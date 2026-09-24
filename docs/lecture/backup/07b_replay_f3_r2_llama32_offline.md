<!-- Backup: offline replay (no internet) of incidents/recorded/f3_retrieval_down-r2 with local llama3.2, run 2026-09-24 ~10:47 UTC, 4.6 s.
Command (PowerShell, from doctor/): ..\.venv\Scripts\python.exe -m app.replay ..\incidents\recorded\f3_retrieval_down-r2\bundle.json --provider ollama --model llama3.2
The class it gives (capacity) is WRONG - truth is dependency_failure. Compare 07_replay_f3_r2_glm/report.md (GLM, correct). -->

# Incident inc_d6b392195b

**Alert:** ServiceDown - retrieval is not answering Prometheus scrapes
**Started:** 2026-09-23T18:54:26.923Z  
**Running commit:** 4d271b9  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

retrieval is not answering Prometheus scrapes

**Incident class:** `capacity`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: capacity_fell. Traffic increased, but capacity did not rise to meet the demand. The latency of the gateway increased, but the retrieval service was not the bottleneck.

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
| 1 | 0.80 | gateway | none | The latency of the gateway increased, but the retrieval service was not the bottleneck. |

Evidence for #1:
- metric Y rose x10 (latency_p95_s{endpoint=/api/retrieval/search,service=gateway}: baseline=1.2466 incident_max=13.7)
- log signature X appeared at ... (DownstreamCallFailures gateway: calls from gateway to retrieval are failing)

## Proposed fix

**Kind:** action

Restart the gateway service to see if it resolves the issue.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

1 calls, 3779 prompt + 276 completion tokens, $0.0; reasoning 3.5s, total 4.27s

