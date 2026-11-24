# Incident inc_83fa18ffae

**Alert:** ServiceDown - retrieval is not answering Prometheus scrapes
**Started:** 2026-11-22T12:11:06.923Z  
**Running commit:** 6961a53  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

The retrieval container stopped being reachable at about 12:10. Its hostname no longer resolves on the compose network, and it fails every Prometheus scrape. Gateway calls to retrieval now fail with ConnectError, which drives gateway 5xx to 77% and pushes answerless chats into refused_scope. Traffic was flat, and no deploy or listed commit explains retrieval disappearing.

**Incident class:** `dependency_failure`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: capacity_fell. traffic_rps was 0.60 mean in the baseline and 0.63 in the incident, so demand did not rise. Capacity fell when the retrieval service went down: up dropped to 0, and the gateway logged ConnectError 'Temporary failure in name resolution' from 12:10:20Z. The only recent deploy, 6961a53 at 11:57:17Z, touched only the gateway, came 13 minutes before onset, and nothing shown ties it to name resolution. Retrieval itself was last deployed at 11:35:42Z (3c9f8fa) and ran healthily afterwards.

## Evidence

- alert 2026-11-22T12:11:06.923Z **ServiceDown** retrieval: retrieval is not answering Prometheus scrapes
- alert 2026-11-22T12:11:28.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- log `WARNING:a4dace19f999` x59 in gateway:  request
- log `ConnectError:bf91e0cfbf34` x17 in gateway: ConnectError [Errno -3] Temporary failure in name resolution
- metric `requests_rps{service=llm}` baseline 0.2526 -> 0.4182 (x1.7)
- metric `error_ratio_5xx{service=gateway}` baseline 0.0581 -> 0.775 (x13.3)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.1874 -> 0.3455 (x1.8)
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline None -> 0.1636 (appeared (no baseline))
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 2.4483 -> 4.0 (x1.6)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 2.3636 -> 4.1 (x1.7)
- metric `in_flight{service=gateway}` baseline 0.2069 -> 2.0 (x9.7)
- metric `in_flight{service=llm}` baseline 0.2414 -> 2.0 (x8.3)

Deploys in the lookback window: 17; candidate commits (time filter only): 28

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.80 | retrieval | none | The retrieval container/process stopped or was removed, so its DNS name 'retrieval' no longer resolves on the Docker network. The gateway cannot connect to it and Prometheus cannot scrape it. |
| 2 | 0.15 | infrastructure | none | A network or compose-level change (for example the retrieval service being detached from the network or renamed) removed its DNS entry while the process may still be running. |
| 3 | 0.05 | gateway | none | Gateway deploy 6961a53 (11:57) changed how the gateway reaches retrieval. |

Evidence for #1:
- service_up for retrieval:8002 went from 0.97 to 0.0; the ServiceDown alert fired at 12:11:06Z
- New log signature: ConnectError '[Errno -3] Temporary failure in name resolution' in gateway at telemetry.py:194, x17, first seen 12:10:20Z
- downstream_failures_per_min{reason=ConnectError,target=retrieval} appeared, max 50/min
- requests_rps{service=retrieval} fell from 0.75 to 0.16; gateway error_ratio_5xx rose from 0.06 to 0.775
- refused_scope outcomes appeared because chats proceed with no retrieved context
- retrieval memory was steady at about 96 MB, so there is no sign of OOM growth before it went away

Evidence for #2:
- The error is a name-resolution failure (EAI_AGAIN), not connection refused or a timeout, so the lookup itself fails
- No deploy touched retrieval or compose near 12:10

Evidence for #3:
- The gateway was the last service deployed, but failures began 13 minutes later
- Prometheus also cannot scrape retrieval, which is independent of gateway code

## Proposed fix

**Kind:** action

The retrieval service is unreachable at the DNS level and nothing in the candidate commits plausibly removes it. Restoring the dependency is the direct remedy. A code or config change is not warranted, and this should be done by an operator, not applied automatically.

**Recommended action:** Check the retrieval container's state and exit reason (docker compose ps retrieval; docker compose logs --tail=200 retrieval). Restart it with docker compose up -d retrieval so it rejoins the network and its DNS name resolves again. Then confirm that up{job=retrieval}=1, the gateway ConnectError rate drops to 0, and chat_outcomes return to answered. If it exited on its own, look into the exit cause (exit code, OOM kill flag) before closing.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

1 calls, 10315 prompt + 1781 completion tokens, $0.07688; reasoning 18.23s, total 22.87s
