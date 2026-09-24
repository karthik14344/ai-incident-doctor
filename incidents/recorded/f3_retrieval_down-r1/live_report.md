# Incident inc_62e26ac22f

**Alert:** DownstreamCallFailures - calls from gateway to retrieval are failing
**Started:** 2026-09-23T11:15:43.987Z  
**Running commit:** ffb6f14  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

Calls from gateway to retrieval are failing

**Incident class:** `capacity`

**Demand versus capacity:** traffic flat, deploy before onset: True, verdict: capacity_fell. Demand rose, but capacity did not increase to match. The incident window shows a deploy shortly before the onset, with no notable changes in traffic or capacity metrics.

## Evidence

- alert 2026-09-23T11:15:43.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- alert 2026-09-23T11:16:01.923Z **ServiceDown** retrieval: retrieval is not answering Prometheus scrapes
- alert 2026-09-23T11:16:33.987Z **HighErrorRate** gateway: gateway is answering 34.72% of requests with 5xx
- alert 2026-09-23T11:16:40.51Z **HighLatencyP95** gateway: p95 latency of gateway /api/retrieval/search is 18.3s
- log `WARNING:a4dace19f999` x27 in gateway:  request
- log `ConnectError:5b2993ef741b` x11 in gateway: ConnectError [Errno -5] No address associated with hostname
- log `ConnectError:11530a30dc36` x5 in gateway: ConnectError [Errno -2] Name or service not known
- log `ConnectError:8dda9665dd81` x3 in gateway: ConnectError All connection attempts failed
- metric `traffic_rps{all}` baseline 0.318 -> 0.8728 (x2.7)
- metric `requests_rps{service=gateway}` baseline 0.3814 -> 0.9273 (x2.4)
- metric `requests_rps{service=llm}` baseline 0.1539 -> 0.4 (x2.6)
- metric `requests_rps{service=retrieval}` baseline 0.3333 -> 0.9455 (x2.8)
- metric `error_ratio_5xx{service=gateway}` baseline 0.0537 -> 0.5484 (x10.2)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.088 -> 0.3273 (x3.7)
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline 0.024 -> 0.2182 (x9.1)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 5.7709 -> 19.6182 (x3.4)

Deploys in the lookback window: 11; candidate commits (time filter only): 42

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.80 | gateway | none | Inadequate capacity to handle increased demand |

Evidence for #1:
- Metric requests_rps{service=gateway} rose x2.4
- Metric latency_p95_s{endpoint=/api/retrieval/search,service=gateway} rose x5.6

## Proposed fix

**Kind:** action

Scale the gateway service to increase capacity and handle the increased demand.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

1 calls, 3336 prompt + 251 completion tokens, $0.0; reasoning 3.28s, total 23.08s
