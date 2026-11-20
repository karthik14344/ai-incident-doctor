"""Hand-off to the agent team: the hierarchical stage after the doctor's report.

The doctor still does what only it can do - collect the evidence (metrics, logs,
deploys, commits) and write a diagnosis. It then hands every incident to the
agent team, CodeFix AI (the separate AGAI project, reached over HTTP and never
imported or copied), where a Manager agent delegates to a Diagnoser, a Fixer and
a Tester:

    doctor report --> Manager --> Diagnoser (ReAct over our repo)
                         |   <--  diagnosis
                         +------> Fixer       (writes the patch)
                         |   <--  patch
                         +------> Tester      (our own test suite, on a clone)
                         |   <--  pass -> PR waits for a human
                         |        fail -> back to the Fixer WITH the failure log (max 3)
                         +------> escalation, written up, when nothing passes

Env/capacity incidents go to the team as well; when no code change can fix them
the Manager escalates with a summary, and the doctor's own suggested action
stays the answer.

Nothing here touches the running system. The team works on throw-away clones
of the repo, and a Pull Request is only opened after a person confirms it on
the Incidents page (POST /api/incidents/{id}/agents/pr).

State per incident: <data>/incidents/<id>/agents.json (a compact summary of
the team's run, refreshed while it runs).
"""

import re
import threading
import time
from typing import Any, Dict, List, Optional

import httpx

from app import store
from app.settings import SETTINGS

FILE = "agents.json"
FINISHED = {"awaiting_approval", "done", "escalated", "failed", "error", "rejected"}
POLL_S = 8
GIVE_UP_S = 45 * 60          # a run still "running" after this is reported as stalled
MAX_REPORT = 12_000          # AGAI's input guardrail allows 20 000 chars

_following: set = set()
_lock = threading.Lock()


def enabled() -> bool:
    return bool(SETTINGS.agents_url)


def _api(path: str) -> str:
    return SETTINGS.agents_url.rstrip("/") + path


def run_link(task_id: Optional[str]) -> Optional[str]:
    """Where a person opens the team's live run page (Manager decisions, ReAct, patch, tests)."""
    base = SETTINGS.agents_public_url or SETTINGS.agents_url
    return f"{base.rstrip('/')}/run.html?id={task_id}" if (base and task_id) else None


# ---------------------------------------------------------------- the brief

_CONTAINER_PATH = re.compile(r"/app/(api_gateway|ingestion_service|retrieval_service|llm_service|common)/")


def repo_path(text: str) -> str:
    """Container paths (/app/api_gateway/...) -> repo paths (patient/api_gateway/...)."""
    return _CONTAINER_PATH.sub(lambda m: f"patient/{m.group(1)}/", text or "")


def stack_trace(bundle: Dict[str, Any]) -> str:
    traces = []
    for g in bundle.get("logs") or []:
        if g.get("stack_tail"):
            traces.append("\n".join(g["stack_tail"]))
        if len(traces) == 2:
            break
    return repo_path("\n\n".join(traces))[:6000]


def brief(report: Dict[str, Any], bundle: Dict[str, Any]) -> str:
    """The bug report the Manager receives: the doctor's findings in plain words."""
    d = report.get("diagnosis") or {}
    alert = report.get("alert") or bundle.get("alert") or {}
    labels, ann = alert.get("labels") or {}, alert.get("annotations") or {}
    lines: List[str] = [
        f"Production incident on the KnowledgeAI app (service: {labels.get('service', 'unknown')}).",
        f"Alert: {alert.get('alertname')} - {ann.get('summary') or ann.get('description') or ''}",
        f"Started: {alert.get('startsAt')}. Running commit: {(report.get('live_sha') or '')[:12]}.",
        "",
        "The incident doctor (a monitoring agent) collected metrics, logs and recent commits and concluded:",
        f"- Summary: {d.get('summary', 'no diagnosis')}",
        f"- Incident class: {d.get('incident_class', 'unknown')}",
    ]
    for i, h in enumerate((d.get("hypotheses") or [])[:2], 1):
        lines.append(f"- Hypothesis {i} ({h.get('confidence')}): {h.get('cause')} "
                     f"[component {h.get('component')}, suspected commit {h.get('suspected_commit') or 'none'}]")
        if h.get("suspected_files"):
            lines.append(f"  Files: {', '.join(h['suspected_files'][:5])}")
        for ev in (h.get("evidence") or [])[:4]:
            lines.append(f"  Evidence: {ev}")
    fix = d.get("fix") or {}
    lines.append(f"- Doctor's suggested fix ({fix.get('kind')}): {fix.get('rationale', '')}")
    if fix.get("action"):
        lines.append(f"  Action: {fix['action']}")
    errors = [g for g in (bundle.get("logs") or []) if g.get("level") != "TEXT"][:4]
    if errors:
        lines += ["", "Most frequent errors in the logs during the incident:"]
        for g in errors:
            where = f" at {repo_path(g.get('error_file') or '')}:{g.get('error_line')}" if g.get("error_file") else ""
            lines.append(f"- x{g.get('count')} {g.get('exc_type') or g.get('level')}: "
                         f"{g.get('exc_message') or g.get('message')}{where}")
    lines += ["", "Find the root cause in this repository. The application code is under patient/. "
              "If a code change fixes it, make the smallest patch and keep the existing tests passing. "
              "If no code change can fix it (capacity, a stopped container, an outside service), say so."]
    return repo_path("\n".join(lines))[:MAX_REPORT]


# ---------------------------------------------------------------- hand-off

