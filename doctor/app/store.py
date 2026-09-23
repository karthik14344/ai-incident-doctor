"""Incidents on disk: <data>/incidents/<id>/{bundle.json, report.json, report.md, resolution.json}."""

import json
import os
import tempfile
import threading
from typing import Any, Dict, List, Optional

from app.settings import SETTINGS, Settings

# The worker, the catch-up poll and request handlers all write incident files.
# Unsynchronised writes to one file interleaved and corrupted it ("Extra data"),
# which killed a diagnosis; writes are now serialised and atomic (temp + rename),
# so a reader sees either the old file or the new one, never a mixture.
_WRITE_LOCK = threading.RLock()


def _dir(settings: Settings, incident_id: str) -> str:
    return os.path.join(settings.data_dir, "incidents", incident_id)


def save(incident_id: str, name: str, content: Any, settings: Settings = SETTINGS) -> str:
    path = os.path.join(_dir(settings, incident_id), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content, indent=1, default=str)
    with _WRITE_LOCK:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=f".{name}.")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    return path


def update(incident_id: str, name: str, fields: Dict[str, Any], settings: Settings = SETTINGS) -> Dict[str, Any]:
    """Read-modify-write of a JSON file under the lock."""
    with _WRITE_LOCK:
        current = load(incident_id, name, settings) or {}
        merged = {**current, **fields}
        save(incident_id, name, merged, settings)
        return merged


def load(incident_id: str, name: str, settings: Settings = SETTINGS) -> Optional[Any]:
    path = os.path.join(_dir(settings, incident_id), name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read() if name.endswith(".md") else json.load(fh)
    except ValueError:  # a file damaged before writes were made atomic
        return None


def list_incidents(settings: Settings = SETTINGS) -> List[Dict[str, Any]]:
    root = os.path.join(settings.data_dir, "incidents")
    if not os.path.isdir(root):
        return []
    out = []
    for incident_id in os.listdir(root):
        meta = load(incident_id, "incident.json", settings) or {}
        report = load(incident_id, "report.json", settings)
        alert = meta.get("alert") or (load(incident_id, "bundle.json", settings) or {}).get("alert", {})
        d = (report or {}).get("diagnosis") or {}
        top = (d.get("hypotheses") or [{}])[0]
        out.append({
            "id": incident_id, "alertname": alert.get("alertname"),
            "service": (alert.get("labels") or {}).get("service") or meta.get("service"),
            "started": alert.get("startsAt"),
            "status": meta.get("status") or (report or {}).get("status", "collecting"),
            "trigger": meta.get("trigger") or (report or {}).get("trigger", "alert"),
            "incident_class": d.get("incident_class"), "top_cause": top.get("cause"),
            "suspected_commit": top.get("suspected_commit"), "confidence": top.get("confidence"),
            "verification": ((report or {}).get("verification") or {}).get("status"),
            "provider": (report or {}).get("provider"), "model": (report or {}).get("model"),
            "alert_to_report_s": meta.get("alert_to_report_s") or (report or {}).get("alert_to_report_s"),
            "resolved": load(incident_id, "resolution.json", settings) is not None,
        })
    return sorted(out, key=lambda r: r.get("started") or "", reverse=True)
