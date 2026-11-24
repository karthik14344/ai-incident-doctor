# Incident inc_d9cbee9e2e

**Alert:** DownstreamCallFailures - calls from gateway to retrieval are failing
**Started:** 2026-11-22T09:21:28.987Z  
**Running commit:** 4c8b3c0  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

From about 09:20:21Z the gateway can no longer resolve the retrieval service's hostname. Every gateway->retrieval call fails with httpx ConnectError '[Errno -3] Temporary failure in name resolution', which pushes gateway 5xx to 75%. Traffic is flat and retrieval itself shows no restarts or OOMs, so retrieval has most likely become unreachable by name on the Docker network.

**Incident class:** `dependency_failure`

**Demand versus capacity:** traffic flat, deploy before onset: True, verdict: capacity_fell. traffic_rps is flat: baseline mean 0.59, incident mean 0.63, with the incident max (0.85) below the baseline max (0.87). Gateway in_flight max rose only to 2, so demand did not drive this. The failures are sudden and new: ConnectError gateway->retrieval goes from absent to 51/min, and requests reaching retrieval drop from about 0.85 to 0.07 rps. A gateway-only deploy (4c8b3c0) landed at 09:07:18Z, but the errors start about 13 minutes later at 09:20:21Z. No candidate commit touches service addressing or networking, so the deploy does not explain a DNS resolution failure that appears mid-run.

## Evidence

- alert 2026-11-22T09:21:28.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- log `WARNING:a4dace19f999` x63 in gateway:  request
- log `ConnectError:bf91e0cfbf34` x29 in gateway: ConnectError [Errno -3] Temporary failure in name resolution
- metric `requests_rps{service=llm}` baseline 0.2394 -> 0.3818 (x1.6)
- metric `error_ratio_5xx{service=gateway}` baseline 0.0447 -> 0.7451 (x16.7)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.183 -> 0.3455 (x1.9)
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline None -> 0.2545 (appeared (no baseline))
- metric `latency_p50_s{endpoint=/api/retrieval/search,service=gateway}` baseline 0.0386 -> 0.0588 (x1.5)
- metric `in_flight{service=gateway}` baseline 0.2333 -> 2.0 (x8.6)
- metric `in_flight{service=llm}` baseline 0.1333 -> 1.0 (x7.5)
- metric `downstream_failures_per_min{reason=ConnectError,service=gateway,target=retrieval}` baseline None -> 51.2727 (appeared (no baseline))

Deploys in the lookback window: 7; candidate commits (time filter only): 16

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.65 | retrieval | none | The retrieval container stopped being resolvable on the compose network. Likely causes are that it was disconnected from the network or lost its DNS name or alias. The gateway's httpx client therefore fails at name resolution and never reaches retrieval. |
| 2 | 0.20 | infrastructure | none | Docker's embedded DNS, or the host resolver used by the gateway container, broke. This would be an infrastructure-level name-resolution failure rather than a problem with retrieval itself. |
| 3 | 0.15 | gateway | none | The gateway's configured retrieval address was changed to a hostname that does not exist. This would be a configuration error in the gateway environment. |

Evidence for #1:
- New log signature ConnectError bf91e0cfbf34 (x29, absent in baseline) reads '[Errno -3] Temporary failure in name resolution' at common/telemetry.py:194 handle_async_request, first seen 09:20:21Z.
- downstream_failures_per_min{reason=ConnectError,target=retrieval} appeared with no baseline, max 51.3.
- requests_rps{service=retrieval} fell from 0.85 at window start to 0.07 at window end, so calls no longer arrive.
- container_restarts and oom_kills for retrieval stay at 0, and the retrieval process memory is steady, so the process looks alive but unreachable by name.
- chat_outcomes refused_scope appeared at 0.25 rps, consistent with chat proceeding without retrieved context.

Evidence for #2:
- The error is EAI_AGAIN ('Temporary failure in name resolution'), which is a resolver error rather than connection refused.
- Only the gateway->retrieval failure counter appears, but the LLM still receives some traffic, so the resolver failure may be selective.

Evidence for #3:
- Gateway deploy 4c8b3c0 at 09:07:18Z is the running build.
- The onset is 13 minutes after that deploy and no candidate commit changes addressing, which weakens this explanation.

## Proposed fix

**Kind:** action

The gateway fails at DNS resolution of the retrieval host while retrieval shows no crash, restart or OOM, and traffic is flat. Restoring retrieval's name resolution on the network brings back the dependency. No code change is implicated.

**Recommended action:** 1. From inside the gateway container, check whether the retrieval hostname resolves (e.g. `getent hosts retrieval` or a python socket.getaddrinfo) and compare it with the configured retrieval URL.
2. Run `docker network inspect` on the compose network to confirm the retrieval container is attached with its service alias.
3. If retrieval is detached, reconnect it with its alias (`docker network connect --alias retrieval <network> <retrieval-container>`), or recreate it with `docker compose up -d retrieval`.
4. If the gateway's retrieval address was changed, restore the correct service hostname.
5. Verify that downstream ConnectError failures drop to 0 and that gateway error_ratio_5xx returns to about 4%.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

1 calls, 10357 prompt + 2274 completion tokens, $0.086908; reasoning 22.93s, total 27.55s
