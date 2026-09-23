"""Steady "normal" traffic for the whole experiment campaign.

Every incident is judged against a baseline window before it, so the app needs
ordinary traffic all the time, not only while a fault is active: a light chat
stream plus retrieval searches, in consecutive 10-minute loadgen runs whose
summaries are appended to runtime/background_traffic.jsonl.

    python -m faults.background_traffic --hours 10
"""

import argparse
import json
import os
import threading
import time

from faults.common import REPO, Load, iso, log

CHAT = {"mode": "chat", "rate": 0.2, "concurrency": 4}
SEARCH = {"mode": "search", "rate": 0.4, "concurrency": 4}
SLICE_S = 600


def loop(profile, until: float, out: str) -> None:
    while time.time() < until:
        started = iso()
        load = Load(**profile, duration=min(SLICE_S, max(30, until - time.time()))).start()
        summary = load.join()
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"started": started, "finished": iso(), **profile, "summary": summary}) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=10)
    args = ap.parse_args()
    until = time.time() + args.hours * 3600
    out = os.path.join(REPO, "runtime", "background_traffic.jsonl")
    log(f"background traffic until {iso(until)}: chat {CHAT}, search {SEARCH}")
    threads = [threading.Thread(target=loop, args=(p, until, out), daemon=True) for p in (CHAT, SEARCH)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
