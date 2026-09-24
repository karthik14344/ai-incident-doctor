# Incident inc_cb34590ec2

**Alert:** EmbeddingFallbackActive - embedding fallback counter on retrieval rose by 1 in 2 minutes
**Started:** 2026-09-23T18:20:00.625Z  
**Running commit:** 3b6f031  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

Embedding fallback counter on retrieval rose by 1 in 2 minutes

**Incident class:** `code_defect`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: capacity_fell. Traffic RPS remained flat while latency p95 rose x163.4

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
| 1 | 0.80 | retrieval | 71b19e9 | Cap embedding calls at 10 s so a stuck call frees its thread |

Evidence for #1:
- log signature [Embedder] Ollama embedding call failed (timed out). Using robust fallback vectorizer.
- metric embedding_fallbacks_per_min rose from ~0 to 15.1458

## Proposed fix

**Kind:** action

Increase cap on embedding calls to prevent stuck calls

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 7400 prompt + 548 completion tokens, $0.0; reasoning 27.31s, total 55.72s
