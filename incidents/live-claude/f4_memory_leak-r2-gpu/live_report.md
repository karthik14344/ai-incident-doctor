# Incident inc_9d36531d7e

**Alert:** MemoryClimbing - resident memory of retrieval is growing by 233.4kiB/s
**Started:** 2026-11-22T13:16:11.176Z  
**Running commit:** 8645aa3  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

Retrieval's resident memory is climbing steadily, from about 146 MB to 300 MB (about 233 KiB/s). The cause is commit 8645aa3, deployed to retrieval at 13:03:24Z just before the incident window. It added a module-level `_RECENT` dict with no size limit or eviction, and each distinct question stores the full response plus a list copy of its query embedding. Higher traffic makes the leak grow faster but did not cause it.

**Incident class:** `code_defect`

**Demand versus capacity:** traffic rose, deploy before onset: True, verdict: capacity_fell. Demand did rise: traffic went from a 1.19 rps mean to about 6.6 rps, and retrieval in_flight peaked at only 2. But the system is serving that demand without strain. /retrieve p50 is unchanged (27 ms), p95 is about 66 ms against 57 ms, embed p95 is flat, and there are no errors, timeouts, restarts or OOM kills. Gateway, llm and ingestion memory stayed flat under the same higher traffic. Only retrieval memory grows, and it grows steadily with no plateau. That is a leak, not saturation. The growth starts right after deploy 8645aa3 to retrieval only. Its diff adds a cache that grows forever and stores each response plus an embedding list. 233 KiB/s divided by about 6.6 rps is roughly 35 KiB per request, which fits one cached response with chunks plus a 768-float Python list. Traffic sets the leak rate; the code change is the cause.

## Evidence

- alert 2026-11-22T13:16:11.176Z **MemoryClimbing** retrieval: resident memory of retrieval is growing by 233.4kiB/s
- metric `traffic_rps{all}` baseline 1.1895 -> 7.3455 (x6.2)
- metric `requests_rps{service=gateway}` baseline 1.2529 -> 7.4 (x5.9)
- metric `requests_rps{service=retrieval}` baseline 1.2644 -> 7.3273 (x5.8)
- metric `in_flight{service=gateway}` baseline 0.8333 -> 3.0 (x3.6)
- metric `in_flight{service=retrieval}` baseline 0.0667 -> 2.0 (x30.0)
- metric `process_memory_mb{service=retrieval}` baseline 100.5312 -> 299.7578 (x3.0)
- metric `container_memory_ratio{service=retrieval}` baseline 0.141 -> 0.5354 (x3.8)

Deploys in the lookback window: 20; candidate commits (time filter only): 31

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.88 | retrieval | 8645aa3 | Commit 8645aa3 added a module-level dict `_RECENT` to /retrieve with no size limit or eviction. Each unique (collection, top_k, model, question) key keeps the whole response (raw_chunks, assembled_context) plus `list(query_emb)`. Nothing is ever removed, so memory grows linearly with the number of distinct requests. |
| 2 | 0.10 | retrieval | none | The roughly 6x request volume only speeds up the leak. Without the cache, per-request allocations would be freed and memory would stay flat under steady load. |

Evidence for #1:
- diff line: `_RECENT: Dict[str, Dict[str, Any]] = {}` has no size limit or eviction
- diff line: `_RECENT[key] = {**response, "query_embedding": list(query_emb)}` stores the full response and the embedding as a Python list on every cache miss
- deploy 8645aa3 (services=['retrieval']) went out at 13:03:24Z, right before the 13:06 incident window
- retrieval process_memory_mb rose steadily from 145.85 to 299.76 and container_memory_ratio from 0.23 to 0.54
- only retrieval memory rose; gateway, llm and ingestion memory stayed flat under the same higher traffic
- 233 KiB/s at about 6.6 rps is roughly 35 KiB per request, consistent with one cached response plus a 768-dim float list per unique question

Evidence for #2:
- traffic_rps rose from a 1.19 mean to a 7.35 max
- latency and error metrics show no saturation, and retrieval in_flight peaks at only 2

## Proposed fix

**Kind:** code_diff

These edits remove the unbounded `_RECENT` cache added in 8645aa3, so /retrieve stops holding a reference to every response and embedding. The cache saved little: embed p95 is only about 48 ms. It would also keep serving cached context after documents are re-ingested. If caching is wanted later, reintroduce it as an LRU with a size cap, a TTL and a lock, and do not store the embedding list. After the fix is deployed, retrieval needs a restart to release the memory it already holds. An operator should do that restart; it should not be applied automatically.

```diff
--- a/patient/retrieval_service/app/main.py
+++ b/patient/retrieval_service/app/main.py
@@ -64,8 +64,6 @@
     }
 
 
-# Recent retrievals, so a repeated question skips the embedding round-trip.
-_RECENT: Dict[str, Dict[str, Any]] = {}
 
 
 @app.post("/retrieve")
@@ -73,9 +71,6 @@
     if not req.question.strip():
         raise HTTPException(status_code=400, detail="Question cannot be empty")
 
-    key = f"{req.collection_name}:{req.top_k}:{req.embedding_model}:{req.question.strip().lower()}"
-    if key in _RECENT:
-        return _RECENT[key]
 
     # 1. Embed query
     query_emb = telemetry.instrumented_embedding("retrieval", req.question, req.embedding_model, req.ollama_base_url)
@@ -103,7 +98,6 @@
         "assembled_context": assembled["assembled_context"],
         "raw_chunks": chunks
     }
-    _RECENT[key] = {**response, "query_embedding": list(query_emb)}
     return response
 
 @app.get("/health")
```

## Verification

**Result:** verified
  
Test suite on the patched copy: 171 passed, 4 warnings in 4.44s

Nothing was applied to the running system.

## Cost

2 calls, 23053 prompt + 5445 completion tokens, $0.201112; reasoning 50.35s, total 61.55s
