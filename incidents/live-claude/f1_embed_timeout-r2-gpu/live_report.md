# Incident inc_b233d93740

**Alert:** UserReport - Answers have been wrong or unrelated to my question for a while now.
**Started:** 2026-11-22T11:08:20Z  
**Running commit:** 4e34716  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

A user reports wrong or unrelated answers, but no errors, restarts, fallbacks or KB changes appear and traffic was flat or falling. The most plausible cause is a retrieval behaviour change from the two retrieval-only deploys, 6cd5503 (10:14Z) and 4e34716 (10:30Z, running at alert time). Neither deploy's commits are in the candidate list, so no commit can be named and confidence is low.

**Incident class:** `code_defect`

**Demand versus capacity:** traffic flat, deploy before onset: True, verdict: capacity_fell. Demand did not rise. traffic_rps averaged 1.04 in the incident window against 1.40 in the baseline, and incident max was 1.62 against a baseline max of 6.29. The symptom is answer quality, not throughput: chat_outcomes answered stayed about 0.62-0.63 rps, with no errors or log warnings. Two deploys touched only retrieval shortly before the window: 6cd5503 at 10:14Z and 4e34716 at 10:30Z, which was running at alert time. Retrieval process memory dropped from a baseline peak of 347 MB to a steady 104 MB, consistent with a restart and changed behaviour. The high LLM latency (p95 118.5 s, in_flight 100) already existed in the baseline during a traffic burst, and it decays to about 1.9 s by the end of the window, so it is not new. 'Capacity_fell' here means served quality degraded under the same load after a deploy, not lost throughput.

## Evidence

- metric `requests_rps{service=llm}` baseline 0.6875 -> 1.1455 (x1.7)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.6172 -> 1.0727 (x1.7)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 58.296 -> 118.5 (x2.0)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 58.3707 -> 118.5 (x2.0)
- metric `latency_p50_s{endpoint=/api/chat,service=gateway}` baseline 49.8475 -> 105.0 (x2.1)
- metric `latency_p50_s{endpoint=/generate,service=llm}` baseline 49.8393 -> 105.0 (x2.1)
- metric `in_flight{service=gateway}` baseline 53.4333 -> 100.0 (x1.9)
- metric `in_flight{service=llm}` baseline 53.4 -> 100.0 (x1.9)

Deploys in the lookback window: 13; candidate commits (time filter only): 24

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.45 | retrieval | none | A retrieval-service change in deploy 6cd5503 or 4e34716 now returns irrelevant or wrong context chunks, so the LLM answers from unrelated context without any error. Possible causes include ranking or filtering, top_k handling, collection selection or the embedding call. The commits are not in the candidate list. |
| 2 | 0.25 | ollama | none | Ollama generation saturation: 100 concurrent generations and p95 near the 120 s client timeout degrade or truncate answers during load bursts. This was already present in the baseline and is recovering. |
| 3 | 0.10 | gateway | none | The gateway retrieval timeout of 0.05 s from cf515c9 makes chat skip retrieval context. This is unlikely because commit 1c5b681 reverted it at 09:48Z, and the running chat_stream code shows timeout=30.0. |

Evidence for #1:
- Only retrieval was deployed recently: 6cd5503 at 10:14:15Z and 4e34716 at 10:30:38Z, the latter running at alert time.
- No warning or error logs, no restarts, no OOMs and embedding_fallbacks_per_min=0, which fits silent wrong behaviour rather than a failure.
- ollama_p95_s{operation=embed} sits at a constant 0.0475 through the incident window, while the baseline varied with a max of 0.39. Query embedding may not be happening or may have changed.
- Retrieval process_memory_mb fell from a baseline max of 347 to a flat 104, suggesting different runtime behaviour after the 10:30 deploy.
- No KB version change in the lookback window, so a changed document set is unlikely.

Evidence for #2:
- in_flight{service=llm} reached 100 in both the baseline and incident windows.
- latency_p95_s{endpoint=/generate} hit 118.5 s, right under the 120 s timeout noted in ee1a12f.
- The baseline traffic burst reached 6.29 rps, and latency decays to 1.9 s by the end of the incident window.

Evidence for #3:
- cf515c9 diff: `timeout=0.05` on the gateway's /retrieve call would silently drop context.
- Running code at the alert shows `telemetry.async_client("gateway", timeout=30.0)`, meaning the revert is live.
- Retrieval requests_rps tracks gateway requests, so retrieval is still being called.

## Proposed fix

**Kind:** action

Answers are wrong but nothing errors, and the only recent changes are two retrieval-only deploys whose commits are not among the candidates. Confirming retrieval relevance and rolling back that service is the lowest-risk way to restore correct context. No code edit is proposed because the retrieval diff is not available to cite.

**Recommended action:** Verify first, then roll back if confirmed. 1) Diff the retrieval service between the pre-10:14 build (70c3dff) and 4e34716. 2) Run a few known evaluation questions through /api/retrieval/search and check whether the returned chunks are relevant. 3) If they are not, have an operator redeploy the retrieval service at its pre-6cd5503 version and re-check answer relevance with the evaluation set. 4) Separately, if generation p95 stays near 120 s under load, consider limiting concurrent generations or scaling Ollama. Nothing should be applied automatically.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

1 calls, 10531 prompt + 3421 completion tokens, $0.110544; reasoning 35.47s, total 35.68s
