# Incident inc_1c061b33ad

**Alert:** DownstreamCallFailures - calls from gateway to retrieval are failing
**Started:** 2026-09-23T16:40:38.987Z  
**Running commit:** 1accbed  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

Calls from gateway to retrieval are failing

**Incident class:** `capacity`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: capacity_fell. Traffic RPS increased by 3.8x, while capacity remained the same.

## Evidence

- alert 2026-09-23T16:40:38.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- alert 2026-09-23T16:41:03.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing intermittently
- log `ReadTimeout:3bd5a2c1f252` x9 in gateway: ReadTimeout retrieval call failed
- log `WARNING:a4dace19f999` x2 in gateway:  request
- metric `traffic_rps{all}` baseline 0.4745 -> 1.8183 (x3.8)
- metric `requests_rps{service=gateway}` baseline 0.5396 -> 1.891 (x3.5)
- metric `requests_rps{service=llm}` baseline 0.2604 -> 1.3819 (x5.3)
- metric `requests_rps{service=retrieval}` baseline 0.7713 -> 1.891 (x2.5)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.1431 -> 1.3092 (x9.1)
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline 0.0006 -> 0.0545 (x90.8)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 2.3119 -> 6.6875 (x2.9)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 1.9197 -> 6.7253 (x3.5)

Deploys in the lookback window: 19; candidate commits (time filter only): 33

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.90 | retrieval | none | Insufficient capacity in the retrieval service |

Evidence for #1:
- log signature ReadTimeout appeared at ...
- metric traffic_rps rose x3.8

## Proposed fix

**Kind:** action

Scale the retrieval service to handle increased traffic.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 7267 prompt + 442 completion tokens, $0.0; reasoning 6.05s, total 17.05s
