"""Deploy the checked-out commit and record it.

    python deploy/deploy.py                # deploy HEAD
    python deploy/deploy.py --reason "ci"  # free text stored in the record

Steps:
  1. Refuse a dirty working tree (the image tag must describe the code in it).
  2. Build every image tagged with the commit's short SHA.
  3. If the knowledge-base version changed, stop ChromaDB so kb-loader can
     swap the index in before it starts again.
  4. `docker compose up -d`, then smoke-test the gateway.
  5. On failure, bring the previous SHA's images back up (rollback).
  6. Append one JSON record to the deploy log and post a Grafana annotation.

The deploy log (runtime/deploys.jsonl, or DEPLOY_LOG_PATH) is what the incident
doctor uses to narrow down which change caused a failure:

    {"ts", "git_sha", "short_sha", "previous_sha", "commits", "services_changed",
     "kb_version", "outcome", "duration_s", "reason", "pipeline", "host"}

`pipeline` is local (the bare-remote stand-in), github (Actions on the Pavilion
runner) or manual (run by hand). Called by scripts/pipeline/deploy.sh.
"""

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Which deployable a changed path belongs to. The patient images all carry the
# whole backend package, but a service is only "changed" if code it runs changed.
PATH_TO_SERVICES = [
    ("patient/common/", ["gateway", "ingestion", "retrieval", "llm"]),
    ("patient/requirements.txt", ["gateway", "ingestion", "retrieval", "llm"]),
    ("patient/api_gateway/", ["gateway"]),
    ("patient/ingestion_service/", ["ingestion", "retrieval", "gateway"]),
    ("patient/retrieval_service/", ["retrieval"]),
    ("patient/llm_service/", ["llm"]),
    ("patient/evaluation/", ["gateway", "llm"]),
    ("patient/kb/", ["kb-loader"]),
    ("patient/frontend/", ["frontend"]),
    ("kb/", ["knowledge-base"]),
    ("dvc.lock", ["knowledge-base"]),
    ("monitoring/", ["monitoring"]),
    ("alert_sink/", ["alert-sink"]),
    ("container_exporter/", ["container-exporter"]),
    ("doctor/", ["doctor"]),
    ("docker-compose.yml", ["compose"]),
]


# Components that are not the patient get the SHA of the last commit that changed
# their own code, so deploying the patient does not recreate them - above all the
# doctor, which must not be restarted mid-diagnosis by the thing it watches.
COMPONENT_TAGS = {
    "DOCTOR_IMAGE_TAG": ["doctor", "loadgen", "patient/requirements.txt"],
    "ALERT_SINK_IMAGE_TAG": ["alert_sink"],
    "CONTAINER_EXPORTER_IMAGE_TAG": ["container_exporter"],
    "MLFLOW_IMAGE_TAG": ["monitoring/mlflow"],
    "FRONTEND_IMAGE_TAG": ["patient/frontend"],
}
SERVICE_TAG_VARS = {"doctor": "DOCTOR_IMAGE_TAG", "alert-sink": "ALERT_SINK_IMAGE_TAG",
                    "container-exporter": "CONTAINER_EXPORTER_IMAGE_TAG", "mlflow": "MLFLOW_IMAGE_TAG",
                    "frontend": "FRONTEND_IMAGE_TAG"}


def component_tags(sha: str) -> Dict[str, str]:
    tags = {}
    for var, paths in COMPONENT_TAGS.items():
        last = git("log", "-1", "--format=%H", sha, "--", *paths)
        tags[var] = (last or sha)[:7]
    return tags


def read_env_file() -> Dict[str, str]:
    values = {}
    path = os.path.join(REPO, ".env")
    if os.path.exists(path):
        for raw in open(path, encoding="utf-8"):
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip()
    return values


ENV = {**read_env_file(), **os.environ}


