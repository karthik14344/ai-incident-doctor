"""One table for a fault campaign: what the monitoring, the doctor and the agent team did.

    python -m faults.campaign_report gpu          # runs labelled *-gpu
    python -m faults.campaign_report gpu --out runtime/campaign-gpu.md

Reads runtime/fault-runs/<fault>-<round>-<suffix>/ (written by faults.run_fault):
ground_truth.json, timeline.json, live_report.json and agents.json. The doctor is
scored with the same function as the evaluation (doctor/eval/scoring.py), so the
columns mean what they mean in RESULTS.md.
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from faults.common import REPO, RUNS_DIR

sys.path.insert(0, REPO)
from doctor.eval.scoring import score  # noqa: E402


def load(path: str) -> Optional[Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def yes(v: Any) -> str:
    return "yes" if v else ("no" if v is not None else "-")


def row(run_dir: str) -> Dict[str, Any]:
    truth = load(os.path.join(run_dir, "ground_truth.json")) or {}
    tl = load(os.path.join(run_dir, "timeline.json")) or {}
    live = load(os.path.join(run_dir, "live_report.json")) or {}
    team = load(os.path.join(run_dir, "agents.json")) or live.get("agents") or {}
    report = live.get("report") or {}
    s = score(report.get("diagnosis"), report, truth) if report else {}
    tests = team.get("tests") or {}
    return {
        "run": os.path.basename(run_dir),
        "class": truth.get("incident_class"),
        "alert": (tl.get("first_alert") or {}).get("alertname") or ("missed -> ticket" if tl.get("monitoring_missed")
                                                                     else "-"),
        "unnoticed_s": tl.get("unnoticed_s"),
        "doctor_s": tl.get("doctor_s"),
        "doctor_class": (report.get("diagnosis") or {}).get("incident_class"),
        "class_ok": s.get("class_correct"),
        "cause_at_1": s.get("acc_at_1"),
        "cause_at_3": s.get("acc_at_3"),
        "fix_verified": s.get("fix_verified"),
        "team": team.get("status") or "-",
        "team_attempts": team.get("attempts"),
        "team_tests": f"{tests.get('total', 0) - (tests.get('failed') or 0)}/{tests.get('total')}" if tests else "-",
        "team_cost": team.get("cost_usd"),
        "doctor_cost": s.get("cost_usd"),
        "error": tl.get("observe_error"),
    }


def table(rows: List[Dict[str, Any]]) -> str:
    head = ("| Run | True class | Alert | Unnoticed s | Doctor s | Doctor class | Class ok | Cause @1 | Cause @3 "
            "| Doctor fix verified | Agent team | Fixer tries | Team tests | Cost $ (doctor+team) |")
    out = [head, "|" + "|".join(["---"] * 14) + "|"]
    for r in rows:
        cost = sum(c for c in (r["doctor_cost"], r["team_cost"]) if isinstance(c, (int, float)))
        out.append(f"| {r['run']} | {r['class']} | {r['alert']} | {r['unnoticed_s'] or '-'} | {r['doctor_s'] or '-'} "
                   f"| {r['doctor_class'] or '-'} | {yes(r['class_ok'])} | {yes(r['cause_at_1'])} "
                   f"| {yes(r['cause_at_3'])} | {yes(r['fix_verified'])} | {r['team']} "
                   f"| {r['team_attempts'] if r['team_attempts'] is not None else '-'} | {r['team_tests']} "
                   f"| {cost:.3f} |")
    n = len(rows) or 1
    pct = lambda k: f"{100 * sum(1 for r in rows if r[k]) / n:.0f}%"  # noqa: E731
    team_ok = sum(1 for r in rows if r["team"] in ("awaiting_approval", "done"))
    out += ["", f"**{len(rows)} runs.** Doctor: class correct {pct('class_ok')}, cause @1 {pct('cause_at_1')}, "
                f"cause @3 {pct('cause_at_3')}, fix verified {pct('fix_verified')}. "
                f"Agent team: patch passed the tests in {team_ok}/{len(rows)} "
                f"(escalated {sum(1 for r in rows if r['team'] == 'escalated')})."]
    errors = [r for r in rows if r["error"]]
    if errors:
        out += ["", "Runs with an observation error: " + "; ".join(f"{r['run']}: {r['error']}" for r in errors)]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("suffix", help="the --suffix the campaign ran with")
    ap.add_argument("--out", help="also write the table to this file")
    args = ap.parse_args()
    dirs = sorted(os.path.join(RUNS_DIR, d) for d in os.listdir(RUNS_DIR) if d.endswith(f"-{args.suffix}")) \
        if os.path.isdir(RUNS_DIR) else []
    text = table([row(d) for d in dirs if os.path.exists(os.path.join(d, "ground_truth.json"))])
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
