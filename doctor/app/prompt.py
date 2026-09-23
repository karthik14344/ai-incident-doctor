"""Prompt construction for one diagnosis.

Arms of the ablation study (what evidence the model sees):
    logs_only                 alert, related alerts, grouped logs, metrics
                              (incident vs baseline), source at stack-trace lines
    logs_commits              + deploy records, ranked candidate commits with
                              diffs, relevant code chunks
    logs_commits_incidents    + similar past incidents and how they resolved

The same system prompt is used by every arm and every model.
"""

import json
from typing import Any, Dict, List, Optional

from app.retrieval import notable_metric_changes
from app.schema import COMPONENTS, INCIDENT_CLASSES

ARMS = ["logs_only", "logs_commits", "logs_commits_incidents"]

SYSTEM = f"""You are an incident doctor for KnowledgeAI, a retrieval-augmented document assistant made of
four FastAPI services (gateway -> retrieval -> llm, plus ingestion), a ChromaDB vector store, and a
local Ollama server that does both embeddings (nomic-embed-text) and generation (llama3.2).

An alert fired. Work out the root cause from the evidence and propose a fix. Rules:

1. Answer ONLY with one JSON object matching the schema you are given. No prose outside it.
2. incident_class is exactly one of: {", ".join(INCIDENT_CLASSES)}.
   - code_defect: a code change introduced wrong behaviour.
   - configuration: a setting, address or parameter is wrong (no code logic bug).
   - capacity: the system is healthy but demand exceeds what it can serve.
   - dependency_failure: a service or component the system relies on is down or unreachable.
   - data_issue: the knowledge base / documents / index are missing or wrong.
3. DEMAND VERSUS CAPACITY - decide this before anything else, using the incident window against the
   baseline window:
   - Did demand rise? Compare traffic_rps and in_flight between baseline and incident.
   - Or did capacity fall? Look for a deploy shortly before the onset, errors, restarts, a
     service going down, or the same traffic suddenly being served slower or wrongly.
   - Traffic up with no relevant deploy => capacity. Traffic flat but slower or failing right after a
     deploy => a change caused it. A deploy existing is NOT evidence by itself: only blame a commit
     whose diff plausibly explains the symptoms.
4. suspected_commit must be a SHA from the candidate commit list, or null. For capacity incidents it
   MUST be null - blaming a commit for a capacity problem is a serious error. It must also be null for
   a dependency that is simply down or unreachable unless a listed commit caused that.
5. component is one of: {", ".join(COMPONENTS)}.
6. Give 1-3 hypotheses ranked by confidence (0..1). Each cites concrete evidence (a log signature, a
   metric change, a diff line).
7. fix.kind: "code_diff" (edit source), "config_change" (edit configuration) or "action" (operate the
   system: restart, scale, restore an address). For code_diff/config_change give "edits": each edit
   names a repository path (e.g. patient/retrieval_service/app/main.py), an exact "find" string copied
   from the current code shown to you, and its "replace" string. Keep edits minimal. Never propose to
   apply anything to the running system automatically."""

EXAMPLE = {
    "summary": "one or two sentences",
    "incident_class": "code_defect",
    "demand_vs_capacity": {"traffic_change": "flat", "deploy_before_onset": True, "verdict": "capacity_fell",
                           "reasoning": "..."},
    "hypotheses": [{"cause": "...", "component": "retrieval", "confidence": 0.7,
                    "evidence": ["log signature X appeared at ...", "metric Y rose x10"],
                    "suspected_commit": "<sha from the list or null>", "suspected_files": ["patient/..."]}],
    "fix": {"kind": "code_diff", "edits": [{"file": "patient/...", "find": "exact old text", "replace": "new text"}],
            "action": None, "rationale": "..."},
}


def approx_tokens(text: str) -> int:
    return int(len(text) / 3.6) + 1


