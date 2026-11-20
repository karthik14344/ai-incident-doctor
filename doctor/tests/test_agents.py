"""The hand-off from the doctor's report to the agent team (app/agents.py)."""

import httpx
import pytest

from app import agents, store
from app.settings import SETTINGS

REPORT = {
    "live_sha": "8b35c3b2419b58d6154bf1055a8fa3870a292774",
    "alert": {"alertname": "HighErrorRate", "startsAt": "2026-09-23T15:02:03Z",
              "labels": {"service": "gateway"}, "annotations": {"summary": "gateway is answering 6% with 5xx"}},
    "diagnosis": {
        "summary": "chat_stream reads a misspelt field", "incident_class": "code_defect",
        "hypotheses": [{"cause": "typo req.qestion", "component": "gateway", "confidence": 0.8,
                        "evidence": ["AttributeError x27"], "suspected_commit": "15c1b17",
                        "suspected_files": ["patient/api_gateway/app/main.py"]}],
        "fix": {"kind": "code_diff", "rationale": "use req.question"},
    },
}
BUNDLE = {"logs": [{
    "level": "ERROR", "count": 27, "exc_type": "AttributeError", "message": "unhandled exception",
    "exc_message": "'ChatRequest' object has no attribute 'qestion'",
    "error_file": "/app/api_gateway/app/main.py", "error_line": 477,
    "stack_tail": ['  File "/app/api_gateway/app/main.py", line 477, in chat_stream',
                   "AttributeError: 'ChatRequest' object has no attribute 'qestion'"],
}]}


@pytest.fixture
def team(monkeypatch):
    monkeypatch.setattr(SETTINGS, "agents_url", "http://agai:8080")
    monkeypatch.setattr(SETTINGS, "agents_public_url", "http://vm:8200")
    monkeypatch.setattr(agents, "follow", lambda incident_id: None)   # no background poller in tests


def test_container_paths_become_repo_paths():
    assert agents.repo_path('File "/app/api_gateway/app/main.py"') == 'File "patient/api_gateway/app/main.py"'
    assert agents.repo_path("/usr/local/lib/python3.10/site-packages/x.py") == \
        "/usr/local/lib/python3.10/site-packages/x.py"


def test_brief_carries_the_doctors_findings_and_the_errors():
    text = agents.brief(REPORT, BUNDLE)
    assert "HighErrorRate" in text and "code_defect" in text and "15c1b17" in text
    assert "patient/api_gateway/app/main.py:477" in text
    assert "/app/" not in text.replace("patient/api_gateway/app/", "")
    assert len(text) <= agents.MAX_REPORT
    assert "patient/api_gateway/app/main.py" in agents.stack_trace(BUNDLE)


def test_without_a_team_url_the_doctor_works_alone(monkeypatch):
    monkeypatch.setattr(SETTINGS, "agents_url", None)
    assert agents.hand_off("inc_off", REPORT, BUNDLE)["status"] == "off"


def test_hand_off_starts_a_hierarchical_run(team, monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        sent.update(url=url, body=json)
        return httpx.Response(200, json={"task_id": "t-123"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(agents.httpx, "post", fake_post)
    state = agents.hand_off("inc_ok", REPORT, BUNDLE)
    assert sent["url"] == "http://agai:8080/api/runs"
    assert sent["body"]["arch"] == "hierarchical" and sent["body"]["repo"] == SETTINGS.agents_repo
    assert state["status"] == "running" and state["task_id"] == "t-123"
    assert state["url"] == "http://vm:8200/run.html?id=t-123"
    assert store.load("inc_ok", agents.FILE)["task_id"] == "t-123"


def test_an_unreachable_team_never_breaks_the_report(team, monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(agents.httpx, "post", boom)
    state = agents.hand_off("inc_down", REPORT, BUNDLE)
    assert state["status"] == "unreachable" and "refused" in state["error"]


def test_summary_keeps_manager_decisions_patch_tests_and_pr():
    snap = {
        "run": {"status": "awaiting_approval", "outcome": "passed", "attempts": 2, "max_attempts": 3},
        "diagnosis": {"root_cause": "typo", "implicated_files": ["patient/api_gateway/app/main.py"],
                      "confidence": 0.9},
        "patch": {"diff": "--- a/x\n+++ b/x\n", "rationale": "fix typo", "files_touched": ["x"], "attempt_no": 2},
        "test_report": {"passed": True, "total": 241, "failed": 0},
        "messages": [{"timestamp": "t1", "sender": "manager", "target_agent": "fixer", "kind": "dispatch",
                      "status": "in_progress"}],
        "manager_decisions": [{"ts": "t0", "event": "test report: FAILED", "decision": "fixer",
                               "reason": "retry with the failure log"}],
        "llm_usage": [{"cost": 0.01}, {"cost": 0.02}],
    }
    s = agents.summarise(snap)
    assert s["status"] == "awaiting_approval" and s["attempts"] == 2
    assert s["decisions"][0]["choice"] == "fixer" and s["steps"][0]["to"] == "fixer"
    assert s["patch"]["files"] == ["x"] and s["tests"]["total"] == 241
    assert s["cost_usd"] == 0.03 and s["escalation"] is None and s["pr"] is None
