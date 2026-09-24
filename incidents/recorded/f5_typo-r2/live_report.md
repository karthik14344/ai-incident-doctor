# Incident inc_38689da628

**Alert:** HighErrorRate - gateway is answering 5.644% of requests with 5xx
**Started:** 2026-09-23T18:41:03.987Z  
**Running commit:** 6089cc6  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

Gateway is answering 5.644% of requests with 5xx

**Incident class:** `code_defect`

**Demand versus capacity:** traffic flat, deploy before onset: True, verdict: capacity_fell. Traffic up with no relevant deploy; service up went down

## Evidence

- alert 2026-09-23T18:41:03.987Z **HighErrorRate** gateway: gateway is answering 5.644% of requests with 5xx
- log `AttributeError:c869db82b3fd` x15 in gateway: AttributeError 'ChatRequest' object has no attribute 'qestion'
- log `WARNING:a4dace19f999` x2 in gateway:  request
- log `ConnectError:8dda9665dd81` x1 in gateway: ConnectError All connection attempts failed
- metric `error_ratio_5xx{service=gateway}` baseline None -> 0.1521 (appeared (no baseline))
- metric `in_flight{service=retrieval}` baseline 0.4138 -> 1.0 (x2.4)
- metric `service_up{__name__=up}` baseline 0.9677 -> 0.0 (went down)

Deploys in the lookback window: 22; candidate commits (time filter only): 37

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.90 | retrieval | d08706d | Fail fast when retrieval is slow |

Evidence for #1:
- retrieval: lexical=17.71 semantic=0.7708 matched=['gateway', 'telemetry', 'api', 'retrieval', 'api_gateway', 'chat']

## Proposed fix

**Kind:** code_diff

Apply the fix to the ChatRequest class to handle the 'question' attribute correctly

## Verification

**Result:** unverified - needs human review
  
no applicable diff was produced

Nothing was applied to the running system.

## Cost

2 calls, 7322 prompt + 514 completion tokens, $0.0; reasoning 5.03s, total 16.25s
