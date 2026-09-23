"""Week 5 - rate-limit demonstration: a concurrent flood on one session.

The AFTER matrix's sequential burst never tripped the limiter - with ~20 s
CPU generations, six sequential requests cannot land inside a 60-second
window, which is itself the finding: sequential traffic self-throttles, so
the flood this guardrail exists for is a *concurrent* one. This script fires
8 simultaneous chat requests on one session and records what happens.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GATEWAY = "http://localhost:8000"
SESSION = "session_ratelimit_flood"
BURST = 8


def one(i: int) -> dict:
    started = time.perf_counter()
    tokens, verdicts = [], []
    try:
        with httpx.Client(timeout=300.0) as client:
            with client.stream("POST", f"{GATEWAY}/api/chat",
                               json={"question": "hello there",
                                     "collection_name": "eval_kb",
                                     "session_id": SESSION},
                               timeout=300.0) as resp:
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except Exception:
                        continue
                    if event.get("type") == "guardrails":
                        verdicts = event.get("verdicts", [])
                    elif "token" in event:
                        tokens.append(event["token"])
                    elif event.get("done"):
                        break
    except Exception as e:
        return {"n": i, "error": str(e)}
    answer = "".join(tokens).strip()
    blocked = next((v for v in verdicts if v.get("allowed") is False), None)
    return {"n": i, "blocked_by": blocked and blocked.get("guardrail"),
            "reason": blocked.get("reason") if blocked else None,
            "answer_chars": len(answer), "elapsed_s": round(time.perf_counter() - started, 1)}


def main() -> int:
    settings = httpx.get(f"{GATEWAY}/api/settings", timeout=10).json()
    assert settings["llm_model"] == "mistral"
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=BURST) as pool:
        results = list(pool.map(one, range(1, BURST + 1)))
    blocked = [r for r in results if r.get("blocked_by")]
    print(f"[flood] {BURST} concurrent requests, one session: "
          f"{BURST - len(blocked)} generated, {len(blocked)} rate-limited "
          f"({round(time.perf_counter() - started, 1)} s total)")
    for r in results:
        print("  ", r)
    out = os.path.join("data", "guardrails", "rate_burst_after.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"burst": BURST, "session": SESSION,
                   "llm_model": settings["llm_model"],
                   "generated": BURST - len(blocked),
                   "rate_limited": len(blocked), "results": results},
                  fh, indent=2)
    print(f"[+] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
