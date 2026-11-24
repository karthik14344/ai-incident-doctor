# Incident inc_13fe9e525e

**Alert:** MemoryClimbing - resident memory of retrieval is growing by 223kiB/s
**Started:** 2026-11-22T10:27:01.176Z  
**Running commit:** 6cd5503  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

Commit 6cd5503, deployed to retrieval at 10:14:15Z, added a module-level `_RECENT` dict that caches every distinct retrieval response with no size limit, including a full copy of the query embedding. Retrieval RSS has grown steadily since then, from about 103 MB at baseline to 317 MB (container memory ratio 0.57). The traffic surge (about 6x) speeds the growth up but does not cause it.

**Incident class:** `code_defect`

**Demand versus capacity:** traffic rose, deploy before onset: True, verdict: capacity_fell. Traffic did rise about 6x (traffic_rps 1.17 -> 7.4, retrieval requests 1.24 -> 7.49 rps), but the system is serving that load well. Retrieval p50 is flat at 27 ms, retrieval p95 dropped from 0.24 s to 0.07 s and gateway chat latency did not rise. There are no errors, restarts or OOMs. The only anomaly is retrieval memory climbing steadily at about 223 KiB/s. It starts right after the retrieval-only deploy 6cd5503 (10:14:15Z, 3 minutes before the incident window). That diff adds an unbounded in-process cache that stores the response, the raw chunks and the query embedding for every distinct question. Load alone would not make a stateless service's memory grow monotonically, and gateway and llm memory stay flat under the same surge. This is a change-induced leak that higher traffic amplifies, not pure capacity.

## Evidence

- alert 2026-11-22T10:27:01.176Z **MemoryClimbing** retrieval: resident memory of retrieval is growing by 223kiB/s
- metric `traffic_rps{all}` baseline 1.1721 -> 7.4 (x6.3)
- metric `requests_rps{service=gateway}` baseline 1.2385 -> 7.4545 (x6.0)
- metric `requests_rps{service=retrieval}` baseline 1.2408 -> 7.4909 (x6.0)
- metric `chat_outcomes_rps{outcome=refused_output}` baseline 0.0015 -> 0.0182 (x12.1)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 2.9018 -> 4.4 (x1.5)
- metric `in_flight{service=gateway}` baseline 0.5 -> 4.0 (x8.0)
- metric `in_flight{service=llm}` baseline 0.4 -> 2.0 (x5.0)
- metric `in_flight{service=retrieval}` baseline 0.0333 -> 4.0 (x120.1)

Deploys in the lookback window: 12; candidate commits (time filter only): 23

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.85 | retrieval | 6cd5503 | An unbounded per-process response cache (`_RECENT`) in retrieval /retrieve grows with every distinct question and is never evicted. Each entry holds raw_chunks, the assembled context and a Python list copy of the embedding (about 768 boxed floats). |
| 2 | 0.12 | retrieval | none | The traffic surge (about 6x rps, many distinct questions) is legitimate demand. It is not the defect itself, but it fills the unbounded cache faster. |

Evidence for #1:
- diff 6cd5503: `_RECENT: Dict[str, Dict[str, Any]] = {}` at module level with no max size or eviction
- diff 6cd5503: `_RECENT[key] = {**response, "query_embedding": list(query_emb)}` stores a full embedding plus chunks per unique question
- process_memory_mb{service=retrieval}: baseline mean 102.7 -> incident first 171.3, last 317.1, monotonically rising; MemoryClimbing alert at 223 kiB/s
- container_memory_ratio{service=retrieval} 0.145 -> 0.571, while gateway/llm/ingestion memory stays flat under the same traffic
- deploy 6cd5503 (services=['retrieval']) at 10:14:15Z, immediately before the 10:17 incident window
- retrieval p95 fell 0.24 s -> 0.067 s and ollama embed p95 fell to 0.048 s, consistent with cache hits skipping the embedding round-trip, so the new code path is active

Evidence for #2:
- traffic_rps 1.17 -> 7.4 (x6.3); in_flight{retrieval} max 4
- No errors, timeouts or latency degradation, so the service has the capacity to handle the load

## Proposed fix

**Kind:** code_diff

This bounds the cache to 256 entries, evicting the oldest first (dicts preserve insertion order). It also stops storing the redundant embedding list, so cached responses match fresh ones and use far less memory. Reverting 6cd5503 outright is a reasonable alternative, because the cache key ignores knowledge-base changes and could serve stale context after ingestion. Once the fix is deployed through normal review, retrieval memory should plateau. A manual restart of retrieval will reclaim the memory already leaked.

```diff
--- a/patient/retrieval_service/app/main.py
+++ b/patient/retrieval_service/app/main.py
@@ -66,6 +66,7 @@
 
 # Recent retrievals, so a repeated question skips the embedding round-trip.
 _RECENT: Dict[str, Dict[str, Any]] = {}
+_RECENT_MAX = 256
 
 
 @app.post("/retrieve")
@@ -103,7 +104,9 @@
         "assembled_context": assembled["assembled_context"],
         "raw_chunks": chunks
     }
-    _RECENT[key] = {**response, "query_embedding": list(query_emb)}
+    if len(_RECENT) >= _RECENT_MAX:
+        _RECENT.pop(next(iter(_RECENT)), None)
+    _RECENT[key] = response
     return response
 
 @app.get("/health")
```

## Verification

**Result:** verified
  
Test suite on the patched copy: 171 passed, 4 warnings in 4.59s

Nothing was applied to the running system.

## Cost

2 calls, 23204 prompt + 4703 completion tokens, $0.186876; reasoning 42.46s, total 53.83s
