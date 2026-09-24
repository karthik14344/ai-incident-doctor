# Incident inc_f5bf806250

**Alert:** HighErrorRate - gateway is answering 6.218% of requests with 5xx
**Started:** 2026-09-23T15:02:03.987Z  
**Running commit:** 8b35c3b  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

Gateway is answering 6.218% of requests with 5xx

**Incident class:** `capacity`

**Demand versus capacity:** traffic flat, deploy before onset: True, verdict: capacity_fell. Demand rose, but capacity did not increase to match, as indicated by flat traffic_rps and requests_rps, and in_flight increasing from 0.2759 to 1.0

## Evidence

- alert 2026-09-23T15:02:03.987Z **HighErrorRate** gateway: gateway is answering 6.218% of requests with 5xx
- log `AttributeError:c869db82b3fd` x27 in gateway: AttributeError 'ChatRequest' object has no attribute 'qestion'
- log `ConnectError:8dda9665dd81` x1 in gateway: ConnectError All connection attempts failed
- log `WARNING:a4dace19f999` x1 in gateway:  request
- metric `traffic_rps{all}` baseline 0.5527 -> 0.891 (x1.6)
- metric `requests_rps{service=gateway}` baseline 0.6132 -> 0.9637 (x1.6)
- metric `requests_rps{service=ingestion}` baseline 0.0678 -> 0.1091 (x1.6)
- metric `error_ratio_5xx{service=gateway}` baseline 0.0544 -> 0.1759 (x3.2)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.1571 -> 0.2727 (x1.7)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 2.1765 -> 3.9 (x1.8)
- metric `latency_p95_s{endpoint=/api/retrieval/search,service=gateway}` baseline 0.0663 -> 0.13 (x2.0)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 2.0841 -> 4.0 (x1.9)

Deploys in the lookback window: 13; candidate commits (time filter only): 22

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.90 | gateway | none | Inadequate capacity to handle increased demand |

Evidence for #1:
- in_flight{service=gateway} baseline=0.2759 incident_max=1.0 (x3.6)
- requests_rps{service=gateway} baseline=0.6132 incident_max=0.9637 (x1.6)

## Proposed fix

**Kind:** action

Scale the gateway service to increase capacity

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

1 calls, 3312 prompt + 273 completion tokens, $0.0; reasoning 2.91s, total 14.57s
