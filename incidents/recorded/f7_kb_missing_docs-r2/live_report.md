# Incident inc_97ae8af9da

**Alert:** UserReport - It no longer answers questions about the library, scholarships or placements.
**Started:** 2026-09-23T19:27:06Z  
**Running commit:** c5614c2  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

User report of library, scholarships, and placements not being answered

**Incident class:** `code_defect`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: capacity_fell. Traffic rose x2.0, but no deploy shortly before the onset

## Evidence

- alert 2026-09-23T19:17:28.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- log `ReadTimeout:3bd5a2c1f252` x3 in gateway: ReadTimeout retrieval call failed
- metric `traffic_rps{all}` baseline 0.8248 -> 1.6365 (x2.0)
- metric `requests_rps{service=gateway}` baseline 0.8923 -> 1.7092 (x1.9)
- metric `requests_rps{service=llm}` baseline 0.4696 -> 1.3092 (x2.8)
- metric `requests_rps{service=retrieval}` baseline 0.8894 -> 1.691 (x1.9)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.4039 -> 1.2546 (x3.1)
- metric `chat_outcomes_rps{outcome=refused_output}` baseline 0.0008 -> 0.0182 (x22.8)
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline 0.0337 -> 0.0545 (x1.6)
- metric `latency_p95_s{endpoint=/retrieve,service=retrieval}` baseline 0.0616 -> 0.1 (x1.6)

Deploys in the lookback window: 26; candidate commits (time filter only): 43

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.80 | retrieval | none | retrieval not handling slow cases correctly |

Evidence for #1:
- retrieval: lexical=5.82 semantic=0.7779 matched=['retrieval', 'telemetry', 'timeout', 'gateway']
- Fail fast when retrieval is slow - it normally answers in about 30 ms

## Proposed fix

**Kind:** code_diff

Add a timeout handler to the retrieval service

## Verification

**Result:** unverified - needs human review
  
no applicable diff was produced

Nothing was applied to the running system.

## Cost

2 calls, 7656 prompt + 514 completion tokens, $0.0; reasoning 6.15s, total 19.53s
