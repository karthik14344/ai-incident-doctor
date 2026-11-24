# Incident inc_f5f7edf5a1

**Alert:** UserReport - It no longer answers questions about the library, scholarships or placements.
**Started:** 2026-11-24T15:16:50Z  
**Running commit:** b26c3a9  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

At 15:16:34Z the knowledge base was swapped from version 38ba55c908d1 to 405bbf0b9802. That shrank the 'default' collection from 10 documents / 21 chunks to 4 documents / 9 chunks, so library, scholarship and placement content can no longer be retrieved. Services, traffic and code are unchanged, so this is a data issue.

**Incident class:** `data_issue`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: neither. Demand did not rise. traffic_rps mean is 0.565 in the baseline and 0.602 in the incident, and the incident max of 0.87 is below the baseline max of 0.89. Capacity did not fall either: latencies are unchanged (gateway /api/chat p95 2.42s vs 2.28s; retrieval p95 0.052s vs 0.057s), there were no restarts or OOM kills, and service_up=1 throughout. The running commit b26c3a9 was deployed on 2026-11-22, and there is no deploy in the lookback window. The only change at the onset is the KB version load at 15:16:34Z, which cut the default collection's content.

## Evidence

- log `WARNING:a4dace19f999` x1 in gateway:  request
- log `ConnectError:bf91e0cfbf34` x1 in retrieval: ConnectError [Errno -3] Temporary failure in name resolution
- metric `traffic_rps{all}` baseline 0.5654 -> 0.8727 (x1.5)
- metric `requests_rps{service=llm}` baseline 0.2516 -> 0.4 (x1.6)
- metric `requests_rps{service=retrieval}` baseline 0.6504 -> 0.9818 (x1.5)
- metric `error_ratio_5xx{service=gateway}` baseline 0.001 -> 0.0294 (x29.4)
- metric `error_ratio_5xx{service=retrieval}` baseline 0.0021 -> 0.0303 (x14.4)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.1601 -> 0.3273 (x2.0)
- metric `latency_p95_s{endpoint=/retrieve,service=retrieval}` baseline 0.0523 -> 0.082 (x1.6)
- metric `in_flight{service=gateway}` baseline 0.0968 -> 2.0 (x20.7)

Deploys in the lookback window: 0; candidate commits (time filter only): 0

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.85 | knowledge_base | none | The knowledge base was reloaded to an older or partial version (405bbf0b9802). The 'default' collection dropped from 10 docs / 21 chunks to 4 docs / 9 chunks, removing the documents on library, scholarships and placements. Retrieval finds nothing relevant for those topics, so the assistant can no longer answer them. |
| 2 | 0.15 | chroma | none | A transient Chroma connectivity blip during the KB reload. The retrieval service got a DNS 'Temporary failure in name resolution' in get_or_create_collection at the same moment, which caused a few HTTP 500s from retrieval to the gateway. |

Evidence for #1:
- KB load at 2026-11-24T15:16:34Z: 38ba55c908d1 -> 405bbf0b9802, default collection {documents: 10, chunks: 21} -> {documents: 4, chunks: 9}
- The same partial version was loaded at 14:49:00Z and reverted at 15:04:32Z, so 38ba55c908d1 is the known-good full KB
- The user reports that specific topics fail (library, scholarships, placements), not a total outage, which fits missing documents
- No deploy since 2026-11-22; traffic, latency and service health are flat

Evidence for #2:
- ConnectError [Errno -3] Temporary failure in name resolution at vector_store.py:34, a single occurrence at 15:16:34Z (also seen in the baseline)
- downstream_failures_per_min{target=retrieval,reason=http_500} incident max 1.09 is below the baseline max 2.18, so the failure is not sustained
- chroma container_restarts=0 and oom_kills=0

## Proposed fix

**Kind:** action

The symptoms come from missing indexed content, not from code, configuration or capacity. Re-ingesting the known-good KB version brings back the missing topic documents. The single Chroma DNS error was transient and needs no change.

**Recommended action:** An operator should restore the full knowledge base by reloading KB version 38ba55c908d1 into the 'default' collection; the collection should then hold 10 documents / 21 chunks. Check the collection count, then run test queries on library, scholarships and placements. Also find out which process or person keeps loading 405bbf0b9802 (it happened at 14:49 and again at 15:16) and stop it, so the partial KB is not loaded again.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 18810 prompt + 3201 completion tokens, $0.13926; reasoning 25.91s, total 26.12s
