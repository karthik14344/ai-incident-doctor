# Incident inc_297e429a9b

**Alert:** HighErrorRate - gateway is answering 5.556% of requests with 5xx
**Started:** 2026-11-22T09:04:03.987Z  
**Running commit:** 5dc7f1a  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

Commit 19871dd changed how the gateway titles new chat sessions and introduced a typo (req.qestion). Any new-session chat whose question has no '?' now raises AttributeError and returns a 5xx. Traffic was flat, so this is a code defect, not load.

**Incident class:** `code_defect`

**Demand versus capacity:** traffic flat, deploy before onset: True, verdict: capacity_fell. Demand did not rise. traffic_rps mean was 0.592 in the baseline and 0.562 in the incident window, and gateway in_flight mean fell from 0.45 to 0.21. Gateway 5xx went from 0 to as high as 10.7% right after the gateway-only deploy 225b7d2 at 08:57:03Z, which contains commit 19871dd. The first AttributeError appeared at 08:56:59Z, and the stack trace points to the line that diff added. Ollama, retrieval and llm latencies, as well as restarts and OOM kills, look the same as baseline.

## Evidence

- alert 2026-11-22T09:04:03.987Z **HighErrorRate** gateway: gateway is answering 5.556% of requests with 5xx
- log `AttributeError:c869db82b3fd` x19 in gateway: AttributeError 'ChatRequest' object has no attribute 'qestion'
- log `WARNING:a4dace19f999` x3 in gateway:  request
- metric `requests_rps{service=llm}` baseline 0.2642 -> 0.4 (x1.5)
- metric `error_ratio_5xx{service=gateway}` baseline 0.0 -> 0.1071 (from ~0)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.1946 -> 0.3091 (x1.6)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 2.5204 -> 3.9 (x1.5)
- metric `latency_p95_s{endpoint=/api/retrieval/search,service=gateway}` baseline 0.0974 -> 0.1825 (x1.9)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 2.409 -> 4.2 (x1.7)
- metric `latency_p95_s{endpoint=/retrieve,service=retrieval}` baseline 0.0647 -> 0.204 (x3.2)
- metric `in_flight{service=gateway}` baseline 0.4483 -> 2.0 (x4.5)

Deploys in the lookback window: 6; candidate commits (time filter only): 15

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.95 | gateway | 19871dd | Typo introduced by commit 19871dd in chat_stream: len(req.qestion) instead of len(req.question). Pydantic raises AttributeError for any new session (no session_id) whose question contains no '?', and the gateway returns 500. |
| 2 | 0.03 | gateway | none | Commit 44405f4 (also gateway, deployed in 5dc7f1a) only adds a comment to the health check and cannot explain the errors. It is listed only to rule it out. |

Evidence for #1:
- New log signature AttributeError:c869db82b3fd x19 in gateway: 'ChatRequest' object has no attribute 'qestion' at api_gateway/app/main.py chat_stream, first seen 08:56:59Z, absent in baseline
- Diff line in 19871dd: + title = req.question.strip()[:60] + ("..." if len(req.qestion) > 60 else "")
- error_ratio_5xx{service=gateway} rose from 0.0 to max 0.1071 after deploy 225b7d2 (08:57:03Z); traffic_rps flat (0.59 -> 0.56)
- ChatRequest defines only 'question', not 'qestion'

Evidence for #2:
- Diff adds only a comment line above gateway_health
- AttributeError started before 5dc7f1a was deployed (08:56:59Z vs 08:57:45Z)

## Proposed fix

**Kind:** code_diff

Fix the misspelled attribute so chat_stream no longer raises AttributeError for new sessions whose question has no '?'. This keeps the intended 60-character title behaviour from 19871dd. The alternative is to revert 19871dd. Review and deploy through the normal pipeline.

```diff
--- a/patient/api_gateway/app/main.py
+++ b/patient/api_gateway/app/main.py
@@ -475,7 +475,7 @@
         if "?" in req.question:
             title = req.question.split("?")[0].strip()[:60] + "?"
         else:
-            title = req.question.strip()[:60] + ("..." if len(req.qestion) > 60 else "")
+            title = req.question.strip()[:60] + ("..." if len(req.question.strip()) > 60 else "")
         cursor.execute("INSERT INTO chat_sessions (id, title, created_at) VALUES (?, ?, ?)", (session_id, title, datetime.utcnow().isoformat()))
         conn.commit()
```

## Verification

**Result:** verified
  
Test suite on the patched copy: 171 passed, 4 warnings in 4.49s

Nothing was applied to the running system.

## Cost

1 calls, 10620 prompt + 1305 completion tokens, $0.06858; reasoning 13.03s, total 23.93s
