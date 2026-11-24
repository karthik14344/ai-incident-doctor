# Incident inc_82acf4538b

**Alert:** UserReport - It no longer answers questions about the library, scholarships or placements.
**Started:** 2026-11-24T14:47:31Z  
**Running commit:** b26c3a9  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

Retrieval, generation and Ollama are healthy, with no error logs, no restarts and no embedding fallbacks, yet a user reports that one set of topics (library, scholarships, placements) no longer gets answered. The most likely cause is that the knowledge base no longer holds those documents, though the evidence for this is indirect.

**Incident class:** `data_issue`

**Demand versus capacity:** traffic rose, deploy before onset: False, verdict: neither. Traffic went from ~0 (baseline 0.0 rps) to a mean of 0.50 rps (max 0.89), so demand rose. But the system served it well. Retrieval p95 was about 0.08s, embed p95 0.0475s and LLM generate p95 4.2s, all far under the 30s gateway timeout. in_flight peaked at 2, there were no restarts or OOM kills, and service_up stayed at 1. The 'answered' outcome rose with traffic. The last deploy was b26c3a9 on 2026-11-22, two days earlier, and there are no candidate commits. Neither demand outrunning capacity nor a capacity drop fits a complaint limited to specific topics. That pattern points to missing content, not a performance problem.

## Evidence

- metric `traffic_rps{all}` baseline 0.0 -> 0.8909 (from ~0)
- metric `requests_rps{service=gateway}` baseline 0.1019 -> 0.9818 (x9.6)
- metric `requests_rps{service=ingestion}` baseline 0.1038 -> 0.2545 (x2.5)
- metric `requests_rps{service=llm}` baseline 0.1038 -> 0.4182 (x4.0)
- metric `requests_rps{service=retrieval}` baseline 0.1021 -> 1.0 (x9.8)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.0 -> 0.3455 (from ~0)
- metric `chat_outcomes_rps{outcome=refused_output}` baseline None -> 0.0182 (appeared (no baseline))
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline None -> 4.2 (appeared (no baseline))

Deploys in the lookback window: 0; candidate commits (time filter only): 0

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.55 | knowledge_base | none | Documents covering library, scholarships and placements are missing from the 'default' collection. Possible reasons are deletion, a re-ingest without them, or a knowledge-base change made before the lookback window. Retrieval runs fine but returns no relevant chunks, so the LLM cannot answer those questions. |
| 2 | 0.20 | infrastructure | none | Demand rose from ~0 to ~0.9 rps. The onset signal (chat_errors_per_min 0 -> 1.09) shows some chats erroring as load arrived, and the user may be reading those failures as topic-specific. |
| 3 | 0.10 | llm | none | The output guardrail is refusing some answers on these topics. |

Evidence for #1:
- The user report is topic-specific: 'no longer answers questions about the library, scholarships or placements', so other topics still work.
- chat_outcomes_rps{outcome=answered} rose to 0.35 rps, so the pipeline answers other questions end to end.
- There are no warning or error logs, no stack traces, and embedding_fallbacks_per_min stayed at 0 for both retrieval and ingestion, so embedding and retrieval are not failing outright.
- Retrieval /retrieve p95 is 0.083s and Chroma has no restarts, so the vector store responds; it may simply return irrelevant chunks.
- Ingestion took steady traffic at baseline (mean 0.10 rps), so collection contents may have been changed by ingestion activity.
- There is no deploy or KB version change in the lookback window, so any removal predates it or came from an untracked ingestion operation.

Evidence for #2:
- traffic_rps rose from 0.0 to a max of 0.89, and gateway requests_rps rose x9.6.
- LLM /generate p95 climbed from 1.925s to 4.2s over the window, and llm in_flight reached 2.
- Against this, nothing is saturated: memory ratios are under 0.15, there are no OOM kills, and latency is well under the timeouts.

Evidence for #3:
- chat_outcomes_rps{outcome=refused_output} appeared during the incident (max 0.018 rps), but it is far too small to explain the whole complaint.

## Proposed fix

**Kind:** action

The code paths, deploys and dependencies all look healthy, and the symptom is limited to one set of topics. That is the signature of missing knowledge-base content, and restoring the documents is the fix that matches it. Because no KB change was recorded in the window, verify first through the debug retrieval endpoint.

**Recommended action:** 1. Confirm the cause before changing anything. Call POST /api/retrieval/search with sample questions about the library, scholarships and placements. Check whether the 'default' collection returns relevant chunks, and list which source documents the collection holds. 2. If those documents are missing, a human operator should re-ingest them from the source corpus through the ingestion service, or restore the last knowledge-base version known to contain them. 3. Re-run the same questions to confirm they are answered. 4. If the documents are present and retrieval looks correct, re-check the chat error counts against load and investigate the gateway chat path. Nothing should be applied to the running system automatically.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

1 calls, 7945 prompt + 2493 completion tokens, $0.08164; reasoning 25.17s, total 25.32s
