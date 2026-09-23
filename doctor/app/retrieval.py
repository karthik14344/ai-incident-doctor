"""Hybrid retrieval of suspect commits, relevant code and past incidents.

Commits, in three steps:
  1. time filter   - only commits shipped by a deploy inside the lookback
                     window before the alert. This set alone is reported as
                     `time_filtered`: it is the baseline retrieval.
  2. lexical       - overlap between identifiers in the evidence (exception
                     types, files and functions from stack traces, words in
                     error messages, symptom vocabulary from anomalous metrics)
                     and identifiers on the commit's changed lines and paths.
  3. semantic      - cosine similarity between the evidence summary and each
                     commit-file chunk (nomic-embed-text), max over the files.
  score = 0.6 * lexical (normalised) + 0.4 * semantic

If the doctor's embeddings are unavailable the ranking degrades to lexical
only and says so.
"""

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from app import indexes as X
from app.settings import SETTINGS, Settings

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_STOP = set("""self none true false return import from def class with for while elif else pass try except
raise async await the and not are was were this that into none str int float dict list any optional print
http https json data value values text item items result results response request requests error errors
line lines file files path app main get set new old add use used using when then than also some all its has
have had been being their there here what which will would could should about after before over under more""".split())

# Symptom -> code vocabulary. Generic operational knowledge ("a fallback counter
# rising points at code that falls back"), not knowledge of any fault.
SYMPTOM_TERMS = {
    "embedding_fallbacks_per_min": ["embed", "embedding", "embedder", "fallback", "timeout", "get_embedding"],
    "ollama_p95_s": ["ollama", "timeout", "embed", "generate"],
    "ollama_failures_per_min": ["ollama", "timeout", "fallback"],
    "process_memory_mb": ["cache", "memory", "dict", "append", "store", "lru", "maxsize"],
    "container_memory_ratio": ["cache", "memory", "dict", "store", "lru", "maxsize"],
    "oom_kills": ["cache", "memory"],
    "container_restarts": ["cache", "memory", "crash"],
    "downstream_failures_per_min": ["timeout", "httpx", "asyncclient", "client", "connect", "url"],
    "error_ratio_5xx": ["exception", "error"],
    "latency_p95_s": ["timeout", "latency", "concurrency", "semaphore"],
    "zero_chunk_share": ["retrieve", "collection", "chunks", "top_k", "vector_store"],
}


def identifiers(text: str) -> List[str]:
    out = []
    for tok in _IDENT.findall(text or ""):
        low = tok.lower()
        if low in _STOP:
            continue
        out.append(low)
        if "_" in low:  # EMBED_TIMEOUT_S also matches "embed", "timeout"
            out.extend(p for p in low.split("_") if len(p) > 2 and p not in _STOP)
    return out


def notable_metric_changes(bundle: Dict[str, Any], ratio: float = 1.5, min_abs: float = 1e-6) -> List[Dict[str, Any]]:
    """Series whose incident-window value departs from the baseline window."""
    changes = []
    for name, block in (bundle.get("metrics") or {}).items():
        for labels, windows in block.get("series", {}).items():
            if labels == "_error":
                continue
            inc = windows.get("incident") or {}
            base = windows.get("baseline") or {}
            if not inc:
                continue
            peak, typical = inc.get("max", 0.0), base.get("mean") if base else None
            if name in ("container_restarts", "oom_kills"):
                delta = inc.get("last", 0) - (base.get("last", inc.get("first", 0)) if base else inc.get("first", 0))
                if delta > 0:
                    changes.append({"metric": name, "labels": labels, "baseline": base.get("last") if base else None,
                                    "incident_max": inc.get("last"), "change": f"+{delta:g}"})
                continue
            if name == "service_up":
                if inc.get("min", 1) < 1:
                    changes.append({"metric": name, "labels": labels, "baseline": base.get("mean") if base else None,
                                    "incident_max": inc.get("min"), "change": "went down"})
                continue
            if typical is None:
                if peak > min_abs:
                    changes.append({"metric": name, "labels": labels, "baseline": None, "incident_max": peak,
                                    "change": "appeared (no baseline)"})
                continue
            if peak > max(typical * ratio, typical + min_abs) and peak > min_abs:
                changes.append({"metric": name, "labels": labels, "baseline": round(typical, 4),
                                "incident_max": peak,
                                "change": f"x{peak / typical:.1f}" if typical > min_abs else "from ~0"})
    return changes


def evidence_terms(bundle: Dict[str, Any]) -> Counter:
    terms: Counter = Counter()
    for g in bundle.get("logs", [])[:15]:
        weight = 3 if g.get("new_in_incident") else 1
        for field in ("exc_type", "error_function", "message", "exc_message", "target"):
            for t in identifiers(str(g.get(field) or "")):
                terms[t] += weight
        for field in ("error_file",):
            for t in identifiers(str(g.get(field) or "").replace("/", " ").replace(".py", "")):
                terms[t] += 2 * weight
        for line in g.get("stack_tail", []):
            for t in identifiers(line):
                terms[t] += 1
    alert = bundle.get("alert", {})
    for t in identifiers(" ".join(str(v) for v in (alert.get("labels") or {}).values())):
        terms[t] += 1
    for change in notable_metric_changes(bundle):
        for t in SYMPTOM_TERMS.get(change["metric"], []):
            terms[t] += 2
        for t in identifiers(change["labels"]):
            terms[t] += 1
    return terms


