"""Verify a proposed fix without touching the running system.

Code and config fixes (adapted from the patient's evaluation/code_eval.py,
which runs model-written code against a fixed pytest suite in a throwaway
directory): export the patient at the running commit, apply the diff, run the
test suite in a subprocess with a timeout. The result is `verified` only if the
diff applies and every test passes; anything else is
`unverified - needs human review`.

An optional acceptance test (the evaluation passes the fault's own test) is
run separately and reported separately: the suite answers "did the fix break
anything", the acceptance test answers "did it fix the fault".

Load fixes: start the patched service from the sandbox on a spare port, next
to (not instead of) the live stack, replay the incident's load against it, and
check p95 latency / error rate / memory growth against the thresholds - and do
the same for the unpatched code, so the comparison is like for like.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

import httpx

from app.fixes import Sandbox

VERIFIED = "verified"
UNVERIFIED = "unverified - needs human review"
NOT_APPLICABLE = "not applicable"

SUITE_TIMEOUT_S = 420

# Test runs never talk to real services: conftest.py pins these.
_TEST_ENV = {"PYTHONDONTWRITEBYTECODE": "1", "KNOWLEDGEAI_ENV_FILE": os.devnull,
             "OLLAMA_BASE_URL": "http://localhost:11434", "INGESTION_SERVICE_URL": "http://127.0.0.1:18001",
             "RETRIEVAL_SERVICE_URL": "http://127.0.0.1:18002", "LLM_SERVICE_URL": "http://127.0.0.1:18003",
             "CHROMA_HOST": ""}


def _pytest(workdir: str, target: str, timeout: int = SUITE_TIMEOUT_S) -> Dict[str, Any]:
    env = {**os.environ, **_TEST_ENV}
    env.pop("MLFLOW_TRACKING_URI", None)
    started = time.perf_counter()
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=line", target],
                           cwd=os.path.join(workdir, "patient"), capture_output=True, text=True, env=env,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"passed": False, "summary": f"timed out after {timeout}s", "seconds": timeout}
    tail = (r.stdout + r.stderr).strip().splitlines()
    return {"passed": r.returncode == 0, "returncode": r.returncode, "summary": tail[-1] if tail else "",
            "output_tail": "\n".join(tail[-15:]), "seconds": round(time.perf_counter() - started, 1)}


def verify_code_fix(repo: str, sha: str, diff: str, acceptance_tests: Optional[List[str]] = None,
                    run_suite: bool = True) -> Dict[str, Any]:
    result: Dict[str, Any] = {"kind": "code", "sha": sha[:7]}
    if not diff or not diff.strip():
        return {**result, "status": UNVERIFIED, "reason": "no applicable diff was produced"}
    with Sandbox(repo, sha) as box:
        applied, message = box.patch(diff)
        result["applied"] = applied
        if not applied:
            return {**result, "status": UNVERIFIED, "reason": f"diff does not apply: {message}"}
        if run_suite:
            result["suite"] = _pytest(box.dir, "tests")
        for i, path in enumerate(acceptance_tests or []):
            dest = os.path.join(box.dir, "patient", "tests", f"test_acceptance_{i}.py")
            shutil.copy(path, dest)
        if acceptance_tests:
            result["acceptance"] = _pytest(box.dir, "tests/" + " tests/".join(
                f"test_acceptance_{i}.py" for i in range(len(acceptance_tests))), timeout=180)
    suite_ok = result.get("suite", {}).get("passed", not run_suite)
    result["status"] = VERIFIED if suite_ok else UNVERIFIED
    if not suite_ok:
        result["reason"] = "test suite failed on the patched copy"
    return result


# ---------------------------------------------------------------- load verification

SERVICE_MODULES = {
    "gateway": ("api_gateway.app.main:app", "/api/health"),
    "retrieval": ("retrieval_service.app.main:app", "/health"),
    "llm": ("llm_service.app.main:app", "/health"),
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _rss_mb(pid: int) -> Optional[float]:
    try:
        import psutil
        return psutil.Process(pid).memory_info().rss / 1048576
    except Exception:
        return None


class SandboxService:
    """One patient service running from a sandbox copy, beside the live stack."""

    def __init__(self, box_dir: str, service: str, env: Dict[str, str]):
        module, self.health = SERVICE_MODULES[service]
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        data_dir = os.path.join(box_dir, "sandbox_data")
        os.makedirs(data_dir, exist_ok=True)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(self.port),
             "--no-access-log"], cwd=os.path.join(box_dir, "patient"),
            env={**os.environ, **env, "KNOWLEDGEAI_ENV_FILE": os.devnull, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def wait(self, timeout: float = 60) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if httpx.get(self.url + self.health, timeout=2, trust_env=False).status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            if self.proc.poll() is not None:
                return False
            time.sleep(0.5)
        return False

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _load_run(service: SandboxService, profile: Dict[str, Any]) -> Dict[str, Any]:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    from loadgen.loadgen import run as load_run

    rss_before = _rss_mb(service.proc.pid)
    out = load_run(base_url=service.url, mode=profile.get("mode", "chat"), rate=profile.get("rate", 1.0),
                   concurrency=profile.get("concurrency", 8), duration=profile.get("duration", 60),
                   unique=profile.get("unique", False), timeout=profile.get("timeout", 180))
    rss_after = _rss_mb(service.proc.pid)
    summary = out["summary"]
    summary["rss_mb_before"] = round(rss_before, 1) if rss_before else None
    summary["rss_mb_after"] = round(rss_after, 1) if rss_after else None
    summary["rss_growth_mb"] = round(rss_after - rss_before, 1) if rss_before and rss_after else None
    return summary


def verify_load_fix(repo: str, sha: str, diff: Optional[str], service: str, profile: Dict[str, Any],
                    env: Dict[str, str], thresholds: Dict[str, float]) -> Dict[str, Any]:
    """Replay the incident's load against unpatched and patched sandboxes."""
    result: Dict[str, Any] = {"kind": "load", "service": service, "profile": profile, "thresholds": thresholds}
    if service not in SERVICE_MODULES:
        return {**result, "status": NOT_APPLICABLE, "reason": f"no sandbox for service '{service}'"}
    runs = {}
    for label, patch in (("before", None), ("after", diff)):
        with Sandbox(repo, sha) as box:
            if patch:
                ok, msg = box.patch(patch)
                if not ok:
                    return {**result, "status": UNVERIFIED, "reason": f"diff does not apply: {msg}"}
            svc = SandboxService(box.dir, service, env)
            try:
                if not svc.wait():
                    return {**result, "status": UNVERIFIED, "reason": f"patched {service} did not start"}
                runs[label] = _load_run(svc, profile)
            finally:
                svc.stop()
    result["before"], result["after"] = runs["before"], runs["after"]
    after = runs["after"]
    checks = {}
    if "p95_s" in thresholds and after.get("p95_s") is not None:
        checks["p95_below_threshold"] = after["p95_s"] < thresholds["p95_s"]
    if "error_rate" in thresholds:
        checks["error_rate_below_threshold"] = after["error_rate"] <= thresholds["error_rate"]
    if "rss_growth_mb" in thresholds and after.get("rss_growth_mb") is not None:
        checks["memory_growth_below_threshold"] = after["rss_growth_mb"] < thresholds["rss_growth_mb"]
    result["checks"] = checks
    result["status"] = VERIFIED if checks and all(checks.values()) else UNVERIFIED
    return result
