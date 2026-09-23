"""Render evaluation results as markdown tables (pasted into RESULTS.md)."""

from typing import Any, Dict, List

DELIVERIES = ["environment", "data", "push", "all"]


def _fmt(cell) -> str:
    if cell is None:
        return "-"
    if isinstance(cell, dict):
        if cell.get("mean") is None:
            return "-"
        if cell.get("repeats", 1) > 1:
            return f"{cell['mean']:.2f} ({cell['min']:.2f}-{cell['max']:.2f})"
        return f"{cell['mean']:.2f}"
    if isinstance(cell, float):
        return f"{cell:.2f}"
    return str(cell)


def _row(label: str, agg: Dict[str, Any], keys: List[str]) -> str:
    return "| " + label + " | " + " | ".join(_fmt(agg.get(k)) for k in keys) + " |"


def table(title: str, entries: List[tuple], keys: List[str], headers: List[str]) -> str:
    lines = [f"#### {title}", "", "| | " + " | ".join(headers) + " |", "|---|" + "---|" * len(headers)]
    for label, agg in entries:
        if agg:
            lines.append(_row(label, agg, keys))
    return "\n".join(lines) + "\n"


def write_markdown(results: Dict[str, Any]) -> str:
    out = [f"### Evaluation {results['generated']}", "",
           f"Incidents: {len(results['incidents'])}; repeats per configuration: {results['repeats']}; "
           f"ablation model: `{results['primary_model']}`"
           f"{' (cloud)' if results['primary_is_cloud'] else ' (local stand-in: no cloud API key was configured)'}.",
           "Cells show the mean over repeats with the (min-max) range across repeats.", ""]
    if results.get("skipped"):
        out += ["Not run: " + "; ".join(f"{s['model']} ({s['reason']})" for s in results["skipped"]), ""]

    keys = ["acc_at_1", "acc_at_3", "class_correct", "false_attribution", "guilty_in_retrieved",
            "fix_verified", "fix_acceptance_passed", "reasoning_s", "tokens_per_incident", "cost_usd_per_incident"]
    headers = ["acc@1", "acc@3", "class", "false attr.", "guilty retrieved", "fix verified (suite)",
               "fix correct (acceptance)", "reasoning s", "tokens", "cost $"]

    groups = results["groups"]
    for delivery in DELIVERIES:
        entries = []
        base = results["baseline_most_recent_deploy"].get(delivery)
        if base:
            entries.append(("baseline: blame most recent deploy", base))
        for key in sorted(groups):
            comparison, arm, model = key.split("|")
            agg = groups[key].get(delivery)
            if agg:
                entries.append((f"{comparison}: {arm} / {model}", agg))
        if entries:
            title = {"environment": "environment faults (no guilty commit) - the real score",
                     "data": "data faults (guilty knowledge-base version, no commit)",
                     "push": "push faults (guilty commit; the deploy record nearly gives it away)",
                     "all": "all faults together (for reference only - mixes easy and hard cases)"}[delivery]
            out.append(table(title, entries, keys, headers))

    rr = results.get("retrieval", [])
    push = [r for r in rr if r["guilty"]]
    if push:
        out += ["#### Commit retrieval (push faults)", "",
                "| incident | time-filtered candidates | guilty in time filter | guilty in top-5 after rerank | rank |",
                "|---|---|---|---|---|"]
        for r in push:
            out.append(f"| {r['incident']} | {r['time_filter_size']} | {r['in_time_filter']} | {r['in_top5']} | "
                       f"{r['rank'] or '-'} |")
        out.append("")

    hit = results.get("baseline_deploy_hit", {})
    if hit.get("push") is not None:
        out += [f"Guilty commit inside the most recent deploy (deploy-level baseline hit rate, push faults): "
                f"{hit['push']:.2f}", ""]

    live = results.get("live_timings", [])
    if live:
        out += ["#### Live runs: time unnoticed and time to report", "",
                "| incident | delivery | first alert | expected alert? | break -> alert (s) | alert -> report (s) |",
                "|---|---|---|---|---|---|"]
        for r in live:
            out.append(f"| {r['incident']} | {r['delivery']} | {r['first_alert'] or '-'} | {r['expected_alert']} | "
                       f"{r['unnoticed_s'] if r['unnoticed_s'] is not None else '-'} | "
                       f"{r['doctor_s'] if r['doctor_s'] is not None else '-'} |")
        out.append("")
    return "\n".join(out)