def commit_terms(commit: Dict[str, Any]) -> Counter:
    terms: Counter = Counter()
    for f in commit.get("files", []):
        for t in identifiers(f["path"].replace("/", " ").replace(".py", "")):
            terms[t] += 1
        for line in (f.get("diff") or "").splitlines():
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                for t in identifiers(line[1:]):
                    terms[t] += 1
    for t in identifiers(commit.get("subject", "")):
        terms[t] += 1
    return terms


def evidence_query_text(bundle: Dict[str, Any]) -> str:
    alert = bundle.get("alert", {})
    parts = [f"{alert.get('alertname')}: {(alert.get('annotations') or {}).get('summary', '')}"]
    for g in bundle.get("logs", [])[:6]:
        parts.append(f"{g.get('exc_type') or g.get('level')} in {g.get('error_file') or g.get('services')}: "
                     f"{g.get('exc_message') or g.get('message')}")
    for c in notable_metric_changes(bundle)[:8]:
        parts.append(f"{c['metric']} {c['labels']} {c['change']}")
    return "\n".join(parts)


def rank_commits(bundle: Dict[str, Any], settings: Settings = SETTINGS, use_embeddings: bool = True,
                 top_k: int = 5) -> Dict[str, Any]:
    candidates = bundle.get("candidate_commits") or []
    time_filtered = [c["sha"] for c in candidates]
    if not candidates:
        return {"time_filtered": [], "ranked": [], "embedding_used": False, "note": "no deploys in the lookback window"}

    ev = evidence_terms(bundle)
    lexical: Dict[str, Tuple[float, List[str]]] = {}
    for c in candidates:
        ct = commit_terms(c)
        matched = sorted(set(ev) & set(ct), key=lambda t: -ev[t])
        score = sum(ev[t] * min(ct[t], 3) for t in matched)
        lexical[c["sha"]] = (float(score), matched[:10])
    top_lex = max(v[0] for v in lexical.values()) or 1.0

    semantic: Dict[str, float] = {}
    embedding_used, note = False, None
    if use_embeddings:
        try:
            idx = X.index_commits(candidates, settings)
            chunk_ids = {X.commit_chunk_id(c["sha"], f["path"]): c["sha"] for c in candidates for f in c["files"]}
            sims = idx.similarities(evidence_query_text(bundle), list(chunk_ids))
            for cid, sim in sims.items():
                sha = chunk_ids[cid]
                semantic[sha] = max(semantic.get(sha, 0.0), sim)
            embedding_used = True
        except X.EmbeddingUnavailable as exc:
            note = f"embeddings unavailable, lexical ranking only ({exc})"

    ranked = []
    for c in candidates:
        lex, matched = lexical[c["sha"]]
        sem = semantic.get(c["sha"], 0.0)
        score = 0.6 * (lex / top_lex) + (0.4 * sem if embedding_used else 0.0)
        ranked.append({"sha": c["sha"], "subject": c["subject"], "deployed_in": c.get("deployed_in"),
                       "lexical": round(lex, 2), "semantic": round(sem, 4), "score": round(score, 4),
                       "matched_terms": matched})
    ranked.sort(key=lambda r: -r["score"])
    return {"time_filtered": time_filtered, "ranked": ranked[:top_k], "all_ranked": ranked,
            "embedding_used": embedding_used, "note": note}


def relevant_code(bundle: Dict[str, Any], files: List[str], settings: Settings = SETTINGS,
                  k: int = 4) -> List[Dict[str, Any]]:
    """Function/class chunks from the live commit, near the evidence."""
    live = bundle.get("live_deploy") or {}
    if not live.get("git_sha"):
        return []
    try:
        idx = X.code_index(live["git_sha"], settings)
        query = evidence_query_text(bundle)
        hits = []
        for path in files[:3]:
            hits.extend(idx.query(query, k=2, where={"path": path}))
        if len(hits) < k:
            hits.extend(idx.query(query, k=k))
    except X.EmbeddingUnavailable:
        return []
    seen, out = set(), []
    for h in hits:
        if h["id"] in seen:
            continue
        seen.add(h["id"])
        out.append({"path": h["meta"]["path"], "name": h["meta"]["name"], "start": h["meta"]["start"],
                    "end": h["meta"]["end"], "imports": h["meta"].get("imports", ""),
                    "similarity": h["similarity"], "text": h["text"][:2500]})
    return out[:k]


def past_incidents(bundle: Dict[str, Any], settings: Settings = SETTINGS, k: int = 3,
                   index_name: str = "incidents", exclude: Optional[set] = None) -> List[Dict[str, Any]]:
    try:
        idx = X.incident_index(settings, index_name)
        hits = idx.query(evidence_query_text(bundle), k=k + len(exclude or ()))
    except X.EmbeddingUnavailable:
        return []
    out = []
    for h in hits:
        if exclude and h["id"] in exclude:
            continue
        if h["meta"].get("t_alert", 0) and float(h["meta"]["t_alert"]) >= bundle.get("t_alert", 0):
            continue  # only incidents that happened before this one
        out.append({"id": h["id"], "similarity": h["similarity"], "summary": h["text"][:1200]})
    return out[:k]
