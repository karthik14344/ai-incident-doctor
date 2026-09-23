"""The incident doctor service.

    GET  /health
    GET  /metrics
    GET  /api/incidents                     list, newest first
    GET  /api/incidents/{id}                report JSON + markdown + evidence summary
    POST /api/incidents/diagnose            {"alert": {...}} or {"fingerprint": "..."} - diagnose now
    POST /api/incidents/{id}/resolve        {"root_cause", "incident_class", "fix"} - record the real
                                            resolution; it joins the past-incident index

A background watcher polls alert-sink. For each new firing alert of severity
warning or critical it waits until the incident window has closed, collects
evidence, diagnoses, and stores the report. Alerts that start within
DOCTOR_GROUP_S of an open incident on the same service join it instead of
opening a new one. Nothing is ever applied to the running system.
"""

import threading
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel
from starlette.responses import Response

from app import collectors, evidence, indexes, reasoner, report, store
from app.settings import SETTINGS, get

app = FastAPI(title="Incident Doctor", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DIAGNOSES = Counter("doctor_diagnoses_total", "Diagnoses finished", ["status"])
DIAGNOSIS_SECONDS = Histogram("doctor_alert_to_report_seconds", "Alert start to finished report",
                              buckets=(30, 60, 90, 120, 180, 240, 300, 600, 1200))

GROUP_S = int(get("DOCTOR_GROUP_S", "600"))
SEVERITIES = set((get("DOCTOR_SEVERITIES", "warning,critical") or "").split(","))
_lock = threading.Lock()
_state: Dict[str, Any] = {"seen": set(), "open": [], "last_poll": None, "last_error": None, "busy": None}


def run_diagnosis(alert: Dict[str, Any], arm: str = "logs_commits_incidents") -> Dict[str, Any]:
    bundle = evidence.collect(alert)
    store.save(bundle["id"], "bundle.json", bundle)
    result = reasoner.diagnose(bundle, arm=arm)
    t_alert = collectors.parse_ts(alert["startsAt"])
    result["alert_to_report_s"] = round(time.time() - t_alert, 1)
    store.save(bundle["id"], "report.json", result)
    store.save(bundle["id"], "report.md", report.to_markdown(result, bundle))
    DIAGNOSES.labels(result.get("status", "failed")).inc()
    DIAGNOSIS_SECONDS.observe(result["alert_to_report_s"])
    return result


def _should_open(alert: Dict[str, Any]) -> bool:
    if alert.get("status") != "firing":
        return False
    if (alert.get("labels") or {}).get("severity") not in SEVERITIES:
        return False
    t = collectors.parse_ts(alert["startsAt"])
    service = (alert.get("labels") or {}).get("service")
    for inc in _state["open"]:
        if inc["service"] == service and abs(t - inc["t"]) < GROUP_S:
            return False
    return True


def watcher() -> None:
    since = collectors.iso(time.time() - 3600)
    pending = []
    while True:
        try:
            alerts = collectors.load_alerts(SETTINGS, since="")
            _state["last_poll"] = collectors.iso(time.time())
            for a in alerts:
                key = f"{a.get('fingerprint')}|{a.get('startsAt')}"
                if key in _state["seen"] or (a.get("received_at") or "") < since:
                    continue
                _state["seen"].add(key)
                if _should_open(a):
                    _state["open"].append({"service": (a.get("labels") or {}).get("service"),
                                           "t": collectors.parse_ts(a["startsAt"])})
                    pending.append(a)
            ready = [a for a in pending
                     if time.time() > collectors.parse_ts(a["startsAt"]) + SETTINGS.incident_after_s + 15]
            for a in ready:
                pending.remove(a)
                _state["busy"] = a.get("alertname")
                try:
                    run_diagnosis(a)
                finally:
                    _state["busy"] = None
            _state["open"] = [o for o in _state["open"] if time.time() - o["t"] < GROUP_S]
        except Exception as exc:  # the watcher must never die
            _state["last_error"] = f"{type(exc).__name__}: {exc}"
        time.sleep(10)


@app.on_event("startup")
def _start_watcher() -> None:
    if SETTINGS.auto_diagnose and SETTINGS.alert_sink_url:
        threading.Thread(target=watcher, daemon=True).start()


@app.get("/health")
def health():
    return {"service": "doctor", "status": "online", "watcher": {
        "last_poll": _state["last_poll"], "last_error": _state["last_error"], "busy": _state["busy"]},
        "primary": SETTINGS.primary.label if SETTINGS.primary else None,
        "fallback": SETTINGS.fallback.label if SETTINGS.fallback else None}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/incidents")
def list_incidents():
    return store.list_incidents()


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    rep = store.load(incident_id, "report.json")
    bundle = store.load(incident_id, "bundle.json")
    if rep is None and bundle is None:
        raise HTTPException(404, "unknown incident")
    return {"report": rep, "markdown": store.load(incident_id, "report.md"),
            "resolution": store.load(incident_id, "resolution.json"),
            "evidence": {"alert": (bundle or {}).get("alert"), "related_alerts": (bundle or {}).get("related_alerts"),
                         "windows": (bundle or {}).get("windows"), "logs": (bundle or {}).get("logs", [])[:10],
                         "deploys": (bundle or {}).get("deploys"),
                         "candidate_commits": [{"sha": c["sha"], "subject": c["subject"], "date": c["date"]}
                                               for c in (bundle or {}).get("candidate_commits", [])]}}


class DiagnoseRequest(BaseModel):
    alert: Optional[Dict[str, Any]] = None
    fingerprint: Optional[str] = None
    arm: str = "logs_commits_incidents"


@app.post("/api/incidents/diagnose")
def diagnose_now(req: DiagnoseRequest):
    alert = req.alert
    if alert is None and req.fingerprint:
        matches = [a for a in collectors.load_alerts(SETTINGS) if a.get("fingerprint") == req.fingerprint
                   and a.get("status") == "firing"]
        alert = matches[-1] if matches else None
    if not alert:
        raise HTTPException(400, "give an alert or the fingerprint of a firing alert")
    return run_diagnosis(alert, arm=req.arm)


class Resolution(BaseModel):
    root_cause: str
    incident_class: str
    fix: str
    guilty_commit: Optional[str] = None


@app.post("/api/incidents/{incident_id}/resolve")
def resolve(incident_id: str, res: Resolution):
    bundle = store.load(incident_id, "bundle.json")
    if bundle is None:
        raise HTTPException(404, "unknown incident")
    store.save(incident_id, "resolution.json", res.model_dump())
    index_resolution(incident_id, bundle, res.model_dump())
    return {"status": "resolved", "indexed": True}


def index_resolution(incident_id: str, bundle: Dict[str, Any], res: Dict[str, Any], index_name: str = "incidents"):
    alert = bundle.get("alert", {})
    text = (f"Past incident {incident_id} ({alert.get('startsAt')}): alert {alert.get('alertname')} on "
            f"{(alert.get('labels') or {}).get('service')} - {(alert.get('annotations') or {}).get('summary')}.\n"
            f"Symptoms: {'; '.join((g.get('exc_type') or g.get('level')) + ' ' + (g.get('message') or '')[:80] for g in bundle.get('logs', [])[:4])}\n"
            f"Resolution: class={res['incident_class']}; root cause: {res['root_cause']}; "
            f"guilty commit: {res.get('guilty_commit') or 'none'}; fix: {res['fix']}")
    indexes.incident_index(SETTINGS, index_name).add(
        [incident_id], [text], [{"t_alert": bundle.get("t_alert", 0), "incident_class": res["incident_class"]}])
