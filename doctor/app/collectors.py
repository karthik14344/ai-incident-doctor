"""Evidence collectors: alerts, logs, metrics, deploys, git history, source.

Each collector returns plain JSON-able data. `evidence.collect()` calls them
all for one alert and freezes the result into an evidence bundle, which is what
the reasoning step - and the evaluation's replays - consume.
"""

import json
import os
import re
import statistics
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.settings import SETTINGS, Settings
from app.signatures import signature

PATIENT_SERVICES = ["gateway", "ingestion", "retrieval", "llm"]


# ---------------------------------------------------------------- time helpers

def parse_ts(value: Any) -> float:
    """ISO-8601 (with Z or offset, any precision) or epoch -> epoch seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("Z", "+00:00")
    if "." in text:  # Python < 3.11 cannot parse nanoseconds
        head, _, rest = text.partition(".")
        frac = re.match(r"\d+", rest).group(0)
        text = f"{head}.{frac[:6].ljust(6, '0')}{rest[len(frac):]}"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------- alerts

def load_alerts(settings: Settings = SETTINGS, since: str = "") -> List[Dict[str, Any]]:
    """The incident trigger log, from alert-sink's API."""
    if not settings.alert_sink_url:
        return []
    r = httpx.get(f"{settings.alert_sink_url.rstrip('/')}/alerts", params={"since": since}, timeout=15,
                  trust_env=False)
    r.raise_for_status()
    return r.json()


def related_alerts(alerts: List[Dict[str, Any]], start: float, end: float) -> List[Dict[str, Any]]:
    """Firing alerts whose start falls inside the incident window."""
    out, seen = [], set()
    for a in alerts:
        if a.get("status") != "firing" or not a.get("startsAt"):
            continue
        t = parse_ts(a["startsAt"])
        key = (a.get("alertname"), json.dumps(a.get("labels", {}), sort_keys=True))
        if start <= t <= end and key not in seen:
            seen.add(key)
            out.append({"alertname": a.get("alertname"), "startsAt": a["startsAt"],
                        "labels": a.get("labels", {}), "summary": (a.get("annotations") or {}).get("summary")})
    return sorted(out, key=lambda a: a["startsAt"])


# ---------------------------------------------------------------- logs (Loki)

def _loki_query(settings: Settings, query: str, start: float, end: float, limit: int = 5000) -> List[Tuple[float, Dict, str]]:
    if not settings.loki_url:
        return []
    r = httpx.get(f"{settings.loki_url.rstrip('/')}/loki/api/v1/query_range", params={
        "query": query, "start": str(int(start * 1e9)), "end": str(int(end * 1e9)),
        "limit": str(limit), "direction": "forward"}, timeout=60, trust_env=False)
    r.raise_for_status()
    out = []
    for stream in r.json()["data"]["result"]:
        for ts, line in stream["values"]:
            out.append((int(ts) / 1e9, stream["stream"], line))
    return sorted(out, key=lambda x: x[0])


def group_log_lines(lines: List[Tuple[float, Dict, str]]) -> List[Dict[str, Any]]:
    """Group warning/error lines by log signature, most frequent first."""
    groups: Dict[str, Dict[str, Any]] = {}
    for ts, labels, raw in lines:
        service = labels.get("compose_service", "?")
        try:
            entry = json.loads(raw)
            if not isinstance(entry, dict):
                raise ValueError
        except ValueError:
            entry = {"level": "TEXT", "msg": raw.strip()}
        level = entry.get("level", "TEXT")
        if level == "INFO":
            continue
        sig = entry.get("log_signature") or signature(entry.get("exc_type") or level, entry.get("msg", ""))
        g = groups.get(sig)
        if g is None:
            stack = (entry.get("stack") or "").strip().splitlines()
            g = groups[sig] = {
                "signature": sig, "count": 0, "first_seen": iso(ts), "last_seen": iso(ts),
                "services": set(), "level": level, "message": (entry.get("msg") or "")[:300],
                "exc_type": entry.get("exc_type"), "exc_message": (entry.get("exc_message") or "")[:300],
                "error_file": entry.get("error_file"), "error_line": entry.get("error_line"),
                "error_function": entry.get("error_function"), "stack_tail": stack[-10:],
                "git_shas": set(), "target": entry.get("target"),
            }
        g["count"] += 1
        g["last_seen"] = iso(ts)
        g["services"].add(service)
        if entry.get("git_sha"):
            g["git_shas"].add(entry["git_sha"][:7])
    out = []
    for g in groups.values():
        g["services"] = sorted(g["services"])
        g["git_shas"] = sorted(g["git_shas"])
        out.append(g)
    return sorted(out, key=lambda g: -g["count"])


