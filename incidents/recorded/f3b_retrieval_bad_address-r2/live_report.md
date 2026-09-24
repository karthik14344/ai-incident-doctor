# Incident inc_ab945bb462

**Alert:** DownstreamCallFailures - calls from gateway to retrieval are failing
**Started:** 2026-09-23T20:26:23.987Z  
**Running commit:** 16735bd  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

Calls from gateway to retrieval are failing

**Incident class:** `capacity`

**Demand versus capacity:** traffic flat, deploy before onset: True, verdict: capacity_fell. Demand rose, but capacity did not increase to match. Recent deployment of 16735bd introduced changes to the gateway service, which may have caused the failure.

## Evidence

- alert 2026-09-23T20:26:23.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- alert 2026-09-23T20:27:10.51Z **HighLatencyP95** gateway: p95 latency of gateway /api/retrieval/search is 7.4s
- log `WARNING:a4dace19f999` x54 in gateway:  request
- log `ConnectError:11530a30dc36` x34 in gateway: ConnectError [Errno -2] Name or service not known
- metric `requests_rps{service=llm}` baseline 0.2622 -> 0.4 (x1.5)
- metric `error_ratio_5xx{service=gateway}` baseline 0.0062 -> 0.6341 (x102.3)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.1918 -> 0.3455 (x1.8)
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline 0.0084 -> 0.3273 (x39.0)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 2.3199 -> 11.75 (x5.1)
- metric `latency_p95_s{endpoint=/api/retrieval/search,service=gateway}` baseline 0.21 -> 7.7125 (x36.7)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 2.234 -> 3.9 (x1.7)
- metric `latency_p50_s{endpoint=/api/chat,service=gateway}` baseline 1.0449 -> 5.0 (x4.8)

Deploys in the lookback window: 26; candidate commits (time filter only): 43

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.70 | gateway | none | Recent deployment of 16735bd introduced changes to the gateway service, which may have caused the failure. |

Evidence for #1:
- log signature X appeared at ...
- metric Y rose x10

## Proposed fix

**Kind:** code_diff

Add checks to the record_downstream_failure function to handle slow retrievals more robustly.

## Verification

**Result:** unverified - needs human review
  
no applicable diff was produced

Nothing was applied to the running system.

## Cost

2 calls, 6029 prompt + 489 completion tokens, $0.0; reasoning 5.15s, total 15.73s