def _fmt_metrics(bundle: Dict[str, Any]) -> str:
    rows = []
    keys = ["traffic_rps", "requests_rps", "in_flight", "latency_p95_s", "latency_p50_s", "error_ratio_5xx",
            "chat_outcomes_rps", "downstream_failures_per_min", "ollama_p95_s", "ollama_failures_per_min",
            "embedding_fallbacks_per_min", "zero_chunk_share", "process_memory_mb", "container_memory_ratio",
            "container_restarts", "oom_kills", "service_up"]
    metrics = bundle.get("metrics") or {}
    for name in keys:
        block = metrics.get(name)
        if not block:
            continue
        for labels, w in list(block.get("series", {}).items())[:8]:
            if labels == "_error":
                continue
            b, i = w.get("baseline") or {}, w.get("incident") or {}
            rows.append(f"{name}{{{labels}}}  baseline mean={b.get('mean', 'n/a')} max={b.get('max', 'n/a')}"
                        f"  |  incident mean={i.get('mean', 'n/a')} max={i.get('max', 'n/a')} "
                        f"first={i.get('first', 'n/a')} last={i.get('last', 'n/a')}")
    return "\n".join(rows) or "(no metrics collected)"


def _fmt_logs(bundle: Dict[str, Any], limit: int) -> str:
    out = []
    for g in bundle.get("logs", [])[:limit]:
        where = f"{g.get('error_file')}:{g.get('error_line')} in {g.get('error_function')}" if g.get("error_file") else ""
        out.append(f"- [{g['signature']}] x{g['count']} {g['level']} services={g['services']} "
                   f"{'NEW (absent in baseline)' if g.get('new_in_incident') else 'also in baseline'} "
                   f"first={g['first_seen']} last={g['last_seen']} running={g.get('git_shas')}\n"
                   f"  {g.get('exc_type') or ''} {g.get('exc_message') or g.get('message')} {where}".rstrip())
        if g.get("stack_tail"):
            out.append("  stack: " + " | ".join(line.strip() for line in g["stack_tail"][-4:]))
    return "\n".join(out) or "(no warning or error log lines in the incident window)"


def _fmt_deploys(bundle: Dict[str, Any]) -> str:
    rows = []
    for d in bundle.get("deploys", []):
        rows.append(f"- {d['ts']} deploy {d['short_sha']} ({d.get('outcome')}): services={d.get('services_changed')} "
                    f"commits={len(d.get('commits') or [])} kb={d.get('kb_version')}")
    live = bundle.get("live_deploy")
    head = f"Running at alert time: {live['short_sha']} deployed {live['ts']}\n" if live else ""
    return head + ("\n".join(rows) if rows else "(no deploys in the lookback window before the alert)")


def _fmt_commits(ranked: List[Dict[str, Any]], bundle: Dict[str, Any], diff_chars: int) -> str:
    by_sha = {c["sha"]: c for c in bundle.get("candidate_commits", [])}
    out = []
    for r in ranked:
        c = by_sha[r["sha"]]
        out.append(f"### commit {c['sha']}  ({c['date']}, deployed in {c.get('deployed_in')})\n{c['subject']}\n"
                   f"retrieval: lexical={r['lexical']} semantic={r['semantic']} matched={r['matched_terms'][:6]}")
        budget = diff_chars
        for f in c["files"]:
            diff = (f.get("diff") or "")[:budget]
            budget -= len(diff)
            out.append(f"file {f['path']}\n{diff}")
            if budget <= 0:
                out.append("...[remaining files omitted]")
                break
    return "\n".join(out)


