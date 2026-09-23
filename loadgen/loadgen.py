"""Load generator for the patient, grown out of run_rate_burst_demo.py.

run_rate_burst_demo.py fired a fixed burst of 8 concurrent chats at one session
to trip the rate limiter. Several faults only appear under sustained load, so
this generalises it: an open-loop arrival rate, a cap on concurrency, a
duration, and a choice of target - and it records client-side latency, status
and errors per request.

    python loadgen/loadgen.py --mode chat --rate 2 --concurrency 16 --duration 120
    python loadgen/loadgen.py --mode search --rate 20 --concurrency 20 --duration 300 --unique
    python loadgen/loadgen.py --mode retrieve --base-url http://127.0.0.1:18002 ...

Modes:
    chat      POST /api/chat on the gateway, streamed (SSE) to the last event
    search    POST /api/retrieval/search on the gateway (retrieval only, no LLM)
    retrieve  POST /retrieve on the retrieval service directly

Each chat request starts a new conversation (no session id), as a first
message from a new user does: the gateway creates the session. The
per-session rate limiter is a guardrail, not what a load test measures.
"""

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

QUESTIONS = [
    "What is the minimum attendance required to sit semester examinations?",
    "How many books can a student borrow from the central library?",
    "What are the hostel curfew timings?",
    "What happens if a student is caught using unfair means in an exam?",
    "What is the fine for returning a library book late?",
    "Who is eligible for the merit scholarship?",
    "What safety equipment is mandatory in the chemistry lab?",
    "What is the one student one offer rule in placements?",
    "How do I file a grievance with the university?",
    "When does the odd semester begin according to the academic calendar?",
    "Can attendance shortage be condoned for medical reasons?",
    "What are the library opening hours?",
    # Real users also type keywords rather than questions.
    "hostel curfew timings",
    "late fee for library books",
    "scholarship eligibility criteria",
]


def _env(name: str) -> Optional[str]:
    if os.environ.get(name):
        return os.environ[name]
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(path):
        for raw in open(path, encoding="utf-8"):
            if raw.strip().startswith(f"{name}="):
                return raw.split("=", 1)[1].strip() or None
    return None


def percentile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 3)


def summarise(results: List[Dict[str, Any]], wall_s: float) -> Dict[str, Any]:
    ok = [r for r in results if r["ok"]]
    lat = [r["latency_s"] for r in ok]
    errors: Dict[str, int] = {}
    for r in results:
        if not r["ok"]:
            errors[r["error"]] = errors.get(r["error"], 0) + 1
    outcomes: Dict[str, int] = {}
    for r in results:
        if r.get("outcome"):
            outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    return {
        "requests": len(results), "ok": len(ok), "errors": len(results) - len(ok),
        "error_rate": round((len(results) - len(ok)) / len(results), 4) if results else 0.0,
        "p50_s": percentile(lat, 0.50), "p95_s": percentile(lat, 0.95), "p99_s": percentile(lat, 0.99),
        "mean_s": round(statistics.fmean(lat), 3) if lat else None, "max_s": max(lat) if lat else None,
        "throughput_rps": round(len(ok) / wall_s, 3) if wall_s else 0.0,
        "error_kinds": errors, "outcomes": outcomes, "wall_s": round(wall_s, 1),
    }