def hand_off(incident_id: str, report: Dict[str, Any], bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Start the team's hierarchical run for this incident. Never raises."""
    if not enabled():
        return store.update(incident_id, FILE, {"status": "off", "note": "DOCTOR_AGENTS_URL is not set"})
    store.update(incident_id, FILE, {"status": "starting", "requested_at": _now(), "error": None})
    body = {"bug_report": brief(report, bundle), "stack_trace": stack_trace(bundle),
            "repo": SETTINGS.agents_repo, "arch": "hierarchical", "llm": "live",
            "max_attempts": SETTINGS.agents_max_attempts}
    try:
        r = httpx.post(_api("/api/runs"), json=body, timeout=30)
        r.raise_for_status()
        task_id = r.json()["task_id"]
    except Exception as exc:  # the team is optional: the doctor's own report stands
        detail = exc.response.text[:300] if isinstance(exc, httpx.HTTPStatusError) else str(exc)[:300]
        return store.update(incident_id, FILE, {"status": "unreachable", "error": f"{type(exc).__name__}: {detail}"})
    state = store.update(incident_id, FILE, {"status": "running", "task_id": task_id, "url": run_link(task_id),
                                             "started_at": _now()})
    follow(incident_id)
    return state


def follow(incident_id: str) -> None:
    """Poll the team's run in the background until it finishes."""
    with _lock:
        if incident_id in _following:
            return
        _following.add(incident_id)
    threading.Thread(target=_follow, args=(incident_id,), daemon=True, name=f"agents-{incident_id}").start()


def _follow(incident_id: str) -> None:
    try:
        started = time.time()
        while time.time() - started < GIVE_UP_S:
            state = refresh(incident_id)
            if state.get("status") in FINISHED or state.get("status") == "lost":
                return
            time.sleep(POLL_S)
        store.update(incident_id, FILE, {"status": "stalled",
                                         "error": f"still running after {GIVE_UP_S // 60} min"})
    finally:
        with _lock:
            _following.discard(incident_id)


def refresh(incident_id: str) -> Dict[str, Any]:
    """Pull the run's current state from the team and keep a compact copy."""
    state = store.load(incident_id, FILE) or {}
    task_id = state.get("task_id")
    if not task_id or not enabled():
        return state
    try:
        r = httpx.get(_api(f"/api/runs/{task_id}"), timeout=20)
        if r.status_code == 404:
            return store.update(incident_id, FILE, {"status": "lost", "error": "the team no longer has this run"})
        r.raise_for_status()
        snap = r.json()
    except Exception as exc:
        return store.update(incident_id, FILE, {"poll_error": f"{type(exc).__name__}: {str(exc)[:200]}"})
    return store.update(incident_id, FILE, {**summarise(snap), "poll_error": None})


def summarise(snap: Dict[str, Any]) -> Dict[str, Any]:
    run = snap.get("run") or {}
    diag = snap.get("diagnosis") or {}
    patch = snap.get("patch") or {}
    test = snap.get("test_report") or {}
    esc = snap.get("escalation") or {}
    pr = snap.get("pr") or {}
    steps = []
    for m in snap.get("messages") or []:
        if m.get("status") in ("in_progress", "success", "failure"):
            steps.append({"t": m.get("timestamp"), "agent": m.get("sender"), "to": m.get("target_agent"),
                          "kind": m.get("kind"), "status": m.get("status")})
    decisions = [{"t": e.get("ts"), "event": e.get("event"), "choice": e.get("decision"),
                  "why": (e.get("reason") or "")[:300]} for e in snap.get("manager_decisions") or []]
    usage = snap.get("llm_usage") or []
    return {
        "status": run.get("status"), "outcome": run.get("outcome"), "failure_stage": run.get("failure_stage"),
        "attempts": run.get("attempts"), "max_attempts": run.get("max_attempts"),
        "duration_ms": run.get("duration_ms"),
        "cost_usd": round(sum(u.get("cost") or 0 for u in usage), 4) if usage else run.get("cost_usd"),
        "diagnosis": {k: diag.get(k) for k in ("root_cause", "implicated_files", "evidence", "confidence",
                                               "degraded", "react_steps") if diag.get(k) is not None} or None,
        "patch": {"diff": (patch.get("diff") or "")[:20000], "rationale": patch.get("rationale"),
                  "files": patch.get("files_touched"), "attempt": patch.get("attempt_no")} if patch else None,
        "tests": {k: test.get(k) for k in ("passed", "total", "failed", "failure_stage", "failing_assertions",
                                           "duration_ms")} if test else None,
        "escalation": {k: esc.get(k) for k in ("reason", "summary", "attempts", "tried")
                       if esc.get(k) is not None} or None,
        "pr": {k: pr.get(k) for k in ("url", "branch", "pushed", "note", "commit_sha") if pr.get(k) is not None}
        or None,
        "steps": steps[-40:], "decisions": decisions[-20:],
        "updated_at": _now(),
    }


def open_pr(incident_id: str, confirm: bool) -> Dict[str, Any]:
    """The human gate: a person confirms (or declines) the team's Pull Request."""
    state = store.load(incident_id, FILE) or {}
    task_id = state.get("task_id")
    if not task_id:
        raise LookupError("the agent team has no run for this incident")
    r = httpx.post(_api(f"/api/runs/{task_id}/pr"), json={"confirm": bool(confirm)}, timeout=240)
    if r.status_code >= 400:
        raise ValueError(r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json")
                         else r.text[:300])
    return refresh(incident_id)


def resume_all() -> None:
    """After a doctor restart: keep following runs that were still in progress."""
    for inc in store.list_incidents():
        state = store.load(inc["id"], FILE) or {}
        if state.get("task_id") and state.get("status") not in FINISHED | {"lost", "stalled"}:
            follow(inc["id"])


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
