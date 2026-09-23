"""The CI/CD pipeline, run locally on a push - the same two jobs as
.github/workflows/ci.yml.

This project must not be pushed to GitHub by the build itself, so the
end-to-end "push -> test -> deploy" loop runs against a local bare remote
(`deploy/setup_local_remote.py` creates it). Its post-receive hook starts this
script in the background for every push to main:

    job 1  lint-and-test   ruff, the patient / alert-sink / doctor test suites,
                           compose validation
    job 2  deploy          deploy/deploy.py: SHA-tagged build, compose up, smoke
                           test, rollback on failure, deploy record, Grafana
                           annotation

Job 2 only runs when job 1 passed. Once the GitHub repository and the Pavilion
runner exist, ci.yml does exactly this and the local remote is no longer needed.

The pipeline ends at the deploy record. It never contacts the incident doctor:
the doctor is woken only by symptoms (alerts, tickets), never by a change.

Each run appends a record to runtime/pipeline_runs.jsonl and keeps job logs in
runtime/pipeline/<sha>/.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_step(name: str, cmd, log, cwd=REPO, env=None) -> bool:
    log.write(f"\n=== {name}: {' '.join(cmd)}\n")
    log.flush()
    r = subprocess.run(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, **(env or {})})
    log.write(f"=== {name}: exit {r.returncode}\n")
    log.flush()
    return r.returncode == 0


def job_lint_and_test(log) -> bool:
    steps = [
        ("ruff", [PY, "-m", "ruff", "check", "."], REPO),
        ("patient tests", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"], os.path.join(REPO, "patient")),
        ("alert-sink tests", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"], os.path.join(REPO, "alert_sink")),
        ("doctor tests", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "doctor/tests"], REPO),
        ("compose config", ["docker", "compose", "config", "--quiet"], REPO),
    ]
    ok = True
    for name, cmd, cwd in steps:
        env = {"IMAGE_TAG": "ci"} if name == "compose config" else None
        if not run_step(name, cmd, log, cwd=cwd, env=env):
            ok = False
            break
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", required=True, help="the pushed commit")
    ap.add_argument("--ref", default="refs/heads/main")
    args = ap.parse_args()

    workdir = os.path.join(REPO, "runtime", "pipeline", args.sha[:12])
    os.makedirs(workdir, exist_ok=True)
    record = {"sha": args.sha, "ref": args.ref, "pushed_at": now_iso(), "jobs": {}}

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    if head != args.sha:
        # The runner's workspace is this checkout; it must be at the pushed commit.
        record["jobs"]["checkout"] = {"ok": False, "error": f"workspace is at {head[:7]}, push was {args.sha[:7]}"}
    else:
        started = time.time()
        with open(os.path.join(workdir, "job1-lint-and-test.log"), "w", encoding="utf-8") as log:
            ok1 = job_lint_and_test(log)
        record["jobs"]["lint-and-test"] = {"ok": ok1, "seconds": round(time.time() - started, 1)}
        if ok1 and args.ref == "refs/heads/main":
            started = time.time()
            with open(os.path.join(workdir, "job2-deploy.log"), "w", encoding="utf-8") as log:
                ok2 = run_step("deploy", [PY, "deploy/deploy.py", "--reason", f"pipeline push {args.sha[:7]}"], log)
            record["jobs"]["deploy"] = {"ok": ok2, "seconds": round(time.time() - started, 1)}
    record["finished_at"] = now_iso()
    with open(os.path.join(REPO, "runtime", "pipeline_runs.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return 0 if all(j.get("ok") for j in record["jobs"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
