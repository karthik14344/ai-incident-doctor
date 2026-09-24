# Incident inc_9bf1ee6114

**Alert:** EmbeddingFallbackActive - embedding fallback counter on retrieval rose by 1 in 2 minutes
**Started:** 2026-09-23T11:58:25.625Z  
**Running commit:** 8f63699  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

Embedding fallback counter on retrieval rose by 1 in 2 minutes

**Incident class:** `data_issue`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: capacity_fell. Traffic up with no relevant deploy; latency_p95_s{endpoint=/api/retrieval/search,service=gateway} rose x16.7

## Evidence

- alert 2026-09-23T11:57:33.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- alert 2026-09-23T11:58:25.625Z **EmbeddingFallbackActive** retrieval: embedding fallback counter on retrieval rose by 1 in 2 minutes
- alert 2026-09-23T11:59:25.51Z **HighLatencyP95** retrieval: p95 latency of retrieval /retrieve is 10.7s
- alert 2026-09-23T11:59:25.51Z **HighLatencyP95** gateway: p95 latency of gateway /api/retrieval/search is 11.5s
- log `WARNING:a4dace19f999` x2 in gateway:  request
- log `TEXT:4511c6932039` x2 in retrieval:  [Embedder] Ollama embedding call failed (timed out). Using robust fallback vectorizer.
- log `ConnectError:5b2993ef741b` x1 in gateway: ConnectError [Errno -5] No address associated with hostname
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 4.6573 -> 28.75 (x6.2)
- metric `latency_p95_s{endpoint=/api/retrieval/search,service=gateway}` baseline 0.7121 -> 11.875 (x16.7)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 4.1626 -> 28.75 (x6.9)
- metric `latency_p95_s{endpoint=/retrieve,service=retrieval}` baseline 0.0738 -> 11.25 (x152.4)
- metric `latency_p50_s{endpoint=/api/chat,service=gateway}` baseline 2.546 -> 16.5 (x6.5)
- metric `latency_p50_s{endpoint=/api/retrieval/search,service=gateway}` baseline 0.0474 -> 2.0 (x42.2)
- metric `latency_p50_s{endpoint=/generate,service=llm}` baseline 2.0657 -> 16.5 (x8.0)
- metric `latency_p50_s{endpoint=/retrieve,service=retrieval}` baseline 0.0367 -> 1.25 (x34.1)

Deploys in the lookback window: 12; candidate commits (time filter only): 45

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.80 | retrieval | none | Embedding fallback counter on retrieval rose by 1 in 2 minutes |

Evidence for #1:
- log signature ConnectError:5b2993ef741b appeared at ...
- metric embedding_fallbacks_per_min{service=retrieval} rose from 0 to 2.1774

## Proposed fix

**Kind:** action

Restart the gateway service to resolve the issue.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 7042 prompt + 527 completion tokens, $0.0; reasoning 5.54s, total 17.68s
