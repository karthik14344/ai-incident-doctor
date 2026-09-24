# Incident inc_ffbeaa1ad2

**Alert:** UserReport - The assistant says it has nothing relevant in the documents, for every question.
**Started:** 2026-09-24T10:35:39Z  
**Running commit:** 73e80cf  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** glm:glm-4.5-flash

## What broke

The retrieval service is failing to respond to requests, causing the assistant to report having no relevant documents.

**Incident class:** `dependency_failure`

**Demand versus capacity:** traffic fell, deploy before onset: True, verdict: capacity_fell. Traffic decreased during the incident, but the retrieval service became unresponsive. The ServiceDown alert and ConnectError logs indicate a dependency failure rather than capacity issues.

## Evidence

- alert 2026-09-24T10:36:46.923Z **ServiceDown** retrieval: retrieval is not answering Prometheus scrapes
- alert 2026-09-24T10:37:13.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- alert 2026-09-24T10:37:25.51Z **HighLatencyP95** gateway: p95 latency of gateway /api/retrieval/search is 11.7s
- log `WARNING:a4dace19f999` x10 in gateway:  request
- log `ConnectError:5b2993ef741b` x4 in gateway: ConnectError [Errno -5] No address associated with hostname
- metric `chat_outcomes_rps{outcome=refused_output}` baseline 0.0 -> 0.0182 (from ~0)
- metric `latency_p95_s{endpoint=/api/retrieval/search,service=gateway}` baseline 3.0305 -> 7.85 (x2.6)
- metric `latency_p95_s{endpoint=/retrieve,service=retrieval}` baseline 0.0606 -> 0.145 (x2.4)
- metric `in_flight{service=gateway}` baseline 0.8571 -> 3.0 (x3.5)
- metric `in_flight{service=llm}` baseline 0.4286 -> 1.0 (x2.3)
- metric `in_flight{service=retrieval}` baseline 0.0 -> 1.0 (from ~0)
- metric `service_up{__name__=up}` baseline 0.8929 -> 0.0 (went down)
- metric `ollama_p95_s{operation=embed}` baseline 0.0507 -> 0.0845 (x1.7)

Deploys in the lookback window: 2; candidate commits (time filter only): 4

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.90 | retrieval | none | The retrieval service is not answering Prometheus scrapes and calls from the gateway are failing. |
| 2 | 0.70 | gateway | none | The telemetry module in the gateway is unable to connect to the retrieval service. |
| 3 | 0.50 | ollama | none | The Ollama embedding service is experiencing increased latency, potentially affecting retrieval. |

Evidence for #1:
- ServiceDown alert fired at 2026-09-24T10:36:46.923Z
- DownstreamCallFailures alert fired at 2026-09-24T10:37:13.987Z
- ConnectError logs show 'No address associated with hostname'

Evidence for #2:
- ConnectError logs in gateway telemetry module
- HighLatencyP95 alert for gateway /api/retrieval/search endpoint

Evidence for #3:
- ollama_p95_s for embed operation increased by 1.7x
- Increased latency in retrieval service

## Proposed fix

**Kind:** action

The retrieval service is completely unresponsive (service_up metric went to 0), indicating a service failure rather than a configuration issue. A restart should restore the service to a working state.

**Recommended action:** Restart the retrieval service to restore connectivity

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 7057 prompt + 1033 completion tokens, $0.006507; reasoning 36.28s, total 36.42s
