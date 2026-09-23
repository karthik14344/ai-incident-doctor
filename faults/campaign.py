"""Run a list of faults back to back, unattended, with cool-downs between them.

    python -m faults.campaign            # the default plan below
    python -m faults.campaign --only f3_retrieval_down f2_capacity

A cool-down follows every run so the next incident's 30-minute baseline window
is not dominated by the previous fault, and so an alert of the next run is not
grouped with the previous incident.
"""

import argparse
import json
import os
import time
import traceback

from faults.common import REPO, iso, log
from faults.run_fault import run

PLAN = [
    ("f3_retrieval_down", "guilty_last", "r1"),
    ("f2_capacity", "guilty_last", "r1"),
    ("f1_embed_timeout", "guilty_last", "r1"),
    ("f5_typo", "guilty_earlier", "r1"),
    ("f3b_retrieval_bad_address", "guilty_last", "r1"),
    ("f6_tight_timeout", "guilty_last", "r1"),
    ("f7_kb_missing_docs", "guilty_last", "r1"),
    ("f4_memory_leak", "guilty_last", "r1"),
    ("f2_capacity", "guilty_last", "r2"),
    ("f1_embed_timeout", "guilty_earlier", "r2"),
    ("f5_typo", "guilty_last", "r2"),
    ("f3_retrieval_down", "guilty_last", "r2"),
    ("f6_tight_timeout", "guilty_earlier", "r2"),
    ("f7_kb_missing_docs", "guilty_last", "r2"),
    ("f4_memory_leak", "guilty_earlier", "r2"),
    ("f3b_retrieval_bad_address", "guilty_last", "r2"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--cooldown", type=int, default=720)
    ap.add_argument("--round", default=None, help="only runs with this label (r1/r2)")
    ap.add_argument("--background", action="store_true",
                    help="also run the normal background traffic in this process (one process = less memory)")
    args = ap.parse_args()
    if args.background:
        import threading

        from faults.background_traffic import CHAT, SEARCH, loop
        until = time.time() + 24 * 3600
        out = os.path.join(REPO, "runtime", "background_traffic.jsonl")
        for profile in (CHAT, SEARCH):
            threading.Thread(target=loop, args=(profile, until, out), daemon=True).start()
        log("background traffic running inside the campaign process; settling 600 s first")
        time.sleep(600)
    plan = [p for p in PLAN if (not args.only or p[0] in args.only) and (not args.round or p[2] == args.round)]
    record = os.path.join(REPO, "runtime", "campaign.jsonl")
    for i, (fault, variant, label) in enumerate(plan):
        started = iso()
        try:
            run_dir = run(fault, variant, label)
            status = "done"
        except Exception as exc:
            run_dir, status = None, f"error: {type(exc).__name__}: {exc}"
            log(traceback.format_exc())
        with open(record, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"fault": fault, "variant": variant, "label": label, "started": started,
                                 "finished": iso(), "status": status, "run_dir": run_dir}) + "\n")
        if i < len(plan) - 1:
            log(f"cool-down {args.cooldown}s")
            time.sleep(args.cooldown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
