# Incident inc_2dfbad634b

**Alert:** HighLatencyP95 - p95 latency of gateway /api/chat is 80.7s
**Started:** 2026-09-23T17:52:20.51Z  
**Running commit:** 1f00121  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

Gateway /api/chat p95 latency exceeded 40s threshold

**Incident class:** `capacity`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: capacity_fell. Traffic_rps{service=gateway} increased by 1.9819, while baseline was 3.5308, and in_flight{service=gateway} increased by 100.0, while baseline was 0.3929

## Evidence

- alert 2026-09-23T17:52:20.51Z **HighLatencyP95** gateway: p95 latency of gateway /api/chat is 80.7s
- alert 2026-09-23T17:52:25.51Z **HighLatencyP95** llm: p95 latency of llm /generate is 82.7s
- metric `requests_rps{service=llm}` baseline 0.2622 -> 1.6001 (x6.1)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.195 -> 1.5273 (x7.8)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 2.4881 -> 88.5 (x35.6)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 2.371 -> 88.5 (x37.3)
- metric `latency_p50_s{endpoint=/api/chat,service=gateway}` baseline 1.1748 -> 75.0 (x63.8)
- metric `latency_p50_s{endpoint=/generate,service=llm}` baseline 1.1221 -> 75.0 (x66.8)
- metric `in_flight{service=gateway}` baseline 0.3929 -> 100.0 (x254.5)
- metric `in_flight{service=llm}` baseline 0.1429 -> 100.0 (x699.8)

Deploys in the lookback window: 21; candidate commits (time filter only): 38

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.80 | retrieval | none | Inadequate retrieval performance |

Evidence for #1:
- retrieval: lexical=9.22 semantic=0.7562 matched=['timeout', 'gateway', 'chat', 'api', 'retrieval']
- requests_rps{service=retrieval} baseline=3.5406 incident_max=1.0938 (x3.2)

## Proposed fix

**Kind:** action

Scale the gateway service to handle increased traffic

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 7524 prompt + 600 completion tokens, $0.0; reasoning 144.16s, total 158.85s
