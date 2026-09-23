"""Incidents on disk: <data>/incidents/<id>/{bundle.json, report.json, report.md, resolution.json}."""

import json
import os
from typing import Any, Dict, List, Optional

from app.settings import SETTINGS, Settings


def _dir(settings: Settings, incident_id: str) -> str:
    return os.path.join(settings.data_dir, "incidents", incident_id)


def save(incident_id: str, name: str, content: Any, settings: Settings = SETTINGS) -> str:
    path = os.path.join(_dir(settings, incident_id), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        if isinstance(content, str):
            fh.write(content)
        else:
            json.dump(content, fh, indent=1, default=str)
    return path


def load(incident_id: str, name: str, settings: Settings = SETTINGS) -> Optional[Any]:
    path = os.path.join(_dir(settings, incident_id), name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read() if name.endswith(".md") else json.load(fh)


def list_incidents(settings: Settings = SETTINGS) -> List[Dict[str, Any]]:
    root = os.path.join(settings.data_dir, "incidents")
    if not os.path.isdir(root):
        return []
    out = []
    for incident_id in os.listdir(root):
        report = load(incident_id, "report.json", settings)
        bundle_alert = (load(incident_id, "bundle.json", settings) or {}).get("alert", {})
        d = (report or {}).get("diagnosis") or {}
        top = (d.get("hypotheses") or [{}])[0]
        out.append({
            "id": incident_id, "alertname": bundle_alert.get("alertname"),
            "service": (bundle_alert.get("labels") or {}).get("service"),
            "started": bundle_alert.get("startsAt"), "status": (report or {}).get("status", "collecting"),
            "incident_class": d.get("incident_class"), "top_cause": top.get("cause"),
            "suspected_commit": top.get("suspected_commit"), "confidence": top.get("confidence"),
            "verification": ((report or {}).get("verification") or {}).get("status"),
            "provider": (report or {}).get("provider"), "model": (report or {}).get("model"),
            "resolved": load(incident_id, "resolution.json", settings) is not None,
        })
    return sorted(out, key=lambda r: r.get("started") or "", reverse=True)