def setting(name: str, default: Optional[str] = None) -> Optional[str]:
    value = ENV.get(name)
    return value if value else default


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def deploy_log_path() -> str:
    return setting("DEPLOY_LOG_PATH", os.path.join(REPO, "runtime", "deploys.jsonl"))


def read_records() -> List[dict]:
    path = deploy_log_path()
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def last_good_sha() -> Optional[str]:
    for rec in reversed(read_records()):
        if rec.get("outcome") == "success":
            return rec["git_sha"]
    return None


def last_kb_version() -> Optional[str]:
    for rec in reversed(read_records()):
        if rec.get("outcome") == "success":
            return rec.get("kb_version")
    return None


def kb_version() -> str:
    with open(os.path.join(REPO, "kb", "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)["kb_version"]


def changed_services(prev: Optional[str], sha: str) -> Dict[str, List[str]]:
    if not prev:
        return {"services": ["all"], "files": [], "commits": [sha]}
    files = [f for f in git("diff", "--name-only", f"{prev}..{sha}").splitlines() if f]
    commits = [c for c in git("rev-list", "--reverse", f"{prev}..{sha}").splitlines() if c]
    services = set()
    for f in files:
        for prefix, names in PATH_TO_SERVICES:
            if f == prefix or f.startswith(prefix):
                services.update(names)
    return {"services": sorted(services), "files": files, "commits": commits}


def compose(env: Dict[str, str], *args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", *args]
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=REPO, env={**os.environ, **env}, check=check)


def built_services() -> List[str]:
    """Compose services whose image this repository builds (tagged per SHA)."""
    out = subprocess.run(["docker", "compose", "config", "--format", "json"], cwd=REPO,
                         env={**os.environ, "IMAGE_TAG": "x"}, capture_output=True, text=True, check=True).stdout
    services = json.loads(out)["services"]
    return sorted(name for name, svc in services.items() if svc.get("build"))


def image_exists(service: str, tag: str) -> bool:
    prefix = setting("IMAGE_PREFIX", "aid")
    image = {"kb-loader": "ingestion"}.get(service, service)
    return subprocess.run(["docker", "image", "inspect", f"{prefix}/{image}:{tag}"],
                          capture_output=True).returncode == 0


def http_json(url: str, method: str = "GET", body: Optional[dict] = None,
              headers: Optional[dict] = None, timeout: float = 30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"null")


def smoke_test(gateway: str, deadline_s: float = 180) -> Dict[str, object]:
    """The gateway is up, sees every service, and retrieval returns chunks."""
    started = time.time()
    last_error = ""
    while time.time() - started < deadline_s:
        try:
            status = http_json(f"{gateway}/api/system/status", timeout=10)
            offline = [k for k in ("gateway", "ingestion", "retrieval", "llm_service", "ollama")
                       if status.get(k) != "online"]
            if offline:
                raise RuntimeError(f"offline: {offline}")
            found = http_json(f"{gateway}/api/retrieval/search", "POST",
                              {"question": "What is the minimum attendance requirement?"}, timeout=60)
            if not found.get("results_count"):
                raise RuntimeError("retrieval returned no chunks")
            return {"ok": True, "seconds": round(time.time() - started, 1)}
        except Exception as exc:  # retried until the deadline
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(5)
    return {"ok": False, "error": last_error, "seconds": round(time.time() - started, 1)}


def reload_monitoring() -> None:
    """Prometheus rules and Alertmanager routes are bind-mounted config files; a
    deploy that changes them must hot-reload both, or the old rules keep firing."""
    for name in ("PROMETHEUS_URL", "ALERTMANAGER_URL"):
        url = setting(name)
        if not url:
            continue
        for attempt in range(10):
            try:
                req = urllib.request.Request(f"{url.rstrip('/')}/-/reload", data=b"", method="POST")
                urllib.request.urlopen(req, timeout=10).read()
                print(f"reloaded {name}", flush=True)
                break
            except (urllib.error.URLError, OSError):
                time.sleep(3)


def annotate(text: str, tags: List[str]) -> Optional[str]:
    grafana = setting("GRAFANA_URL")
    password = setting("GRAFANA_ADMIN_PASSWORD")
    if not grafana or not password:
        return "skipped: GRAFANA_URL or GRAFANA_ADMIN_PASSWORD not set"
    token = base64.b64encode(f"admin:{password}".encode()).decode()
    try:
        http_json(f"{grafana.rstrip('/')}/api/annotations", "POST",
                  {"time": int(time.time() * 1000), "tags": tags, "text": text},
                  headers={"Authorization": f"Basic {token}"}, timeout=10)
        return None
    except (urllib.error.URLError, OSError) as exc:
        return f"failed: {exc}"


def append_record(record: dict) -> None:
    path = deploy_log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reason", default="manual")
    ap.add_argument("--pipeline", choices=["local", "github", "manual"], default="manual",
                    help="which pipeline produced this deploy; recorded so results from the local "
                         "stand-in and from GitHub Actions are never mixed silently")
    ap.add_argument("--allow-dirty", action="store_true", help="for local experiments only")
    ap.add_argument("--no-build", action="store_true")
    args = ap.parse_args()

    if not args.allow_dirty and git("status", "--porcelain", "--untracked-files=no"):
        print("working tree has uncommitted changes; commit first (the image tag must match the code)",
              file=sys.stderr)
        return 2

    started = time.time()
    sha = git("rev-parse", "HEAD")
    short = sha[:7]
    prev = last_good_sha()
    kb = kb_version()
    change = changed_services(prev, sha)
    tags = component_tags(sha)
    env = {"IMAGE_TAG": short, "APP_GIT_SHA": sha, "KB_VERSION": kb, **tags}

    outcome, error, smoke = "success", None, None
    try:
        if not args.no_build:
            compose(env, "build")
        if kb != last_kb_version():
            compose(env, "stop", "chroma", check=False)
        compose(env, "up", "-d", "--remove-orphans")
        reload_monitoring()
        smoke = smoke_test(setting("GATEWAY_URL"))
        if not smoke["ok"]:
            raise RuntimeError(f"smoke test failed: {smoke.get('error')}")
    except Exception as exc:
        error = str(exc)
        outcome = "failed"
        if prev:
            print(f"deploy of {short} failed ({error}); rolling back to {prev[:7]}", flush=True)
            prev_env = {"IMAGE_TAG": prev[:7], "APP_GIT_SHA": prev, "KB_VERSION": last_kb_version() or kb,
                        **component_tags(prev)}
            # Only services that have an image at the previous SHA can go back to it;
            # a service added by this deploy has none and is simply left alone.
            restorable = [s for s in built_services()
                          if image_exists(s, prev_env.get(SERVICE_TAG_VARS.get(s, ""), prev[:7]))]
            if restorable:
                rollback = compose(prev_env, "up", "-d", "--no-build", *restorable, check=False)
                outcome = "rolled_back" if rollback.returncode == 0 else "rollback_failed"
            else:
                outcome = "rollback_failed"

    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "git_sha": sha,
        "short_sha": short,
        "previous_sha": prev,
        "commits": change["commits"],
        "services_changed": change["services"],
        "files_changed": change["files"][:200],
        "kb_version": kb,
        "component_tags": tags,
        "outcome": outcome,
        "error": error,
        "smoke_test": smoke,
        "duration_s": round(time.time() - started, 1),
        "reason": args.reason,
        "pipeline": args.pipeline,
        "host": socket.gethostname(),
    }
    append_record(record)
    note = annotate(f"deploy {short} ({outcome}): {', '.join(change['services']) or 'no service changes'}",
                    ["deploy", outcome])
    if note:
        print(f"grafana annotation {note}")
    print(json.dumps(record, indent=2))
    return 0 if outcome == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
