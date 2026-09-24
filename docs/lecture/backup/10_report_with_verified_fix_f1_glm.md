<!-- Backup: a real doctor report WITH a code fix that was tested on a throwaway copy.
Source: doctor/eval/results/glm/runs.jsonl, incident f1_embed_timeout-r2, repeat 0, arm logs_commits_incidents,
model glm-4.5-flash (the GLM evaluation run of 2026-09-24). Rendered with doctor/app/report.py; colour codes removed.
Ground truth: guilty commit 71b19e9 'Cap embedding calls at 10 s so a stuck call frees its thread'. -->

# Incident inc_cb34590ec2

**Alert:** EmbeddingFallbackActive - embedding fallback counter on retrieval rose by 1 in 2 minutes
**Started:** 2026-09-23T18:20:00.625Z  
**Running commit:** 3b6f031  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** glm:glm-4.5-flash

## What broke

Embedding timeout was reduced from 45s to 10s, causing Ollama embedding calls to timeout and fall back to hash-based embeddings when Ollama is slow to respond.

**Incident class:** `code_defect`

**Demand versus capacity:** traffic flat, deploy before onset: True, verdict: capacity_fell. Traffic remained flat during the incident, but a deploy (commit 71b19e9350050b299f8f218d81577ea7314cd58e) reduced the embedding timeout from 45s to 10s, causing the system to fall back to hash-based embeddings when Ollama was slow to respond.

## Evidence

- alert 2026-09-23T18:20:00.625Z **EmbeddingFallbackActive** retrieval: embedding fallback counter on retrieval rose by 1 in 2 minutes
- alert 2026-09-23T18:20:40.51Z **HighLatencyP95** gateway: p95 latency of gateway /api/retrieval/search is 11.8s
- alert 2026-09-23T18:20:45.51Z **HighLatencyP95** retrieval: p95 latency of retrieval /retrieve is 12.1s
- log `TEXT:4511c6932039` x15 in retrieval:  [Embedder] Ollama embedding call failed (timed out). Using robust fallback vectorizer.
- log `WARNING:a4dace19f999` x2 in gateway:  request
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline None -> 0.0915 (appeared (no baseline))
- metric `latency_p95_s{endpoint=/api/retrieval/search,service=gateway}` baseline 0.0756 -> 12.35 (x163.4)
- metric `latency_p95_s{endpoint=/retrieve,service=retrieval}` baseline 0.061 -> 12.4706 (x204.4)
- metric `latency_p50_s{endpoint=/api/retrieval/search,service=gateway}` baseline 0.0324 -> 0.2167 (x6.7)
- metric `latency_p50_s{endpoint=/retrieve,service=retrieval}` baseline 0.0262 -> 7.25 (x276.7)
- metric `in_flight{service=retrieval}` baseline 0.0645 -> 7.0 (x108.5)
- metric `service_up{__name__=up}` baseline 1.0 -> 0.0 (went down)
- metric `embedding_fallbacks_per_min{service=retrieval}` baseline 0.0 -> 15.1458 (from ~0)

Deploys in the lookback window: 19; candidate commits (time filter only): 32

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.90 | retrieval | 71b19e9 | Reduced embedding timeout causes fallback to hash-based embeddings when Ollama is slow |
| 2 | 0.60 | ollama | none | Ollama service is overloaded or experiencing high latency |
| 3 | 0.50 | retrieval | none | Retrieval service is experiencing high latency |

Evidence for #1:
- Log signature: '[Embedder] Ollama embedding call failed (timed out). Using robust fallback vectorizer.'
- Metric: embedding_fallbacks_per_min rose from 0 to 15.1458
- Metric: ollama_p95_s for embed operation increased from 0.0534 to 12.4706

Evidence for #2:
- Metric: ollama_p95_s for embed operation increased from 0.0534 to 12.4706
- Metric: ollama_failures_per_min for embed operation with reason=fallback appeared at 17.3282

Evidence for #3:
- Metric: latency_p95_s for /retrieve endpoint increased from 0.061 to 12.4706
- Metric: in_flight for retrieval service increased from 0.0645 to 7.0

## Proposed fix

**Kind:** code_diff

The timeout was reduced from 45s to 10s in commit 71b19e9350050b299f8f218d81577ea7314cd58e, which caused embedding calls to timeout when Ollama was slow to respond (e.g., during cold load). Restoring the timeout to 45s will allow the system to wait for Ollama to respond properly instead of falling back to hash-based embeddings that produce irrelevant results.

```diff
--- a/patient/ingestion_service/app/embedder.py
+++ b/patient/ingestion_service/app/embedder.py
@@ -14,9 +14,9 @@
 # counter around a call and flag any result it moved.
 _FALLBACK_COUNT = 0
 
-# Embedding calls normally return in well under a second; give up after 10 s
-# so a stuck Ollama cannot hold a request thread for most of a minute.
-EMBED_TIMEOUT_S = 10.0
+# Cold nomic-embed-text can take ~15 s to load on first use. The old 10 s
+# timeout turned that first query into silent garbage instead of a slow answer.
+EMBED_TIMEOUT_S = 45.0
 
 
 def embedding_fallback_count() -> int:
```

## Verification

**Result:** verified
  
Test suite on the patched copy: 170 passed, 5 warnings in 12.34s
  
Acceptance test: 1 passed in 0.06s

Nothing was applied to the running system.

## Cost

1 calls, 7496 prompt + 845 completion tokens, $0.006357; reasoning 27.02s, total 41.44s
