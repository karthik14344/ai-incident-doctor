"""Shared machinery for fault injection runs.

Nothing here edits files on the running machine by hand: `push` faults go
through git and the pipeline (a real `git push` to the pipeline remote),
`environment` and `data` faults go through these recorded functions. Every
action is timestamped into the run's timeline.

The doctor is never called from here. It wakes up on its own from the alert
(alert-sink -> /incident) - the scripts only *wait* for its report.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIR = os.path.join(REPO, "runtime", "fault-runs")
sys.path.insert(0, REPO)


def env_file() -> Dict[str, str]:
    out = {}
    path = os.path.join(REPO, ".env")
    if os.path.exists(path):
        for raw in open(path, encoding="utf-8"):
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return {**out, **{k: v for k, v in os.environ.items() if v}}


ENV = env_file()


def setting(name: str, default: Optional[str] = None) -> Optional[str]:
    return ENV.get(name) or default


def now() -> float:
    return time.time()


def iso(ts: Optional[float] = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time(), tz=timezone.utc) \
        .isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_ts(value: str) -> float:
    import re
    text = value.replace("Z", "+00:00")
    m = re.match(r"^([^.]+)\.(\d+)(.*)$", text)
    if m:  # Python 3.10 accepts only 3 or 6 fractional digits
        text = f"{m.group(1)}.{m.group(2)[:6].ljust(6, '0')}{m.group(3)}"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def log(msg: str) -> None:
    print(f"[{iso()}] {msg}", flush=True)


def http(url: str, method: str = "GET", body: Any = None, timeout: float = 30) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


# ---------------------------------------------------------------- git + pipeline

def git(*args: str, check: bool = True) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def head() -> str:
    return git("rev-parse", "HEAD")


def commit(paths: List[str], message: str) -> str:
    git("add", *paths)
    git("commit", "-q", "-m", message)
    return head()


PUSH_REMOTE = setting("FAULT_PUSH_REMOTE", "pipeline")


def push() -> Dict[str, Any]:
    """`git push <remote> main`. With the local pipeline remote the hook runs
    verify + deploy synchronously, so this returns when the deploy is done."""
    sha = head()
    started = now()
    r = subprocess.run(["git", "push", PUSH_REMOTE, "main"], cwd=REPO, capture_output=True, text=True,
                       timeout=int(setting("PIPELINE_TIMEOUT_S", "2400")) * 2 + 120)
    out = (r.stdout + r.stderr)
    return {"sha": sha, "pushed_at": iso(started), "push_returned_at": iso(), "push_seconds": round(now() - started, 1),
            "ok": "pipeline: SUCCESS" in out, "output_tail": out.strip().splitlines()[-4:]}


def deploy_record(sha: str) -> Optional[Dict[str, Any]]:
    path = setting("DEPLOY_LOG_PATH", os.path.join(REPO, "runtime", "deploys.jsonl"))
    if not os.path.exists(path):
        return None
    found = None
    for line in open(path, encoding="utf-8"):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("git_sha") == sha:
            found = rec
    return found


def wait_deploy(sha: str, timeout: float = 1800) -> Dict[str, Any]:
    deadline = now() + timeout
    while now() < deadline:
        rec = deploy_record(sha)
        if rec:
            return rec
        time.sleep(5)
    raise TimeoutError(f"no deploy record for {sha[:7]} within {timeout}s")


def push_and_deploy(label: str, timeline: Dict[str, Any]) -> Dict[str, Any]:
    result = push()
    rec = wait_deploy(result["sha"])
    timeline.setdefault("pushes", []).append({"label": label, **result, "deploy_ts": rec["ts"],
                                              "deploy_outcome": rec["outcome"], "pipeline": rec.get("pipeline")})
    log(f"push {label}: {result['sha'][:7]} deployed ({rec['outcome']}, {result['push_seconds']}s)")
    if rec["outcome"] != "success":
        raise RuntimeError(f"deploy of {result['sha'][:7]} did not succeed: {rec.get('error')}")
    return rec


# ---------------------------------------------------------------- compose

def compose(*args: str, extra_env: Optional[Dict[str, str]] = None, check: bool = True) -> str:
    live = deploy_record(last_deployed_sha()) if last_deployed_sha() else None
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if live:
        env.update({"IMAGE_TAG": live["short_sha"], "APP_GIT_SHA": live["git_sha"], "KB_VERSION": live["kb_version"],
                    **(live.get("component_tags") or {})})
    env.update(extra_env or {})
    r = subprocess.run(["docker", "compose", *args], cwd=REPO, capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)}: {r.stderr.strip()[-400:]}")
    return r.stdout + r.stderr


def last_deployed_sha() -> Optional[str]:
    path = setting("DEPLOY_LOG_PATH", os.path.join(REPO, "runtime", "deploys.jsonl"))
    sha = None
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("outcome") == "success":
                sha = rec["git_sha"]
    return sha


# ---------------------------------------------------------------- traffic

class Load:
    """A loadgen run in a background thread."""

    def __init__(self, **kwargs):
        from loadgen.loadgen import LoadGenerator

        kwargs.setdefault("base_url", setting("GATEWAY_URL"))
        self.gen = LoadGenerator(**kwargs)
        self.summary: Optional[Dict[str, Any]] = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        import asyncio
        self.summary = asyncio.run(self.gen.run())["summary"]

    def start(self) -> "Load":
        self.thread.start()
        return self

    def join(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        self.thread.join(timeout)
        return self.summary


# ---------------------------------------------------------------- alerts and the doctor

def alerts_since(since_iso: str) -> List[Dict[str, Any]]:
    return http(f"{setting('ALERT_SINK_URL').rstrip('/')}/alerts?since={since_iso}")


def wait_alert(since_iso: str, names: Optional[List[str]] = None, timeout: float = 900,
               stop: Optional[Callable[[], bool]] = None) -> Optional[Dict[str, Any]]:
    """First firing alert (of the given names, if any) received after since_iso."""
    deadline = now() + timeout
    t_since = parse_ts(since_iso)
    while now() < deadline:
        for a in alerts_since(since_iso):
            # Only alerts whose condition began after the break: one still firing
            # from something earlier (a deploy blip) is not this fault's symptom.
            began_after = bool(a.get("startsAt")) and parse_ts(a["startsAt"]) >= t_since - 2
            if a.get("status") == "firing" and (not names or a.get("alertname") in names) \
                    and (a.get("labels") or {}).get("severity") in ("warning", "critical") and began_after:
                return a
        if stop and stop():
            return None
        time.sleep(5)
    return None


def doctor_url() -> str:
    return setting("DOCTOR_URL").rstrip("/")


def incident_id_for(alert: Dict[str, Any]) -> str:
    """The id the doctor gives the incident this alert opens (same formula as
    doctor/app/evidence.incident_id; duplicated so this script needs no doctor code)."""
    import hashlib
    key = f"{alert.get('alertname')}|{json.dumps(alert.get('labels', {}), sort_keys=True)}|{alert.get('startsAt')}"
    return "inc_" + hashlib.sha1(key.encode()).hexdigest()[:10]


def wait_report(alert: Dict[str, Any], timeout: float = 1500) -> Optional[Dict[str, Any]]:
    """The finished report of the incident this alert opened (or was joined to).
    Read-only: the doctor was woken by the alert, not by this script."""
    deadline = now() + timeout
    own = incident_id_for(alert)
    while now() < deadline:
        try:
            listing = http(f"{doctor_url()}/api/incidents")
            target = next((i for i in listing if i["id"] == own), None)
            if target is None:  # joined to an incident that was still open
                for inc in listing:
                    meta = (http(f"{doctor_url()}/api/incidents/{inc['id']}").get("incident") or {})
                    if any(j.get("alertname") == alert.get("alertname") and j.get("startsAt") == alert.get("startsAt")
                           for j in meta.get("joined_alerts", [])):
                        target = inc
                        break
            if target and target.get("status") in ("ok", "failed", "interrupted"):
                return {"summary": target, "detail": http(f"{doctor_url()}/api/incidents/{target['id']}")}
        except Exception:
            pass
        time.sleep(10)
    return None


def export_incident(incident_id: str, run_dir: str) -> None:
    os.makedirs(run_dir, exist_ok=True)
    bundle = http(f"{doctor_url()}/api/incidents/{incident_id}/bundle")
    detail = http(f"{doctor_url()}/api/incidents/{incident_id}")
    with open(os.path.join(run_dir, "bundle.json"), "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, indent=1)
    with open(os.path.join(run_dir, "live_report.json"), "w", encoding="utf-8") as fh:
        json.dump(detail, fh, indent=1)
    with open(os.path.join(run_dir, "live_report.md"), "w", encoding="utf-8") as fh:
        fh.write(detail.get("markdown") or "")


def write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=2)


def wait_quiet(seconds: float, reason: str) -> None:
    log(f"waiting {seconds:.0f}s ({reason})")
    time.sleep(seconds)
