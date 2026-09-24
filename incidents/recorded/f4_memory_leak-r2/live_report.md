# Incident inc_1898ba07d1

**Alert:** MemoryClimbing - resident memory of retrieval is growing by 236.6kiB/s
**Started:** 2026-09-23T20:11:56.176Z  
**Running commit:** 2354deb  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** ollama:llama3.2

## What broke

MemoryClimbing labels indicate steady growth in retrieval process memory

**Incident class:** `capacity`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: capacity_fell. Traffic RPS increased by 6x, while process memory MB rose by 3x

## Evidence

- alert 2026-09-23T20:11:56.176Z **MemoryClimbing** retrieval: resident memory of retrieval is growing by 236.6kiB/s
- metric `traffic_rps{all}` baseline 1.1304 -> 7.2551 (x6.4)
- metric `requests_rps{service=gateway}` baseline 1.195 -> 7.3096 (x6.1)
- metric `requests_rps{service=llm}` baseline 0.2382 -> 0.4182 (x1.8)
- metric `requests_rps{service=retrieval}` baseline 1.1751 -> 7.3461 (x6.3)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.1746 -> 0.3455 (x2.0)
- metric `in_flight{service=gateway}` baseline 0.1034 -> 3.0 (x29.0)
- metric `in_flight{service=llm}` baseline 0.2414 -> 2.0 (x8.3)
- metric `in_flight{service=retrieval}` baseline 0.0345 -> 1.0 (x29.0)

Deploys in the lookback window: 27; candidate commits (time filter only): 46

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.80 | retrieval | none | Potential memory leak in the retrieval service |

Evidence for #1:
- log signature 'memory allocation exceeded' appeared at ...
- metric 'process memory MB' rose 3x

## Proposed fix

**Kind:** action

Restart the retrieval service to identify and fix the memory leak

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 7611 prompt + 458 completion tokens, $0.0; reasoning 5.49s, total 17.96s
