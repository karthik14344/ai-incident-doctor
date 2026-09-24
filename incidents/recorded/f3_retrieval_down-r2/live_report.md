# Incident inc_d6b392195b

**Alert:** ServiceDown - retrieval is not answering Prometheus scrapes
**Started:** 2026-09-23T18:54:26.923Z  
**Running commit:** 4d271b9  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

retrieval is not answering Prometheus scrapes

**Incident class:** `capacity`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: capacity_fell. Traffic increased, but capacity did not keep up with the demand.

## Evidence

- alert 2026-09-23T18:54:26.923Z **ServiceDown** retrieval: retrieval is not answering Prometheus scrapes
- alert 2026-09-23T18:54:53.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- alert 2026-09-23T18:55:00.51Z **HighLatencyP95** gateway: p95 latency of gateway /api/retrieval/search is 12.2s
- log `WARNING:a4dace19f999` x34 in gateway:  request
- log `ConnectError:5b2993ef741b` x17 in gateway: ConnectError [Errno -5] No address associated with hostname
- metric `traffic_rps{all}` baseline 0.5653 -> 0.8909 (x1.6)
- metric `requests_rps{service=gateway}` baseline 0.6296 -> 0.9637 (x1.5)
- metric `requests_rps{service=llm}` baseline 0.228 -> 0.4 (x1.8)
- metric `error_ratio_5xx{service=gateway}` baseline 0.0577 -> 0.6333 (x11.0)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.162 -> 0.3273 (x2.0)
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline 0.0421 -> 0.1818 (x4.3)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 4.7441 -> 16.5 (x3.5)
- metric `latency_p95_s{endpoint=/api/retrieval/search,service=gateway}` baseline 1.2466 -> 13.7 (x11.0)

Deploys in the lookback window: 23; candidate commits (time filter only): 38

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.90 | retrieval | none | Insufficient capacity in the retrieval service |

Evidence for #1:
- HighLatencyP95 gateway: p95 latency of gateway /api/retrieval/search is 12.2s
- in_flight{service=retrieval}: baseline=0.4138 incident_max=1.0 (x2.4)

## Proposed fix

**Kind:** action

Scale the retrieval service to handle the increased traffic.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

1 calls, 3778 prompt + 240 completion tokens, $0.0; reasoning 2.69s, total 12.46s
