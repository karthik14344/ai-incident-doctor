# Incident inc_33667034f5

**Alert:** MemoryClimbing - resident memory of retrieval is growing by 245.4kiB/s
**Started:** 2026-09-23T17:37:26.176Z  
**Running commit:** 6a33acf  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

MemoryClimbing labels indicate retrieval is slow, causing high traffic and latency

**Incident class:** `capacity`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: capacity_fell. Traffic increased by 6x, while capacity remained constant

## Evidence

- alert 2026-09-23T17:37:26.176Z **MemoryClimbing** retrieval: resident memory of retrieval is growing by 245.4kiB/s
- metric `traffic_rps{all}` baseline 1.1175 -> 7.4731 (x6.7)
- metric `requests_rps{service=gateway}` baseline 1.1804 -> 7.5277 (x6.4)
- metric `requests_rps{service=llm}` baseline 0.2524 -> 0.4 (x1.6)
- metric `requests_rps{service=retrieval}` baseline 1.1924 -> 7.491 (x6.3)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.1818 -> 0.3273 (x1.8)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 2.4602 -> 3.9 (x1.6)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 2.4044 -> 3.9 (x1.6)
- metric `in_flight{service=gateway}` baseline 0.1724 -> 2.0 (x11.6)

Deploys in the lookback window: 20; candidate commits (time filter only): 37

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.90 | retrieval | none | Fail fast when retrieval is slow |

Evidence for #1:
- retrieval: lexical=8.97 semantic=0.7645 matched=['retrieval', 'timeout', 'gateway', 'api', 'chat']
- file patient/api_gateway/app/main.py contains a potential fix

## Proposed fix

**Kind:** action

Restart the retrieval service to prevent slow responses

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 7375 prompt + 507 completion tokens, $0.0; reasoning 6.52s, total 18.64s
