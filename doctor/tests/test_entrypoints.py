"""The doctor's entry points: /incident, /ticket, replay - and nothing else."""

import ast
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from app import main, ticket
from conftest import REPO_ROOT


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(main.SETTINGS, "data_dir", str(tmp_path))  # a fresh incident store per test
    queued = []
    monkeypatch.setattr(main, "_work", type("Q", (), {"put": lambda self, x: queued.append(x),
                                                     "qsize": lambda self: len(queued)})())
    monkeypatch.setattr(main.SETTINGS, "auto_diagnose", True)
    main._seen.clear()
    main._open.clear()
    c = TestClient(main.app)
    c.queued = queued
    return c


def _alert(name="ServiceDown", service="retrieval", start="2026-09-23T10:00:00Z", severity="critical"):
    return {"status": "firing", "alertname": name, "startsAt": start, "fingerprint": f"fp-{name}-{service}",
            "labels": {"alertname": name, "service": service, "severity": severity},
            "annotations": {"summary": f"{service} is not answering scrapes"}}


def test_a_firing_alert_opens_an_incident(client):
    r = client.post("/incident", json={"alert": _alert()}).json()
    assert r["status"] == "opened"
    assert client.queued == [r["incident_id"]]


def test_the_same_alert_twice_is_a_duplicate(client):
    client.post("/incident", json={"alert": _alert()})
    assert client.post("/incident", json={"alert": _alert()}).json()["status"] == "duplicate"


def test_a_second_alert_on_the_same_service_joins_the_open_incident(client):
    first = client.post("/incident", json={"alert": _alert()}).json()
    second = client.post("/incident", json={"alert": _alert("DownstreamCallFailures", start="2026-09-23T10:01:00Z")}).json()
    assert second == {"status": "joined", "incident_id": first["incident_id"]}
    assert len(client.queued) == 1


def test_info_alerts_are_not_diagnosed(client):
    r = client.post("/incident", json={"alert": _alert("NoTraffic", severity="info")}).json()
    assert r["status"] == "ignored"


def test_a_resolved_alert_is_ignored(client):
    a = _alert()
    a["status"] = "resolved"
    assert client.post("/incident", json={"alert": a}).json()["status"] == "ignored"


def test_a_ticket_opens_an_incident_with_a_located_window(client, monkeypatch):
    monkeypatch.setattr(ticket, "find_onset", lambda s, e, settings=None: {
        "onset": e - 1200, "signals": [{"metric": "embedding_fallbacks_per_min", "onset": e - 1200,
                                         "value": 14, "baseline": 0}]})
    monkeypatch.setattr(main.SETTINGS, "prometheus_url", "http://prometheus.invalid")
    r = client.post("/ticket", json={"text": "answers have been nonsense", "since": "this morning"}).json()
    assert r["status"] == "opened"
    assert r["window"]["onset_found"] is True
    assert r["window"]["onset_signals"][0]["metric"] == "embedding_fallbacks_per_min"


def test_an_empty_ticket_is_rejected(client):
    assert client.post("/ticket", json={"text": "  "}).status_code == 400


@pytest.mark.parametrize("text,span_h", [
    ("broken for the last 2 hours", 3.0),
    ("started 30 minutes ago", 0.75),
    ("nothing specific", 6.0),
])
def test_rough_windows(text, span_h):
    now = 1_800_000_000.0
    start, end, _ = ticket.rough_window(text, now=now)
    assert end == now
    assert abs((end - start) / 3600 - span_h) < 0.01


def test_since_a_clock_time_starts_before_it():
    now = time.mktime((2026, 9, 23, 16, 0, 0, 0, 0, -1))
    start, _, how = ticket.rough_window("since 14:30", now=now)
    assert "14:30" in how
    assert time.localtime(start).tm_hour == 14


# ---------------------------------------------------------------- the hard rule

def test_no_deploy_or_pipeline_code_ever_calls_the_doctor():
    """A git push must never wake the doctor. Nothing in deploy/ may reference
    the doctor's entry points or its URL."""
    checked = 0
    for top in ("deploy", os.path.join("scripts", "pipeline")):
        for root, _, files in os.walk(os.path.join(REPO_ROOT, top)):
            for name in files:
                if not name.endswith((".py", ".sh")) and name != "post-receive":
                    continue
                checked += 1
                text = open(os.path.join(root, name), encoding="utf-8").read()
                for forbidden in ("/incident", "/ticket", "DOCTOR_URL", "DOCTOR_INCIDENT_URL", "app.replay"):
                    assert forbidden not in text, f"{name} references {forbidden}"
    assert checked >= 5  # deploy.py, verify.sh, deploy.sh, post-receive, init script


def test_deploy_records_say_which_pipeline_made_them():
    text = open(os.path.join(REPO_ROOT, "deploy", "deploy.py"), encoding="utf-8").read()
    assert '"pipeline": args.pipeline' in text
    assert 'choices=["local", "github", "manual"]' in text
    hook = open(os.path.join(REPO_ROOT, "scripts", "pipeline", "post-receive"), encoding="utf-8").read()
    assert "PIPELINE=local" in hook
    wf = open(os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8").read()
    assert "PIPELINE: github" in wf
    assert "scripts/pipeline/verify.sh" in wf and "scripts/pipeline/deploy.sh" in wf


def test_the_workflow_never_calls_the_doctor():
    wf = open(os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8").read()
    for forbidden in ("/incident", "/ticket", "doctor-api", "app.replay", "8100"):
        assert forbidden not in wf


def test_replay_cli_parses_a_stored_bundle(tmp_path, monkeypatch):
    from app import replay, reasoner

    bundle = {"id": "inc_x", "alert": _alert(), "t_alert": 0, "windows": {"incident": [], "baseline": []}}
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle))
    seen = {}

    def fake(b, arm, providers=None, verify_fix=True, **kw):
        seen.update(arm=arm, id=b["id"])
        return {"status": "ok", "incident_id": b["id"], "alert": b["alert"], "arm": arm, "diagnosis": {
            "summary": "s", "incident_class": "dependency_failure", "demand_vs_capacity": {}, "hypotheses": [],
            "fix": {}}, "retrieval": {"time_filtered": []}, "verification": {}, "usage": {}, "timings": {}}

    monkeypatch.setattr(reasoner, "diagnose", fake)
    assert replay.main([str(path), "--arm", "logs_only", "--no-verify", "--out", str(tmp_path / "o")]) == 0
    assert seen == {"arm": "logs_only", "id": "inc_x"}
    assert (tmp_path / "o" / "report.md").exists()


def test_main_module_has_exactly_the_documented_trigger_routes():
    tree = ast.parse(open(main.__file__, encoding="utf-8").read())
    posts = [d.args[0].value for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
             for d in n.decorator_list if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "post"]
    assert sorted(posts) == ["/api/incidents/{incident_id}/resolve", "/incident", "/ticket"]
