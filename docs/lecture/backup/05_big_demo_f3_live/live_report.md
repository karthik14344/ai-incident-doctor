# Incident inc_a7d4de5377

**Alert:** ServiceDown - retrieval is not answering Prometheus scrapes
**Started:** 2026-09-24T10:36:46.923Z  
**Running commit:** 73e80cf  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** glm:glm-4.5-flash

## What broke

The retrieval service is not answering Prometheus scrapes, causing downstream failures and high latency in the gateway.

**Incident class:** `dependency_failure`

**Demand versus capacity:** traffic fell, deploy before onset: True, verdict: capacity_fell. Traffic decreased during the incident, but the retrieval service became unresponsive, causing downstream failures and increased latency in the gateway. The issue appears to be with the retrieval service itself rather than capacity.

## Evidence

- alert 2026-09-24T10:36:46.923Z **ServiceDown** retrieval: retrieval is not answering Prometheus scrapes
- alert 2026-09-24T10:37:13.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- alert 2026-09-24T10:37:25.51Z **HighLatencyP95** gateway: p95 latency of gateway /api/retrieval/search is 11.7s
- log `WARNING:a4dace19f999` x27 in gateway:  request
- log `ConnectError:5b2993ef741b` x21 in gateway: ConnectError [Errno -5] No address associated with hostname
- metric `error_ratio_5xx{service=gateway}` baseline 0.1631 -> 0.5556 (x3.4)
- metric `chat_outcomes_rps{outcome=refused_output}` baseline 0.0 -> 0.0182 (from ~0)
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline 0.0571 -> 0.2364 (x4.1)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 5.1458 -> 19.09 (x3.7)
- metric `latency_p95_s{endpoint=/api/retrieval/search,service=gateway}` baseline 2.9856 -> 18.25 (x6.1)
- metric `latency_p95_s{endpoint=/retrieve,service=retrieval}` baseline 0.0581 -> 0.1375 (x2.4)
- metric `latency_p50_s{endpoint=/api/chat,service=gateway}` baseline 2.3942 -> 11.5 (x4.8)
- metric `latency_p50_s{endpoint=/api/retrieval/search,service=gateway}` baseline 1.3017 -> 10.1875 (x7.8)

Deploys in the lookback window: 2; candidate commits (time filter only): 4

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.90 | retrieval | none | The retrieval service is not responding to requests, causing the gateway to fail with ConnectError. |
| 2 | 0.70 | retrieval | none | The telemetry configuration in the retrieval service is causing it to not respond to Prometheus scrapes. |
| 3 | 0.50 | retrieval | none | The deployment at 73e80cf may have introduced a configuration issue affecting the retrieval service. |

Evidence for #1:
- ServiceDown alert for retrieval service
- ConnectError log signature in gateway: 'No address associated with hostname'
- service_up metric went to 0 for retrieval service

Evidence for #2:
- The telemetry module is used to instrument the FastAPI app in retrieval service
- /metrics endpoint is failing to respond

Evidence for #3:
- Deploy occurred at 2026-09-24T10:22:31Z, just before the incident window
- No specific code changes in the deployment that directly affect retrieval service

## Proposed fix

**Kind:** action

The retrieval service appears to be unresponsive to requests, including Prometheus scrapes. A restart may resolve any transient issues or clear stuck processes. If the issue persists, further investigation into the telemetry configuration and service dependencies would be needed.

**Recommended action:** Restart the retrieval service to clear any potential runtime issues

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Rule violations by the model

- named a commit that is not a candidate: 73e80cf

## Cost

2 calls, 6970 prompt + 1093 completion tokens, $0.006587; reasoning 51.21s, total 51.43s
