# Incident inc_23acd950cd

**Alert:** DownstreamCallFailures - calls from gateway to retrieval are failing
**Started:** 2026-11-22T13:33:13.987Z  
**Running commit:** b26c3a9  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

From about 13:32Z the gateway can no longer resolve the retrieval service's hostname (httpx.ConnectError '[Errno -3] Temporary failure in name resolution'). This points to the retrieval service being stopped or no longer registered on the Docker network under its usual name. Gateway 5xx rose to 61%, and chats that still get through come back as refused_scope because they have no retrieved context. No candidate commit explains a DNS failure, so this is a dependency outage of the retrieval service.

**Incident class:** `dependency_failure`

**Demand versus capacity:** traffic fell, deploy before onset: True, verdict: capacity_fell. Demand did not rise. traffic_rps fell from a baseline mean of 3.43 to an incident mean of 0.61, and gateway in_flight mean fell from 0.43 to 0.32. Capacity collapsed instead. A new ConnectError signature to retrieval appeared at 13:32:04Z (up to 37 failures/min), gateway 5xx appeared at 0.61, and retrieval requests_rps fell to 0.07 by the end of the window. A retrieval deploy (b26c3a9) landed at 13:19:57Z, about 12 minutes before onset, but its commit is not among the candidates. The listed commits only change a gateway timeout, which would cause ReadTimeout rather than name-resolution failures, and that change was already reverted by 50c9efc. No listed commit explains the symptoms.

## Evidence

- alert 2026-11-22T13:33:13.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- log `WARNING:a4dace19f999` x48 in gateway:  request
- log `ConnectError:bf91e0cfbf34` x30 in gateway: ConnectError [Errno -3] Temporary failure in name resolution
- metric `requests_rps{service=llm}` baseline 0.263 -> 0.4 (x1.5)
- metric `error_ratio_5xx{service=gateway}` baseline None -> 0.6061 (appeared (no baseline))
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.2011 -> 0.3273 (x1.6)
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline None -> 0.2727 (appeared (no baseline))
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 2.3414 -> 3.9 (x1.7)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 2.3751 -> 3.8 (x1.6)
- metric `in_flight{service=gateway}` baseline 0.4333 -> 3.0 (x6.9)
- metric `in_flight{service=llm}` baseline 0.3333 -> 1.0 (x3.0)

Deploys in the lookback window: 20; candidate commits (time filter only): 26

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.75 | retrieval | none | The retrieval container/service is down or detached from the compose network (lost its service name/alias), so Docker DNS no longer resolves its hostname. Every gateway->retrieval call therefore fails at connect time. |
| 2 | 0.15 | retrieval | none | The retrieval rollout b26c3a9 (13:19:57Z) left the service in a state that later stopped or crashed it, or recreated it without its network alias/hostname. The commit itself is not in the candidate list. |
| 3 | 0.10 | infrastructure | none | An infrastructure DNS / Docker embedded resolver problem is affecting name resolution from the gateway container. |

Evidence for #1:
- New log signature bf91e0cfbf34 x30 in gateway from 13:32:04Z: httpx.ConnectError [Errno -3] Temporary failure in name resolution at common/telemetry.py:194
- downstream_failures_per_min{reason=ConnectError,target=retrieval} appeared (no baseline), max 37.09/min
- requests_rps{service=retrieval} fell from a baseline mean of 3.52 to 0.07 by the end of the window; retrieval in_flight is 0 throughout the incident
- error_ratio_5xx{gateway} appeared, max 0.61; chat_outcomes refused_scope appeared (chats answered without retrieved context)

Evidence for #2:
- deploy b26c3a9 touched only ['retrieval'] about 12 minutes before the first ConnectError
- process_memory_mb{retrieval} dropped from a baseline max of 323 MB to about 98 MB, consistent with a process restart

Evidence for #3:
- The error is a resolver failure (EAI_AGAIN 'Temporary failure in name resolution') rather than connection refused
- Gateway calls to the llm service still appear to succeed (llm requests_rps continues), which argues against a general DNS outage

## Proposed fix

**Kind:** action

Gateway calls fail at DNS resolution of the retrieval host, so the retrieval endpoint is missing from the network rather than slow or returning wrong results. Restoring the service and its network registration removes the ConnectErrors. No code or config edit is justified by the listed commits.

**Recommended action:** 1. Check the retrieval container's state, e.g. `docker compose ps retrieval`, plus its logs and exit code around 13:30Z, and its network attachments (`docker inspect`).
2. Bring it back on the knowledgeai network with its usual service name/alias, e.g. `docker compose up -d retrieval`, or reconnect it with `docker network connect --alias <retrieval host> ...`.
3. Verify the recovery:
   - name resolution works from the gateway container (`getent hosts <retrieval host>`);
   - /retrieve answers;
   - ConnectError failures drop to 0;
   - gateway 5xx clears.
4. If the b26c3a9 rollout caused the exit, the operator may decide to roll retrieval back to the previous image (8645aa3).

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 22344 prompt + 4347 completion tokens, $0.176316; reasoning 38.67s, total 43.31s