def build(bundle: Dict[str, Any], arm: str, ranked: Optional[Dict[str, Any]] = None,
          code: Optional[List[Dict[str, Any]]] = None, incidents: Optional[List[Dict[str, Any]]] = None,
          max_tokens: int = 6500) -> Dict[str, Any]:
    assert arm in ARMS, arm
    alert = bundle["alert"]
    ticket = alert.get("ticket")
    sections = [] if not ticket else [
        ("USER REPORT (no alert fired; a person reported this)",
         f"{ticket['text']}\nrough time given: {ticket.get('since') or 'none'}\n"
         f"onset located at {alert.get('startsAt')} from: "
         + ("; ".join(f"{s['metric']} rose from {s['baseline']} to {s['value']}" for s in ticket.get("onset_signals", []))
            or "no metric departed from its baseline in the searched range"))]
    sections += [
        ("ALERT", f"{alert.get('alertname')} labels={json.dumps(alert.get('labels', {}))}\n"
                  f"summary: {(alert.get('annotations') or {}).get('summary')}\n"
                  f"description: {(alert.get('annotations') or {}).get('description')}\nstartsAt: {alert.get('startsAt')}"),
        ("WINDOWS", f"incident window {bundle['windows']['incident']}; baseline window {bundle['windows']['baseline']}"),
        ("OTHER ALERTS IN THE WINDOW", "\n".join(f"- {a['startsAt']} {a['alertname']} {a['labels'].get('service', '')}: "
                                                   f"{a.get('summary')}" for a in bundle.get("related_alerts", [])) or "(none)"),
        ("NOTABLE METRIC CHANGES (incident vs baseline)",
         "\n".join(f"- {c['metric']}{{{c['labels']}}}: baseline={c['baseline']} incident_max={c['incident_max']} ({c['change']})"
                   for c in notable_metric_changes(bundle)[:25]) or "(none detected)"),
        ("METRICS", _fmt_metrics(bundle)),
        ("LOG SIGNATURES (warnings/errors, grouped)", _fmt_logs(bundle, 15)),
        ("SOURCE AT STACK-TRACE LINES", "\n\n".join(f"{s['path']} @ {s['sha']}\n{s['excerpt']}"
                                                    for s in bundle.get("sources", [])) or "(no stack traces)"),
    ]
    candidates: List[str] = []
    if arm in ("logs_commits", "logs_commits_incidents"):
        sections.append(("DEPLOYS BEFORE THE ALERT", _fmt_deploys(bundle)))
        sections.append(("KNOWLEDGE-BASE VERSIONS LOADED BEFORE THE ALERT",
                         "\n".join(f"- {k['ts']} kb {k.get('previous')} -> {k['kb_version']} "
                                   f"collections={k.get('collections')}" for k in bundle.get("kb_changes", []))
                         or "(no knowledge-base change in the lookback window)"))
        top = (ranked or {}).get("ranked", [])
        candidates = [r["sha"] for r in top]
        sections.append(("CANDIDATE COMMITS (the only SHAs you may name; ranked by retrieval)",
                         _fmt_commits(top, bundle, 1800) if top else
                         "(none: no deploy in the lookback window, so no commit can be blamed)"))
        if code:
            sections.append(("RELEVANT CODE AT THE RUNNING COMMIT (function/class chunks)",
                             "\n\n".join(f"{c['path']} :: {c['name']} (lines {c['start']}-{c['end']})\n{c['text'][-1800:]}"
                                         for c in code)))
    if arm == "logs_commits_incidents":
        sections.append(("SIMILAR PAST INCIDENTS (resolved)",
                         "\n\n".join(f"- ({p['similarity']}) {p['summary']}" for p in (incidents or []))
                         or "(no similar past incidents)"))

    schema_text = "Return JSON shaped like this example (values are placeholders):\n" + json.dumps(EXAMPLE, indent=1)

    def render(secs):
        return "\n\n".join(f"## {title}\n{body}" for title, body in secs) + "\n\n" + schema_text

    user = render(sections)
    # Trim the longest optional sections until the prompt fits the budget.
    trim_order = ["METRICS", "RELEVANT CODE AT THE RUNNING COMMIT (function/class chunks)",
                  "SIMILAR PAST INCIDENTS (resolved)", "SOURCE AT STACK-TRACE LINES",
                  "CANDIDATE COMMITS (the only SHAs you may name; ranked by retrieval)"]
    while approx_tokens(SYSTEM + user) > max_tokens:
        longest = max(((i, s) for i, s in enumerate(sections) if s[0] in trim_order), key=lambda x: len(x[1][1]),
                      default=None)
        if longest is None or len(longest[1][1]) < 400:
            break
        i, (title, body) = longest
        sections[i] = (title, body[: int(len(body) * 0.7)] + "\n...[trimmed to fit the context budget]")
        user = render(sections)
    return {"system": SYSTEM, "user": user, "candidates": candidates,
            "approx_prompt_tokens": approx_tokens(SYSTEM + user)}


def repair(previous_output: str, errors: List[str]) -> str:
    return ("Your previous answer was not valid:\n" + "\n".join(f"- {e}" for e in errors) +
            "\n\nReturn the corrected JSON object only.\n\nPrevious answer:\n" + previous_output[:6000])
