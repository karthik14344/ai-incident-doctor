"""Side-by-side table of two live campaigns: the doctor on one model against another.

    python -m faults.compare_live                       # Llama 3.2 (laptop) vs Claude (GCP)
    python -m faults.compare_live --out doctor/eval/results/live/claude-vs-llama-live.md

The Claude runs are kept in incidents/live-claude/, apart from incidents/recorded/,
because the replay evaluation (doctor.eval.run_eval) reads every folder in recorded/.

Each run is scored with the same function as the evaluation and the campaign report
(faults/campaign_report.py -> doctor/eval/scoring.py), so the columns mean what they
mean in RESULTS.md. Runs are matched by fault and round (f5_typo-r1 <-> f5_typo-r1-gpu).
"""

from __future__ import annotations

import argparse
import glob
import os
import statistics
import sys
from typing import Any, Dict, List

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from doctor.eval.scoring import score  # noqa: E402
from faults.campaign_report import load, row  # noqa: E402

CAMPAIGNS = [
    ("Llama 3.2 (laptop, Sept)", os.path.join(REPO, "incidents", "recorded"), ""),
    ("Claude Opus 5.5 (GCP VM, Nov)", os.path.join(REPO, "incidents", "live-claude"), "-gpu"),
]


def runs(root: str, suffix: str) -> Dict[str, Dict[str, Any]]:
    out = {}
    for d in sorted(glob.glob(os.path.join(root, f"f*-r[12]{suffix}"))):
        report = (load(os.path.join(d, "live_report.json")) or {}).get("report") or {}
        if not report:
            continue
        r = row(d)
        truth = load(os.path.join(d, "ground_truth.json")) or {}
        r["delivery"] = truth.get("delivery")
        r["model"] = f"{report.get('provider')}:{report.get('model')}"
        r["evidence_tokens"] = report.get("prompt_tokens_estimate")
        # the evaluation's "false attribution": a commit blamed where no commit is guilty
        r["blamed_innocent"] = bool(score(report.get("diagnosis"), report, truth).get("false_attribution"))
        out[os.path.basename(d)[: len(os.path.basename(d)) - len(suffix)] if suffix else os.path.basename(d)] = r
    return out


def frac(rows: List[Dict[str, Any]], key: str) -> str:
    if not rows:
        return "-"
    return f"{sum(1 for r in rows if r[key])}/{len(rows)} ({100 * sum(1 for r in rows if r[key]) / len(rows):.0f}%)"


def median(rows, key) -> str:
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return f"{statistics.median(vals):.0f}" if vals else "-"


def summary(name: str, rs: Dict[str, Dict[str, Any]]) -> List[str]:
    rows = list(rs.values())
    push = [r for r in rows if r["delivery"] == "push"]
    no_commit = [r for r in rows if r["delivery"] != "push"]
    cost = sum(r["doctor_cost"] or 0 for r in rows)
    return [f"| {name} | {len(rows)} | {frac(rows, 'class_ok')} | {frac(rows, 'cause_at_1')} | {frac(rows, 'cause_at_3')} "
            f"| {frac(no_commit, 'blamed_innocent')} | {frac(push, 'fix_verified')} | {median(rows, 'doctor_s')} "
            f"| {median(rows, 'evidence_tokens')} | {cost:.2f} |"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    data = [(name, runs(root, sfx)) for name, root, sfx in CAMPAIGNS]

    out = ["## Live runs: the doctor on two models", "",
           "| Model | Runs | Right class | Right cause @1 | Right cause @3 | Blamed a commit when none was guilty "
           "| Fix verified (push faults) | Median s alert->report | Median evidence tokens | Doctor cost $ |",
           "|" + "|".join(["---"] * 10) + "|"]
    for name, rs in data:
        out += summary(name, rs)

    out += ["", "### Right cause @1 by fault type", "", "| Model | Environment | Data | Push |", "|---|---|---|---|"]
    for name, rs in data:
        by = lambda d: frac([r for r in rs.values() if r["delivery"] == d], "cause_at_1")  # noqa: E731
        out.append(f"| {name} | {by('environment')} | {by('data')} | {by('push')} |")

    yes = lambda v: "yes" if v else ("no" if v is not None else "-")  # noqa: E731
    out += ["", "### Run by run", "", "| Fault run | Type | " + " | ".join(f"{n.split(' (')[0]} class / cause@1"
                                                                       for n, _ in data) + " |",
            "|" + "|".join(["---"] * (2 + len(data))) + "|"]
    names = sorted(set().union(*(rs.keys() for _, rs in data)))
    for n in names:
        cells, kind = [], "-"
        for _, rs in data:
            r = rs.get(n)
            kind = r["delivery"] if r else kind
            cells.append(f"{r['doctor_class'] or '-'} / {yes(r['cause_at_1'])}" if r else "not run")
        out.append(f"| {n} | {kind} | " + " | ".join(cells) + " |")

    text = "\n".join(out)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
