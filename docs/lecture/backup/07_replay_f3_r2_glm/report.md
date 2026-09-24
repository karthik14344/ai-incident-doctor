# Incident inc_d6b392195b

**Alert:** ServiceDown - retrieval is not answering Prometheus scrapes
**Started:** 2026-09-23T18:54:26.923Z  
**Running commit:** 4d271b9  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** glm:glm-4.5-flash

## What broke

The retrieval service is not responding to Prometheus scrapes, causing downstream failures and high latency in the gateway service.

**Incident class:** `dependency_failure`

**Demand versus capacity:** traffic rose, deploy before onset: True, verdict: capacity_fell. Traffic increased by 1.6x, but the primary issue is the retrieval service becoming unreachable, as evidenced by ConnectError logs and the service_up metric dropping to 0.

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
| 1 | 0.90 | retrieval | none | The retrieval service is down or unreachable due to a network configuration issue or service failure. |
| 2 | 0.60 | retrieval | none | The retrieval service is running but unable to respond to requests due to resource exhaustion or deadlock. |
| 3 | 0.50 | gateway | none | A recent deployment to the gateway service introduced a bug in the telemetry module that's causing connection issues. |

Evidence for #1:
- ConnectError logs in gateway: 'No address associated with hostname'
- service_up metric dropped to 0 during incident
- DownstreamCallFailures alert triggered for gateway->retrieval

Evidence for #2:
- in_flight for retrieval increased by 2.4x during incident
- HighLatencyP95 alert for gateway's /api/retrieval/search endpoint

Evidence for #3:
- Most recent deploy (4d271b9) was to gateway service
- ConnectError logs appear in gateway service telemetry

## Proposed fix

**Kind:** action

The primary evidence points to the retrieval service being completely unreachable (service_up=0), suggesting a service failure rather than a code defect. The most immediate action is to restart the service to restore functionality.

**Recommended action:** Restart the retrieval service and check its logs for any errors. If the issue persists, verify network connectivity between gateway and retrieval services.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Rule violations by the model

- named a commit that is not a candidate: 4d271b9

## Cost

2 calls, 8350 prompt + 1114 completion tokens, $0.0; reasoning 39.39s, total 40.7s
