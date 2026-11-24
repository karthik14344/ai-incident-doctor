# Incident inc_69be87b774

**Alert:** HighErrorRate - gateway is answering 5.941% of requests with 5xx
**Started:** 2026-11-22T11:54:03.987Z  
**Running commit:** d0ba09a  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

Commit d0ba09a reintroduced a typo (`req.qestion`) in the gateway's chat_stream session-titling code. Every new chat session whose question contains no '?' now raises AttributeError and returns a 5xx, which pushed the gateway error ratio to about 6-10% while traffic stayed flat.

**Incident class:** `code_defect`

**Demand versus capacity:** traffic flat, deploy before onset: True, verdict: capacity_fell. Demand did not rise: traffic_rps mean was 0.60 in the baseline and 0.59 in the incident, and gateway requests_rps was 0.67 vs 0.65. Gateway in_flight peaked at only 2. Gateway deploy d0ba09a landed at 11:48:24Z. The first AttributeError appeared at 11:48:17Z, the same moment the new container started. 5xx responses then appeared where the baseline had none. The deployed diff directly explains the exception. The latency maxima (x1.8) sit within normal baseline variance (baseline p95 max was 4.15s) and are not the cause.

## Evidence

- alert 2026-11-22T11:54:03.987Z **HighErrorRate** gateway: gateway is answering 5.941% of requests with 5xx
- log `AttributeError:c869db82b3fd` x18 in gateway: AttributeError 'ChatRequest' object has no attribute 'qestion'
- metric `requests_rps{service=llm}` baseline 0.2644 -> 0.4182 (x1.6)
- metric `error_ratio_5xx{service=gateway}` baseline None -> 0.1001 (appeared (no baseline))
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.199 -> 0.3273 (x1.6)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 2.3806 -> 4.2 (x1.8)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 2.3276 -> 4.2 (x1.8)
- metric `latency_p95_s{endpoint=/retrieve,service=retrieval}` baseline 0.0589 -> 0.0975 (x1.7)
- metric `latency_p50_s{endpoint=/generate,service=llm}` baseline 1.0386 -> 1.6667 (x1.6)
- metric `in_flight{service=gateway}` baseline 0.1667 -> 2.0 (x12.0)

Deploys in the lookback window: 16; candidate commits (time filter only): 27

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.95 | gateway | d0ba09a | Commit d0ba09a changed new-session titling. In the else-branch (question without '?') it reads `len(req.qestion)`, a misspelling of `question`. Pydantic raises AttributeError, chat_stream fails, and the gateway returns 500 for every new session whose question lacks a question mark. |
| 2 | 0.15 | gateway | none | A brief gateway scrape gap or restart during the d0ba09a rollout (service_up dropped to 0) may have added a few transient errors. This is secondary to the persistent AttributeError. |

Evidence for #1:
- New log signature AttributeError:c869db82b3fd x18 'ChatRequest' object has no attribute 'qestion' at /app/api_gateway/app/main.py:478 in chat_stream, first=11:48:17Z, running=['d0ba09a']
- Diff of d0ba09a adds line: title = req.question.strip()[:60] + ("..." if len(req.qestion) > 60 else "")
- ChatRequest model defines only `question`, not `qestion`
- error_ratio_5xx{gateway} appeared from no baseline to max 0.1001 right after the deploy at 11:48:24Z, with flat traffic
- The identical change (19871dd) was deployed earlier and reverted in 4c8b3c0; d0ba09a reintroduced it

Evidence for #2:
- service_up baseline=0.97, incident min=0 (went down)
- process_memory_mb{gateway} dropped from a baseline max of 316MB to about 99MB, consistent with a container restart at deploy

## Proposed fix

**Kind:** code_diff

This corrects the misspelled attribute so new sessions with questions lacking '?' no longer raise AttributeError. The titling feature is kept. Reverting d0ba09a (as 4c8b3c0 did previously) is an equally valid alternative. The change should go through normal review and deploy and should not be applied automatically. A unit test that creates a session from a question without '?' would prevent this from coming back a third time.

```diff
--- a/patient/api_gateway/app/main.py
+++ b/patient/api_gateway/app/main.py
@@ -475,7 +475,7 @@
         if "?" in req.question:
             title = req.question.split("?")[0].strip()[:60] + "?"
         else:
-            title = req.question.strip()[:60] + ("..." if len(req.qestion) > 60 else "")
+            title = req.question.strip()[:60] + ("..." if len(req.question) > 60 else "")
         cursor.execute("INSERT INTO chat_sessions (id, title, created_at) VALUES (?, ?, ?)", (session_id, title, datetime.utcnow().isoformat()))
         conn.commit()
```

## Verification

**Result:** verified
  
Test suite on the patched copy: 171 passed, 4 warnings in 4.66s

Nothing was applied to the running system.

## Cost

1 calls, 10604 prompt + 1703 completion tokens, $0.076476; reasoning 16.31s, total 26.98s
