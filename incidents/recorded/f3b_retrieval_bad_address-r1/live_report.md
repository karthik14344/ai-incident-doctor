# Incident inc_33f8181556

**Alert:** DownstreamCallFailures - calls from gateway to retrieval are failing
**Started:** 2026-09-23T15:17:28.987Z  
**Running commit:** 6abf2ab  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

Calls from gateway to retrieval are failing

**Incident class:** `capacity`

**Demand versus capacity:** traffic flat, deploy before onset: True, verdict: capacity_fell. Traffic up with no relevant deploy; latency p95_s{endpoint=/api/retrieval/search,service=gateway} rose x139.6

## Evidence

- alert 2026-09-23T15:17:28.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- alert 2026-09-23T15:17:30.51Z **HighLatencyP95** gateway: p95 latency of gateway /api/retrieval/search is 10.0s
- log `WARNING:a4dace19f999` x67 in gateway:  request
- log `ConnectError:11530a30dc36` x28 in gateway: ConnectError [Errno -2] Name or service not known
- metric `traffic_rps{all}` baseline 0.5574 -> 0.891 (x1.6)
- metric `requests_rps{service=gateway}` baseline 0.6211 -> 0.9637 (x1.6)
- metric `requests_rps{service=llm}` baseline 0.2213 -> 0.3818 (x1.7)
- metric `requests_rps{service=retrieval}` baseline 0.6229 -> 0.9455 (x1.5)
- metric `error_ratio_5xx{service=gateway}` baseline 0.047 -> 0.7073 (x15.0)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.1598 -> 0.3455 (x2.2)
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline None -> 0.2546 (appeared (no baseline))
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 2.143 -> 12.0833 (x5.6)

Deploys in the lookback window: 14; candidate commits (time filter only): 23

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.80 | retrieval | none | Inconsistent service configuration |

Evidence for #1:
- log signature ConnectError:11530a30dc36 appeared at ...
- metric latency_p95_s{endpoint=/api/retrieval/search,service=gateway} rose x139.6

## Proposed fix

**Kind:** action

Restart the gateway service to resolve the issue.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 6890 prompt + 514 completion tokens, $0.0; reasoning 4.91s, total 14.33s
