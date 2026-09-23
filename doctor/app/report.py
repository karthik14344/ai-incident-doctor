"""Render a diagnosis report as markdown (the JSON is the report itself)."""

from typing import Any, Dict


def _short(sha):
    return sha[:7] if sha else "none"


def to_markdown(report: Dict[str, Any], bundle: Dict[str, Any]) -> str:
    alert = report.get("alert") or {}
    lines = [f"# Incident {report['incident_id']}", ""]
    lines += [f"**Alert:** {alert.get('alertname')} - {(alert.get('annotations') or {}).get('summary')}",
              f"**Started:** {alert.get('startsAt')}  ",
              f"**Running commit:** {_short(report.get('live_sha'))}  ",
              f"**Evidence arm:** {report.get('arm')}  ",
              f"**Reasoned by:** {report.get('provider')}:{report.get('model')}", ""]
    if report.get("status") != "ok":
        lines += ["## Diagnosis failed", "", str(report.get("error")), ""]
        for a in report.get("provider_failures", []):
            lines.append(f"- {a['provider']}: {a['error']}")
        return "\n".join(lines) + "\n"

    d = report["diagnosis"]
    dvc = d.get("demand_vs_capacity", {})
    lines += ["## What broke", "", d.get("summary", ""), "",
              f"**Incident class:** `{d.get('incident_class')}`", "",
              "**Demand versus capacity:** traffic "
              f"{dvc.get('traffic_change')}, deploy before onset: {dvc.get('deploy_before_onset')}, "
              f"verdict: {dvc.get('verdict')}. {dvc.get('reasoning', '')}", ""]

    lines += ["## Evidence", ""]
    for a in bundle.get("related_alerts", [])[:8]:
        lines.append(f"- alert {a['startsAt']} **{a['alertname']}** {a['labels'].get('service', '')}: {a.get('summary')}")
    for g in bundle.get("logs", [])[:6]:
        lines.append(f"- log `{g['signature']}` x{g['count']} in {', '.join(g['services'])}: "
                     f"{(g.get('exc_type') or '')} {(g.get('exc_message') or g.get('message') or '')[:160]}")
    from app.retrieval import notable_metric_changes
    for c in notable_metric_changes(bundle)[:8]:
        lines.append(f"- metric `{c['metric']}{{{c['labels']}}}` baseline {c['baseline']} -> {c['incident_max']} ({c['change']})")
    lines += ["", f"Deploys in the lookback window: {len(bundle.get('deploys', []))}; "
              f"candidate commits (time filter only): {len(report['retrieval']['time_filtered'])}", ""]

    lines += ["## Ranked causes", "", "| # | confidence | component | suspected commit | cause |", "|---|---|---|---|---|"]
    for i, h in enumerate(d.get("hypotheses", []), 1):
        lines.append(f"| {i} | {h.get('confidence', 0):.2f} | {h.get('component')} | {_short(h.get('suspected_commit'))} "
                     f"| {h.get('cause', '').replace('|', '/')} |")
    for i, h in enumerate(d.get("hypotheses", []), 1):
        if h.get("evidence"):
            lines += ["", f"Evidence for #{i}:"] + [f"- {e}" for e in h["evidence"][:6]]

    fix = d.get("fix", {})
    lines += ["", "## Proposed fix", "", f"**Kind:** {fix.get('kind')}", "", fix.get("rationale", ""), ""]
    if fix.get("action"):
        lines += [f"**Recommended action:** {fix['action']}", ""]
    if fix.get("unified_diff"):
        lines += ["```diff", fix["unified_diff"].rstrip(), "```", ""]
    if fix.get("edit_problems"):
        lines += ["Edits that could not be applied:"] + [f"- {p}" for p in fix["edit_problems"]] + [""]

    v = report.get("verification", {})
    lines += ["## Verification", "", f"**Result:** {v.get('status')}"]
    if v.get("reason"):
        lines.append(f"  \n{v['reason']}")
    if v.get("suite"):
        lines.append(f"  \nTest suite on the patched copy: {v['suite'].get('summary')}")
    if v.get("acceptance"):
        lines.append(f"  \nAcceptance test: {v['acceptance'].get('summary')}")
    lines += ["", "Nothing was applied to the running system.", ""]
    if d.get("constraint_violations"):
        lines += ["## Rule violations by the model", ""] + [f"- {x}" for x in d["constraint_violations"]] + [""]
    u = report.get("usage", {})
    lines += ["## Cost", "", f"{u.get('calls')} calls, {u.get('prompt_tokens')} prompt + {u.get('completion_tokens')} "
              f"completion tokens, ${u.get('cost_usd')}; reasoning {report['timings'].get('llm_s')}s, "
              f"total {report['timings'].get('total_s')}s", ""]
    return "\n".join(lines)
