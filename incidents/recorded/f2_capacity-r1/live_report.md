# Incident inc_a2d5a9858a

**Alert:** HighLatencyP95 - p95 latency of gateway /api/chat is 83.2s
**Started:** 2026-09-23T12:26:30.51Z  
**Running commit:** 9c2db40  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

Gateway /api/chat p95 latency exceeded threshold

**Incident class:** `capacity`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: capacity_fell. Traffic RPS increased by x2.9, while capacity remained the same.

## Evidence

- alert 2026-09-23T12:26:30.51Z **HighLatencyP95** gateway: p95 latency of gateway /api/chat is 83.2s
- alert 2026-09-23T12:26:30.51Z **HighLatencyP95** llm: p95 latency of llm /generate is 83.0s
- alert 2026-09-23T12:28:21.176Z **MemoryClimbing** gateway: resident memory of gateway is growing by 662.7kiB/s
- alert 2026-09-23T12:28:26.176Z **MemoryClimbing** llm: resident memory of llm is growing by 306.9kiB/s
- metric `traffic_rps{all}` baseline 0.6647 -> 1.9455 (x2.9)
- metric `requests_rps{service=gateway}` baseline 0.7277 -> 2.0183 (x2.8)
- metric `requests_rps{service=llm}` baseline 0.4963 -> 1.5819 (x3.2)
- metric `requests_rps{service=retrieval}` baseline 0.7459 -> 3.4184 (x4.6)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.4274 -> 1.5092 (x3.5)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 29.5432 -> 88.5 (x3.0)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 28.6878 -> 88.5 (x3.1)
- metric `latency_p50_s{endpoint=/api/chat,service=gateway}` baseline 22.1445 -> 75.0 (x3.4)

Deploys in the lookback window: 14; candidate commits (time filter only): 52

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.90 | gateway | none | Increased traffic from the gateway service |

Evidence for #1:
- requests_rps{service=gateway} baseline=0.7277 incident_max=2.0183
- requests_rps{service=gateway} incident_max=2.0183 (x2.8)

## Proposed fix

**Kind:** action

Scale the gateway service to handle increased traffic.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

1 calls, 3354 prompt + 235 completion tokens, $0.0; reasoning 72.65s, total 73.26s