class LoadGenerator:
    def __init__(self, base_url: str, mode: str = "chat", rate: float = 1.0, concurrency: int = 8,
                 duration: float = 60.0, timeout: float = 180.0, unique: bool = False,
                 collection: str = "default", seed: int = 1, questions: Optional[List[str]] = None):
        self.base_url = base_url.rstrip("/")
        self.mode, self.rate, self.concurrency = mode, rate, concurrency
        self.duration, self.timeout, self.unique = duration, timeout, unique
        self.collection = collection
        self.random = random.Random(seed)
        self.questions = questions or QUESTIONS
        self.results: List[Dict[str, Any]] = []

    def _question(self, n: int) -> str:
        q = self.questions[n % len(self.questions)]
        return f"{q} (ref {uuid.uuid4().hex[:8]})" if self.unique else q

    async def _one(self, client: httpx.AsyncClient, n: int, sem: asyncio.Semaphore) -> None:
        async with sem:
            question = self._question(n)
            started = time.perf_counter()
            rec: Dict[str, Any] = {"n": n, "t_start": time.time(), "ok": False, "status": None,
                                   "error": None, "outcome": None}
            try:
                if self.mode == "chat":
                    tokens, refused = 0, False
                    async with client.stream("POST", f"{self.base_url}/api/chat",
                                             json={"question": question, "collection_name": self.collection}) as resp:
                        rec["status"] = resp.status_code
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            try:
                                event = json.loads(line[6:])
                            except ValueError:
                                continue
                            if "token" in event:
                                tokens += 1
                                if "[LLM Stream error" in event["token"]:
                                    rec["error"] = "llm_stream_error"
                            if event.get("type") == "guardrails":
                                refused = any(v.get("allowed") is False for v in event.get("verdicts", []))
                            if event.get("done"):
                                break
                    rec["tokens"] = tokens
                    rec["outcome"] = "refused" if refused else "answered"
                    rec["ok"] = resp.status_code == 200 and rec["error"] is None
                    if resp.status_code != 200:
                        rec["error"] = f"http_{resp.status_code}"
                else:
                    path = "/api/retrieval/search" if self.mode == "search" else "/retrieve"
                    payload = {"question": question, "collection_name": self.collection}
                    resp = await client.post(f"{self.base_url}{path}", json=payload)
                    rec["status"] = resp.status_code
                    rec["ok"] = resp.status_code == 200
                    if resp.status_code == 200:
                        rec["results_count"] = resp.json().get("results_count")
                    else:
                        rec["error"] = f"http_{resp.status_code}"
            except Exception as exc:
                rec["error"] = type(exc).__name__
            rec["latency_s"] = round(time.perf_counter() - started, 3)
            self.results.append(rec)

    async def run(self) -> Dict[str, Any]:
        sem = asyncio.Semaphore(self.concurrency)
        limits = httpx.Limits(max_connections=self.concurrency + 4, max_keepalive_connections=self.concurrency)
        started = time.perf_counter()
        tasks = []
        async with httpx.AsyncClient(timeout=self.timeout, limits=limits, trust_env=False) as client:
            n = 0
            next_at = started
            while time.perf_counter() - started < self.duration:
                now = time.perf_counter()
                if now < next_at:
                    await asyncio.sleep(next_at - now)
                tasks.append(asyncio.create_task(self._one(client, n, sem)))
                n += 1
                # Poisson arrivals at the configured mean rate.
                next_at += self.random.expovariate(self.rate) if self.rate > 0 else self.duration
            await asyncio.gather(*tasks)
        wall = time.perf_counter() - started
        return {"config": {"base_url": self.base_url, "mode": self.mode, "rate": self.rate,
                           "concurrency": self.concurrency, "duration": self.duration, "unique": self.unique},
                "summary": summarise(self.results, wall)}


def run(**kwargs) -> Dict[str, Any]:
    gen = LoadGenerator(**kwargs)
    out = asyncio.run(gen.run())
    out["results"] = sorted(gen.results, key=lambda r: r["n"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=None, help="default: GATEWAY_URL from the environment/.env")
    ap.add_argument("--mode", choices=["chat", "search", "retrieve"], default="chat")
    ap.add_argument("--rate", type=float, default=1.0, help="mean arrivals per second")
    ap.add_argument("--concurrency", type=int, default=8, help="max requests in flight")
    ap.add_argument("--duration", type=float, default=60.0, help="seconds of arrivals")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--unique", action="store_true", help="make every question unique")
    ap.add_argument("--collection", default="default")
    ap.add_argument("--out", default=None, help="write full results as JSON here")
    args = ap.parse_args()
    base = args.base_url or _env("GATEWAY_URL")
    if not base:
        print("set --base-url or GATEWAY_URL", file=sys.stderr)
        return 2
    out = run(base_url=base, mode=args.mode, rate=args.rate, concurrency=args.concurrency,
              duration=args.duration, timeout=args.timeout, unique=args.unique, collection=args.collection)
    print(json.dumps({"config": out["config"], "summary": out["summary"]}, indent=2))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