def collect_logs(settings: Settings, start: float, end: float,
                 services: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    names = "|".join(services or PATIENT_SERVICES)
    # Everything that is not a routine INFO JSON line: warnings, errors, and
    # plain-text output (tracebacks, print statements).
    query = f'{{compose_service=~"{names}"}} != "\\"level\\": \\"INFO\\""'
    return group_log_lines(_loki_query(settings, query, start, end))


# ---------------------------------------------------------------- metrics (Prometheus)

# name -> (PromQL, what it means). Evaluated over the incident window and over
# the baseline window before it, so the model can compare.
METRIC_QUERIES: Dict[str, Tuple[str, str]] = {
    "traffic_rps": ('sum(rate(knowledgeai_http_requests_total{service="gateway",endpoint=~"/api/chat|/api/retrieval/search"}[1m]))',
                    "user-facing request rate at the gateway (chat + search), req/s"),
    "requests_rps": ('sum by (service) (rate(knowledgeai_http_requests_total{endpoint!="/metrics"}[1m]))',
                     "requests per second served, per service"),
    "error_ratio_5xx": ('sum by (service) (rate(knowledgeai_http_requests_total{status=~"5.."}[1m])) '
                        '/ sum by (service) (rate(knowledgeai_http_requests_total{endpoint!="/metrics"}[1m]))',
                        "share of responses that were 5xx, per service"),
    "chat_outcomes_rps": ("sum by (outcome) (rate(knowledgeai_chat_answers_total[1m]))",
                          "chat answers per second by outcome"),
    "latency_p95_s": ('histogram_quantile(0.95, sum by (le, service, endpoint) (rate(knowledgeai_http_request_duration_seconds_bucket{endpoint=~"/api/chat|/api/retrieval/search|/retrieve|/generate"}[1m])))',
                      "p95 request duration in seconds"),
    "latency_p50_s": ('histogram_quantile(0.50, sum by (le, service, endpoint) (rate(knowledgeai_http_request_duration_seconds_bucket{endpoint=~"/api/chat|/api/retrieval/search|/retrieve|/generate"}[1m])))',
                      "median request duration in seconds"),
    "in_flight": ("sum by (service) (knowledgeai_http_requests_in_flight)", "requests being served at once"),
    "process_memory_mb": ("knowledgeai_process_resident_memory_bytes / 1048576", "process RSS in MiB"),
    "container_memory_ratio": ('aid_container_memory_usage_bytes{service=~"gateway|ingestion|retrieval|llm"} '
                               '/ (aid_container_memory_limit_bytes{service=~"gateway|ingestion|retrieval|llm"} > 0)',
                               "container memory as a fraction of its limit"),
    "container_restarts": ('aid_container_restart_count{service=~"gateway|ingestion|retrieval|llm|chroma"}',
                           "Docker restart count (cumulative)"),
    "oom_kills": ('aid_container_oom_kills_total{service=~"gateway|ingestion|retrieval|llm|chroma"}',
                  "OOM kills observed (cumulative)"),
    "service_up": ('up{job=~"gateway|ingestion|retrieval|llm"}', "1 when Prometheus can scrape the service"),
    "embedding_fallbacks_per_min": ("sum by (service) (increase(knowledgeai_embedding_fallback_total[1m]))",
                                    "embeddings answered by the hash fallback, per minute"),
    "zero_chunk_share": ("sum(rate(knowledgeai_zero_chunk_retrievals_total[1m])) / sum(rate(knowledgeai_retrieved_chunks_count[1m]))",
                         "share of retrieval queries that returned no chunks"),
    "downstream_failures_per_min": ("sum by (service, target, reason) (increase(knowledgeai_downstream_failures_total[1m]))",
                                    "failed service-to-service calls per minute"),
    "ollama_p95_s": ("histogram_quantile(0.95, sum by (le, operation) (rate(knowledgeai_ollama_request_duration_seconds_bucket[1m])))",
                     "p95 duration of Ollama calls by operation"),
    "ollama_failures_per_min": ("sum by (operation, reason) (increase(knowledgeai_ollama_failures_total[1m]))",
                                "failed or fallback-answered Ollama calls per minute"),
}


def _series_summary(values: List[float]) -> Dict[str, float]:
    vals = [v for v in values if v == v and v not in (float("inf"), float("-inf"))]
    if not vals:
        return {}
    return {"first": round(vals[0], 4), "last": round(vals[-1], 4), "mean": round(statistics.fmean(vals), 4),
            "max": round(max(vals), 4), "min": round(min(vals), 4), "points": len(vals)}


def _prom_range(settings: Settings, query: str, start: float, end: float, step: int) -> List[Dict[str, Any]]:
    r = httpx.get(f"{settings.prometheus_url.rstrip('/')}/api/v1/query_range", params={
        "query": query, "start": start, "end": end, "step": step}, timeout=30, trust_env=False)
    r.raise_for_status()
    return r.json()["data"]["result"]


def collect_metrics(settings: Settings, incident: Tuple[float, float],
                    baseline: Tuple[float, float]) -> Dict[str, Any]:
    if not settings.prometheus_url:
        return {}
    out: Dict[str, Any] = {}
    for name, (query, meaning) in METRIC_QUERIES.items():
        series: Dict[str, Dict[str, Any]] = {}
        for window, (start, end), step in (("incident", incident, 15), ("baseline", baseline, 60)):
            try:
                result = _prom_range(settings, query, start, end, step)
            except Exception as exc:
                series.setdefault("_error", {})[window] = str(exc)[:200]
                continue
            for s in result:
                key = ",".join(f"{k}={v}" for k, v in sorted(s["metric"].items()) if k not in ("job", "instance")) or "all"
                summary = _series_summary([float(v) for _, v in s["values"]])
                if summary:
                    series.setdefault(key, {})[window] = summary
        out[name] = {"meaning": meaning, "series": series}
    return out


# ---------------------------------------------------------------- deploys

def read_deploys(settings: Settings = SETTINGS) -> List[Dict[str, Any]]:
    path = settings.deploy_log_path
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def deploys_before(records: List[Dict[str, Any]], t: float, lookback_s: float) -> Dict[str, Any]:
    """Deploys in the lookback window before t, and the one live at t."""
    ordered = sorted(records, key=lambda r: parse_ts(r["ts"]))
    live = None
    for r in ordered:
        if parse_ts(r["ts"]) <= t and r.get("outcome") == "success":
            live = r
    window = [r for r in ordered if t - lookback_s <= parse_ts(r["ts"]) <= t and r.get("outcome") == "success"]
    return {"in_window": window, "live": live}


# ---------------------------------------------------------------- git

def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


DIFF_CHARS_PER_FILE = 2500


def commit_info(repo: str, sha: str, with_diff: bool = True) -> Dict[str, Any]:
    fmt = "%H%x1f%an%x1f%aI%x1f%s%x1f%b"
    full, author, date, subject, body = git(repo, "show", "-s", f"--format={fmt}", sha).split("\x1f", 4)
    files = [f for f in git(repo, "show", "--format=", "--name-only", sha).splitlines() if f]
    info = {"sha": full.strip(), "author": author, "date": date, "ts": parse_ts(date),
            "subject": subject, "body": body.strip()[:800], "files": []}
    for path in files:
        entry = {"path": path}
        if with_diff:
            diff = git(repo, "show", "--format=", "--unified=3", sha, "--", path)
            entry["diff"] = diff[:DIFF_CHARS_PER_FILE] + ("\n...[truncated]" if len(diff) > DIFF_CHARS_PER_FILE else "")
        info["files"].append(entry)
    return info


def commits_for_deploys(repo: str, deploys: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every commit shipped by the given deploys, oldest first, tagged with its deploy."""
    out, seen = [], set()
    for d in deploys:
        for sha in d.get("commits") or [d["git_sha"]]:
            if sha in seen:
                continue
            seen.add(sha)
            try:
                info = commit_info(repo, sha)
            except subprocess.CalledProcessError:
                continue
            info["deployed_in"] = d["short_sha"]
            info["deployed_at"] = d["ts"]
            out.append(info)
    return out


# ---------------------------------------------------------------- source around a stack trace

def repo_path_for(container_path: Optional[str]) -> Optional[str]:
    """/app/retrieval_service/app/main.py -> patient/retrieval_service/app/main.py"""
    if not container_path:
        return None
    p = container_path.replace("\\", "/")
    for marker in ("/app/", "/patient/"):
        if marker in p:
            return "patient/" + p.split(marker, 1)[1]
    return None


def source_excerpt(repo: str, sha: str, path: str, line: int, context: int = 12) -> Optional[Dict[str, Any]]:
    try:
        text = git(repo, "show", f"{sha}:{path}")
    except subprocess.CalledProcessError:
        return None
    lines = text.splitlines()
    lo, hi = max(0, line - context - 1), min(len(lines), line + context)
    return {"path": path, "sha": sha[:7], "line": line,
            "excerpt": "\n".join(f"{i + 1:>4}{'>' if i + 1 == line else ' '} {lines[i]}" for i in range(lo, hi))}


def now() -> float:
    return time.time()
