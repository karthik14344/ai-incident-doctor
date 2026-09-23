"""Ticket trigger: a human reports a symptom in free text and no alert fired.

"Since this morning answers have been nonsense." There is no startsAt, so the
doctor has to find the incident window itself:

  1. `rough_window(text)` turns the rough time in the ticket ("since this
     morning", "for the last 2 hours", "since 14:30", "yesterday") into a
     search range, defaulting to the last 6 hours.
  2. `find_onset()` scans a fixed set of symptom metrics over that range and
     returns the earliest point where one of them departs from its own level at
     the start of the range. That becomes the synthetic alert's startsAt.

This is exactly the case of the silent timeout regression when the
fallback-rate alert is not tuned: answers are wrong, nothing fired, and the
only trace is a counter nobody was alerted on.
"""

import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.collectors import iso
from app.settings import SETTINGS, Settings

# Symptom series scanned for an onset. Each is expected to be flat (or zero)
# while healthy; a departure marks when the trouble started.
ONSET_QUERIES = {
    "embedding_fallbacks_per_min": "sum(increase(knowledgeai_embedding_fallback_total[1m]))",
    "chat_errors_per_min": 'sum(increase(knowledgeai_chat_answers_total{outcome=~"error|refused_scope|refused_output"}[1m]))',
    "http_5xx_per_min": 'sum(increase(knowledgeai_http_requests_total{status=~"5..",endpoint!="/metrics"}[1m]))',
    "downstream_failures_per_min": "sum(increase(knowledgeai_downstream_failures_total[1m]))",
    "zero_chunk_per_min": "sum(increase(knowledgeai_zero_chunk_retrievals_total[1m]))",
    "chat_p95_s": 'histogram_quantile(0.95, sum by (le) (rate(knowledgeai_http_request_duration_seconds_bucket{service="gateway",endpoint="/api/chat"}[2m])))',
    "restarts": 'sum(aid_container_restart_count{service=~"gateway|ingestion|retrieval|llm"})',
}

_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "few": 3,
              "couple": 2, "several": 3}


def rough_window(text: str, now: Optional[float] = None, default_hours: float = 6.0) -> Tuple[float, float, str]:
    """(start, end, how) - the range in which to look for the onset."""
    now = now or time.time()
    t = (text or "").lower()
    local_now = datetime.fromtimestamp(now)
    m = re.search(r"(?:last|past|for)\s+(\d+|a|an|one|two|three|four|five|six|few|couple|several)\s*"
                  r"(?:of\s+)?(min(?:ute)?s?|hours?|hrs?|h)\b", t)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _NUM_WORDS[m.group(1)]
        seconds = n * (60 if m.group(2).startswith("min") else 3600)
        return now - seconds * 1.5, now, f"'{m.group(0)}' (searched 1.5x that span)"
    m = re.search(r"(\d+)\s*(min(?:ute)?s?|hours?|hrs?|h)\s+ago", t)
    if m:
        seconds = int(m.group(1)) * (60 if m.group(2).startswith("min") else 3600)
        return now - seconds * 1.5, now, f"'{m.group(0)}'"
    m = re.search(r"since\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) == "pm" and hour < 12:
            hour += 12
        start = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start.timestamp() > now:
            start -= timedelta(days=1)
        return start.timestamp() - 900, now, f"since {hour:02d}:{minute:02d} local"
    if "this morning" in t or "morning" in t:
        start = local_now.replace(hour=5, minute=0, second=0, microsecond=0)
        return start.timestamp(), now, "this morning (from 05:00 local)"
    if "yesterday" in t:
        start = (local_now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp(), now, "since yesterday"
    if "today" in t:
        start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp(), now, "today"
    return now - default_hours * 3600, now, f"no time given (last {default_hours:g} h)"


def _series(settings: Settings, query: str, start: float, end: float, step: int) -> List[Tuple[float, float]]:
    r = httpx.get(f"{settings.prometheus_url.rstrip('/')}/api/v1/query_range",
                  params={"query": query, "start": start, "end": end, "step": step}, timeout=30, trust_env=False)
    r.raise_for_status()
    out: List[Tuple[float, float]] = []
    for s in r.json()["data"]["result"]:
        for ts, v in s["values"]:
            try:
                val = float(v)
            except ValueError:
                continue
            if val == val:  # drop NaN
                out.append((float(ts), val))
    return sorted(out)


def find_onset(start: float, end: float, settings: Settings = SETTINGS) -> Dict[str, Any]:
    """Earliest departure of any symptom metric from its level at the start of the range."""
    span = max(end - start, 60)
    step = max(15, int(span / 400))
    found: List[Dict[str, Any]] = []
    for name, query in ONSET_QUERIES.items():
        try:
            points = _series(settings, query, start, end, step)
        except Exception:
            continue
        if len(points) < 4:
            continue
        head = [v for _, v in points[: max(3, len(points) // 10)]]
        base = sorted(head)[len(head) // 2]
        threshold = max(base * 2.0, base + (0.5 if name != "chat_p95_s" else 5.0))
        for ts, v in points:
            if v > threshold:
                found.append({"metric": name, "onset": ts, "value": round(v, 3), "baseline": round(base, 3)})
                break
    if not found:
        return {"onset": None, "signals": []}
    found.sort(key=lambda f: f["onset"])
    return {"onset": found[0]["onset"], "signals": found}


def synthetic_alert(text: str, since: Optional[str], settings: Settings = SETTINGS,
                    now: Optional[float] = None) -> Dict[str, Any]:
    start, end, how = rough_window(f"{since or ''} {text}", now=now)
    onset = find_onset(start, end, settings) if settings.prometheus_url else {"onset": None, "signals": []}
    starts = onset["onset"] or max(start, end - 1800)
    return {
        "status": "firing",
        "alertname": "UserReport",
        "startsAt": iso(starts),
        "fingerprint": f"ticket-{int(time.time())}",
        "labels": {"alertname": "UserReport", "severity": "warning", "source": "ticket"},
        "annotations": {"summary": text.strip()[:400],
                        "description": f"Reported by a user; no alert fired. Rough time: {since or 'not given'}."},
        "ticket": {"text": text, "since": since, "search_range": [iso(start), iso(end)], "how": how,
                   "onset_signals": onset["signals"],
                   "onset_found": onset["onset"] is not None},
    }
