"""The incident doctor service.

Entry points - the ONLY ways a diagnosis starts. A git push or a deploy never
calls any of them: if the doctor ran because something was deployed, it would
already know the answer is "the thing just deployed" and the evaluation would
be worthless. The pipeline writes the deploy record and stops there; the doctor
only ever starts from a symptom.

    POST /incident    an alert fired. Called automatically by alert-sink for
                      every firing alert (Prometheus -> Alertmanager -> alert-sink
                      -> here). No human involved.
    POST /ticket      a person reports a symptom in free text, no alert fired.
                      The doctor works out the time window itself (app/ticket.py).
    python -m app.replay <incident-id>
                      replay a stored incident from its evidence snapshot
                      (the evaluation uses only this).

Read endpoints for the Incidents page:
    GET  /api/incidents, GET /api/incidents/{id}, GET /api/incidents/{id}/bundle
    POST /api/incidents/{id}/resolve   record the real resolution (joins the
                                       past-incident index)

Every incident's evidence is snapshotted to disk under its id (bundle.json)
before reasoning, so it can be replayed any number of times. Nothing is ever
applied to the running system.
"""

import queue
import threading
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel
from starlette.responses import Response

from app import collectors, evidence, indexes, reasoner, report, store, ticket
from app.settings import SETTINGS, get

