# Incident inc_176cdacf34

**Alert:** UserReport - It no longer answers questions about the library, scholarships or placements.
**Started:** 2026-09-23T16:59:42Z  
**Running commit:** 1a06be7  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

The system no longer answers questions about the library, scholarships or placements. The traffic_rps has increased by 19.3% and in_flight has increased by 300%.

**Incident class:** `capacity`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: capacity_fell. The traffic_rps has increased by 19.3% and in_flight has increased by 300%, indicating a high demand. The deploy before onset is false because the traffic_rps has not increased significantly before the onset.

## Evidence

- log `ConnectError:5b2993ef741b` x3 in retrieval: ConnectError [Errno -5] No address associated with hostname
- log `WARNING:a4dace19f999` x3 in gateway:  request
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline 0.0149 -> 0.0727 (x4.9)
- metric `latency_p95_s{endpoint=/api/retrieval/search,service=gateway}` baseline 0.1031 -> 4.3667 (x42.4)
- metric `latency_p95_s{endpoint=/retrieve,service=retrieval}` baseline 0.0796 -> 4.1333 (x51.9)
- metric `in_flight{service=gateway}` baseline 0.7667 -> 3.0 (x3.9)
- metric `in_flight{service=retrieval}` baseline 0.0 -> 3.0 (from ~0)
- metric `ollama_p95_s{operation=embed}` baseline 0.0521 -> 0.087 (x1.7)

Deploys in the lookback window: 19; candidate commits (time filter only): 34

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.90 | retrieval | none | The vector store configuration was changed without properly handling the ingestion service. |

Evidence for #1:
- log signature ConnectError:5b2993ef741b appeared at ...
- metric latency_p95_s{endpoint=/api/retrieval/search,service=gateway} rose x42.4

## Proposed fix

**Kind:** config_change

The vector store configuration needs to be updated to properly handle the ingestion service.

## Verification

**Result:** unverified - needs human review
  
no applicable diff was produced

Nothing was applied to the running system.

## Cost

2 calls, 7288 prompt + 632 completion tokens, $0.0; reasoning 7.45s, total 18.18s
