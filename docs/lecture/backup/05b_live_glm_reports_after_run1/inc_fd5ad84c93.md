# Incident inc_fd5ad84c93

**Alert:** HighErrorRate - gateway is answering 34.57% of requests with 5xx
**Started:** 2026-09-24T10:22:03.987Z  
**Running commit:** 73e80cf  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** glm:glm-4.5-flash

## What broke

The gateway service is experiencing high error rates (34.57% 5xx) due to connection failures to the retrieval service, which appears to be down or unreachable.

**Incident class:** `dependency_failure`

**Demand versus capacity:** traffic rose, deploy before onset: True, verdict: capacity_fell. Traffic to gateway increased by 3.8x (from 0.83 to 3.15 RPS) during the incident, but the primary issue is the retrieval service becoming unavailable (service_up metric went to 0), causing downstream connection failures from gateway to retrieval.

## Evidence

- alert 2026-09-24T10:18:06.923Z **ServiceDown** retrieval: retrieval is not answering Prometheus scrapes
- alert 2026-09-24T10:18:38.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- alert 2026-09-24T10:18:45.51Z **HighLatencyP95** gateway: p95 latency of gateway /api/retrieval/search is 12.0s
- alert 2026-09-24T10:21:03.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing intermittently
- alert 2026-09-24T10:21:10.625Z **ChatAnswersRefused** gateway: 51.53% of chat questions were refused as outside the documents
- alert 2026-09-24T10:22:03.987Z **HighErrorRate** gateway: gateway is answering 34.57% of requests with 5xx
- log `WARNING:a4dace19f999` x69 in gateway:  request
- log `ConnectError:5b2993ef741b` x30 in gateway: ConnectError [Errno -5] No address associated with hostname
- log `ConnectError:8dda9665dd81` x5 in gateway: ConnectError All connection attempts failed
- metric `requests_rps{service=gateway}` baseline 0.8348 -> 3.1457 (x3.8)
- metric `requests_rps{service=llm}` baseline 0.1559 -> 1.4001 (x9.0)
- metric `requests_rps{service=retrieval}` baseline 0.8481 -> 3.0548 (x3.6)
- metric `error_ratio_5xx{service=gateway}` baseline None -> 0.6346 (appeared (no baseline))
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.26 -> 1.3274 (x5.1)
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline None -> 0.2727 (appeared (no baseline))
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 2.9456 -> 19.5722 (x6.6)
- metric `latency_p95_s{endpoint=/api/retrieval/search,service=gateway}` baseline 0.0797 -> 19.5692 (x245.5)

Deploys in the lookback window: 1; candidate commits (time filter only): 4

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.90 | retrieval | none | The retrieval service is down or unreachable, causing gateway to fail when trying to connect to it. |
| 2 | 0.60 | gateway | abeae76 | The gateway service may have a configuration issue in how it's attempting to connect to the retrieval service. |
| 3 | 0.50 | infrastructure | none | The increased traffic during the incident may have overwhelmed the retrieval service. |

Evidence for #1:
- ServiceDown alert for retrieval service at 2026-09-24T10:18:06.923Z
- ConnectError logs in gateway showing 'No address associated with hostname'
- service_up metric went to 0 during incident

Evidence for #2:
- ConnectError logs in gateway at /app/common/telemetry.py:183
- DownstreamCallFailures alert from gateway to retrieval

Evidence for #3:
- requests_rps for retrieval increased by 3.6x during incident
- in_flight for retrieval increased by 21x

## Proposed fix

**Kind:** action

The primary issue appears to be the retrieval service being down (service_up=0), which is causing gateway connection failures. Restarting the service should restore connectivity. If the issue persists, check the retrieval service's network configuration and dependencies.

**Recommended action:** Restart the retrieval service and check its configuration to ensure it's properly listening on the expected address and port.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 7154 prompt + 1206 completion tokens, $0.006945; reasoning 65.1s, total 65.25s