app = FastAPI(title="Incident Doctor", version="1.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

INCIDENTS = Counter("doctor_incidents_total", "Incidents opened", ["trigger"])
DIAGNOSES = Counter("doctor_diagnoses_total", "Diagnoses finished", ["status"])
ALERT_TO_REPORT = Histogram("doctor_alert_to_report_seconds", "Alert start to finished report",
                            buckets=(30, 60, 90, 120, 180, 240, 300, 600, 1200))

GROUP_S = int(get("DOCTOR_GROUP_S", "600"))
SEVERITIES = set((get("DOCTOR_SEVERITIES", "warning,critical") or "").split(","))
ARM = get("DOCTOR_ARM", "logs_commits_incidents")

_lock = threading.Lock()
_open: Dict[str, Dict[str, Any]] = {}      # service -> {"id", "t"} of the open incident
_seen: set = set()                           # alert keys already handled
_work: "queue.Queue[str]" = queue.Queue()
_status: Dict[str, Any] = {"busy": None, "last_error": None, "last_catchup": None}


def _now_iso() -> str:
    return collectors.iso(time.time())


def _meta(incident_id: str) -> Dict[str, Any]:
    return store.load(incident_id, "incident.json") or {}


def _update(incident_id: str, **fields: Any) -> Dict[str, Any]:
    meta = {**_meta(incident_id), **fields}
    store.save(incident_id, "incident.json", meta)
    return meta


def accept_alert(alert: Dict[str, Any], trigger: str = "alert") -> Dict[str, Any]:
    """Open an incident for a firing alert, or attach it to the open one."""
    if alert.get("status", "firing") != "firing" or not alert.get("startsAt"):
        return {"status": "ignored", "reason": "not a firing alert"}
    labels = alert.get("labels") or {}
    if trigger == "alert" and labels.get("severity") not in SEVERITIES:
        return {"status": "ignored", "reason": f"severity {labels.get('severity')} is not diagnosed"}
    key = f"{alert.get('fingerprint')}|{alert.get('startsAt')}"
    t = collectors.parse_ts(alert["startsAt"])
    service = labels.get("service") or labels.get("job") or "unknown"
    with _lock:
        if key in _seen:
            return {"status": "duplicate"}
        _seen.add(key)
        current = _open.get(service)
        if trigger == "alert" and current and abs(t - current["t"]) < GROUP_S:
            meta = _meta(current["id"])
            _update(current["id"], joined_alerts=meta.get("joined_alerts", []) + [
                {"alertname": alert.get("alertname"), "startsAt": alert["startsAt"]}])
            return {"status": "joined", "incident_id": current["id"]}
        incident_id = evidence.incident_id(alert)
        _open[service] = {"id": incident_id, "t": t}
    ready_at = t + SETTINGS.incident_after_s + 15 if trigger == "alert" else time.time()
    _update(incident_id, id=incident_id, trigger=trigger, status="open", alert=alert, service=service,
            received_at=_now_iso(), diagnose_after=collectors.iso(ready_at))
    INCIDENTS.labels(trigger).inc()
    _work.put(incident_id)
    return {"status": "opened", "incident_id": incident_id, "diagnose_after": collectors.iso(ready_at)}


def run_diagnosis(incident_id: str) -> Dict[str, Any]:
    meta = _meta(incident_id)
    alert = meta["alert"]
    _update(incident_id, status="collecting", collection_started=_now_iso())
    bundle = evidence.collect(alert)
    bundle["id"] = incident_id
    bundle["trigger"] = meta.get("trigger", "alert")
    store.save(incident_id, "bundle.json", bundle)          # the replayable snapshot
    _update(incident_id, status="diagnosing", evidence_saved=_now_iso())
    result = reasoner.diagnose(bundle, arm=ARM)
    finished = time.time()
    result["trigger"] = meta.get("trigger", "alert")
    result["alert_to_report_s"] = round(finished - collectors.parse_ts(alert["startsAt"]), 1)
    result["received_to_report_s"] = round(finished - collectors.parse_ts(meta["received_at"]), 1)
    store.save(incident_id, "report.json", result)
    store.save(incident_id, "report.md", report.to_markdown(result, bundle))
    _update(incident_id, status=result.get("status", "failed"), report_finished=collectors.iso(finished),
            alert_to_report_s=result["alert_to_report_s"])
    DIAGNOSES.labels(result.get("status", "failed")).inc()
    ALERT_TO_REPORT.observe(result["alert_to_report_s"])
    return result


def worker() -> None:
    """One diagnosis at a time; each waits until its incident window has closed."""
    while True:
        incident_id = _work.get()
        try:
            ready = collectors.parse_ts(_meta(incident_id).get("diagnose_after") or _now_iso())
            delay = ready - time.time()
            if delay > 0:
                time.sleep(delay)
            _status["busy"] = incident_id
            run_diagnosis(incident_id)
        except Exception as exc:  # a broken diagnosis must not stop the worker
            _status["last_error"] = f"{incident_id}: {type(exc).__name__}: {exc}"
            _update(incident_id, status="failed", error=_status["last_error"])
        finally:
            _status["busy"] = None


def catch_up() -> None:
    """Alerts that arrived while the doctor was down: alert-sink kept them.

    Push delivery from alert-sink is the normal path; this poll only fills gaps,
    and shares the same de-duplication, so nothing is diagnosed twice.
    """
    started = time.time()
    while True:
        try:
            since = collectors.iso(started - 3600)
            for a in collectors.load_alerts(SETTINGS, since=since):
                if (a.get("received_at") or "") >= since:
                    accept_alert(a, "alert")
            _status["last_catchup"] = _now_iso()
        except Exception as exc:
            _status["last_error"] = f"catch-up: {type(exc).__name__}: {exc}"
        time.sleep(60)


@app.on_event("startup")
def _start() -> None:
    threading.Thread(target=worker, daemon=True).start()
    if SETTINGS.auto_diagnose and SETTINGS.alert_sink_url:
        threading.Thread(target=catch_up, daemon=True).start()


# ---------------------------------------------------------------- entry points

class IncidentIn(BaseModel):
    alert: Dict[str, Any]


@app.post("/incident")
def incident(req: IncidentIn):
    """Called by alert-sink for every firing alert."""
    if not SETTINGS.auto_diagnose:
        return {"status": "ignored", "reason": "DOCTOR_AUTO_DIAGNOSE=false"}
    return accept_alert(req.alert, "alert")


class TicketIn(BaseModel):
    text: str
    since: Optional[str] = None


@app.post("/ticket")
def submit_ticket(req: TicketIn):
    """A human report. The doctor finds the window from the text and the metrics."""
    if not req.text.strip():
        raise HTTPException(400, "describe the problem")
    alert = ticket.synthetic_alert(req.text, req.since)
    out = accept_alert(alert, "ticket")
    out["window"] = alert["ticket"]
    return out


# ---------------------------------------------------------------- read side

@app.get("/health")
def health():
    return {"service": "doctor", "status": "online", "busy": _status["busy"], "queued": _work.qsize(),
            "last_error": _status["last_error"], "last_catchup": _status["last_catchup"],
            "primary": SETTINGS.primary.label if SETTINGS.primary else None,
            "fallback": SETTINGS.fallback.label if SETTINGS.fallback else None, "arm": ARM}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/incidents")
def list_incidents():
    return store.list_incidents()


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    meta = store.load(incident_id, "incident.json")
    rep = store.load(incident_id, "report.json")
    bundle = store.load(incident_id, "bundle.json")
    if meta is None and rep is None and bundle is None:
        raise HTTPException(404, "unknown incident")
    return {"incident": meta, "report": rep, "markdown": store.load(incident_id, "report.md"),
            "resolution": store.load(incident_id, "resolution.json"),
            "evidence": {"alert": (bundle or {}).get("alert"), "related_alerts": (bundle or {}).get("related_alerts"),
                         "windows": (bundle or {}).get("windows"), "logs": (bundle or {}).get("logs", [])[:10],
                         "deploys": (bundle or {}).get("deploys"), "kb_changes": (bundle or {}).get("kb_changes"),
                         "candidate_commits": [{"sha": c["sha"], "subject": c["subject"], "date": c["date"]}
                                               for c in (bundle or {}).get("candidate_commits", [])]}}


@app.get("/api/incidents/{incident_id}/bundle")
def get_bundle(incident_id: str):
    bundle = store.load(incident_id, "bundle.json")
    if bundle is None:
        raise HTTPException(404, "no evidence snapshot for this incident")
    return bundle


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


def resolution_text(incident_id: str, bundle: Dict[str, Any], res: Dict[str, Any]) -> str:
    alert = bundle.get("alert", {})
    symptoms = "; ".join(f"{g.get('exc_type') or g.get('level')} {(g.get('message') or '')[:80]}"
                         for g in bundle.get("logs", [])[:4])
    return (f"Past incident {incident_id} ({alert.get('startsAt')}): alert {alert.get('alertname')} on "
            f"{(alert.get('labels') or {}).get('service')} - {(alert.get('annotations') or {}).get('summary')}.\n"
            f"Symptoms: {symptoms}\n"
            f"Resolution: class={res['incident_class']}; root cause: {res['root_cause']}; "
            f"guilty commit: {res.get('guilty_commit') or 'none'}; fix: {res['fix']}")


def index_resolution(incident_id: str, bundle: Dict[str, Any], res: Dict[str, Any], index_name: str = "incidents"):
    indexes.incident_index(SETTINGS, index_name).add(
        [incident_id], [resolution_text(incident_id, bundle, res)],
        [{"t_alert": bundle.get("t_alert", 0), "incident_class": res["incident_class"]}])
