# Incident inc_790d9ddcfb

**Alert:** DownstreamCallFailures - calls from gateway to retrieval are failing intermittently
**Started:** 2026-09-23T19:12:03.987Z  
**Running commit:** e91ff59  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

Calls from gateway to retrieval are failing intermittently

**Incident class:** `capacity`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: capacity_fell. Demand rose significantly while capacity remained steady

## Evidence

- alert 2026-09-23T19:12:03.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing intermittently
- log `ReadTimeout:3bd5a2c1f252` x13 in gateway: ReadTimeout retrieval call failed
- metric `traffic_rps{all}` baseline 0.5785 -> 1.691 (x2.9)
- metric `requests_rps{service=gateway}` baseline 0.643 -> 1.7637 (x2.7)
- metric `requests_rps{service=llm}` baseline 0.2364 -> 1.3455 (x5.7)
- metric `requests_rps{service=retrieval}` baseline 0.6329 -> 1.7273 (x2.7)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.1672 -> 1.2728 (x7.6)
- metric `chat_outcomes_rps{outcome=refused_output}` baseline 0.0014 -> 0.0182 (x13.0)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 3.4796 -> 6.8859 (x2.0)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 2.0599 -> 6.71 (x3.3)

Deploys in the lookback window: 25; candidate commits (time filter only): 42

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.90 | retrieval | none | Fail fast when retrieval is slow |

Evidence for #1:
- retrieval: lexical=20.37 semantic=0.8191 matched=['retrieval', 'timeout', 'telemetry', 'gateway', 'api', 'client']
- record_downstream_failure (lines 208-210) in patient/common/telemetry.py

## Proposed fix

**Kind:** action

Restart the gateway service to clear the downstream failures

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 7823 prompt + 506 completion tokens, $0.0; reasoning 7.01s, total 17.94s
