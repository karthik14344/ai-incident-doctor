"""Freeze everything known about one alert into an evidence bundle.

A bundle is self-contained JSON: the alert, related alerts, grouped logs,
metrics for the incident and baseline windows, the deploys before the alert,
every commit those deploys shipped (with diffs), and source around any line a
stack trace names. Reasoning runs on the bundle, never on live systems, which
is what makes an evaluation replay repeatable.
"""

import hashlib
import json
from typing import Any, Dict, List, Optional

from app import collectors as C
from app.settings import SETTINGS, Settings


def incident_id(alert: Dict[str, Any]) -> str:
    key = f"{alert.get('alertname')}|{json.dumps(alert.get('labels', {}), sort_keys=True)}|{alert.get('startsAt')}"
    return "inc_" + hashlib.sha1(key.encode()).hexdigest()[:10]


def collect(alert: Dict[str, Any], settings: Settings = SETTINGS,
            all_alerts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    t_alert = C.parse_ts(alert["startsAt"])
    incident = (t_alert - settings.incident_before_s, t_alert + settings.incident_after_s)
    baseline = (incident[0] - settings.baseline_s, incident[0])
    errors: Dict[str, str] = {}

    try:
        alerts = all_alerts if all_alerts is not None else C.load_alerts(settings)
    except Exception as exc:
        alerts, errors["alerts"] = [], str(exc)

    try:
        logs = C.collect_logs(settings, *incident)
    except Exception as exc:
        logs, errors["logs"] = [], str(exc)
    try:
        baseline_logs = C.collect_logs(settings, *baseline)
    except Exception as exc:
        baseline_logs, errors["baseline_logs"] = [], str(exc)

    try:
        metrics = C.collect_metrics(settings, incident, baseline)
    except Exception as exc:
        metrics, errors["metrics"] = {}, str(exc)

    records = C.read_deploys(settings)
    deploy_view = C.deploys_before(records, t_alert, settings.deploy_lookback_s)
    live = deploy_view["live"]
    try:
        commits = C.commits_for_deploys(settings.repo_root, deploy_view["in_window"])
    except Exception as exc:
        commits, errors["git"] = [], str(exc)

    # The most recent deploy before the alert, even outside the lookback - the
    # "always blame the latest deploy" baseline needs it.
    latest_any = None
    for r in sorted(records, key=lambda r: C.parse_ts(r["ts"])):
        if C.parse_ts(r["ts"]) <= t_alert and r.get("outcome") == "success":
            latest_any = r
    latest_commit = None
    if latest_any:
        try:
            latest_commit = C.commit_info(settings.repo_root, (latest_any.get("commits") or [latest_any["git_sha"]])[-1],
                                          with_diff=False)
        except Exception:
            latest_commit = None

    sources = []
    seen = set()
    if live:
        for g in logs:
            path = C.repo_path_for(g.get("error_file"))
            if path and g.get("error_line") and (path, g["error_line"]) not in seen:
                seen.add((path, g["error_line"]))
                excerpt = C.source_excerpt(settings.repo_root, live["git_sha"], path, int(g["error_line"]))
                if excerpt:
                    sources.append(excerpt)

    kb_changes = [k for k in C.read_kb_loads(settings)
                  if t_alert - settings.deploy_lookback_s <= C.parse_ts(k["ts"]) <= t_alert]

    baseline_sigs = {g["signature"] for g in baseline_logs}
    for g in logs:
        g["new_in_incident"] = g["signature"] not in baseline_sigs

    return {
        "id": incident_id(alert),
        "collected_at": C.iso(C.now()),
        "alert": alert,
        "t_alert": t_alert,
        "windows": {"incident": [C.iso(incident[0]), C.iso(incident[1])],
                    "baseline": [C.iso(baseline[0]), C.iso(baseline[1])]},
        "related_alerts": C.related_alerts(alerts, incident[0], incident[1] + 120),
        "logs": logs[:40],
        "baseline_log_signatures": sorted(baseline_sigs),
        "metrics": metrics,
        "deploys": deploy_view["in_window"],
        "live_deploy": live,
        "latest_deploy": latest_any,
        "latest_commit": latest_commit,
        "candidate_commits": commits,
        "kb_changes": kb_changes,
        "sources": sources[:6],
        "collector_errors": errors,
        "deploy_lookback_s": settings.deploy_lookback_s,
    }
