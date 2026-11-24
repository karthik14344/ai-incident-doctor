# Incident inc_f1dff65801

**Alert:** UserReport - Answers have been wrong or unrelated to my question for a while now.
**Started:** 2026-11-22T08:18:07Z  
**Running commit:** 1a290b0  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

A user reports answers that are wrong or unrelated to the question, but no metric, log line or deploy explains it. Retrieval and embedding are healthy and nothing changed. The most likely cause is the knowledge base or retrieved context not matching what the user asks: missing or wrong documents, or a wrong collection. A runtime settings change such as embedding_model, top_k or collection is the alternative. Confidence is low.

**Incident class:** `data_issue`

**Demand versus capacity:** traffic flat, deploy before onset: False, verdict: neither. Traffic did not rise. traffic_rps averaged 1.061 in the baseline and 0.897 in the incident window; peaks were similar (1.58 vs 1.65). The only deploy (1a290b0) was at 07:23:16Z, about 55 minutes before onset and before the baseline window started. Its commits only touch the GCP start-up and Ollama scripts and agent/doctor config, so none of them can make answers semantically wrong. Generation latency (p50 about 55s, p95 up to 118.5s, in_flight reaching 100) is high, but it is just as high in the baseline. The report is also about correctness, not slowness or errors. There are no 5xx errors, restarts, OOM kills or embedding fallbacks, and no warning/error logs. This is neither a demand rise nor a capacity drop.

## Evidence

- metric `traffic_rps{all}` baseline 1.061 -> 1.6545 (x1.6)
- metric `requests_rps{service=gateway}` baseline 1.1378 -> 1.7091 (x1.5)
- metric `requests_rps{service=llm}` baseline 0.7161 -> 1.1636 (x1.6)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.6364 -> 1.0727 (x1.7)
- metric `chat_outcomes_rps{outcome=refused_output}` baseline 0.0029 -> 0.0182 (x6.3)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 62.3759 -> 118.5 (x1.9)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 64.4639 -> 118.5 (x1.8)
- metric `latency_p50_s{endpoint=/api/chat,service=gateway}` baseline 54.0744 -> 105.0 (x1.9)

Deploys in the lookback window: 1; candidate commits (time filter only): 6

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.40 | knowledge_base | none | Retrieval returns context that does not match the user's questions, so the LLM answers from irrelevant chunks. Possible reasons: the knowledge base lacks the documents the user expects, documents are stale or wrong, or the query targets a collection that does not hold the relevant content. |
| 2 | 0.30 | retrieval | none | Runtime settings stored in the gateway settings table were changed without a deploy. Examples: embedding_model differing from the model used at ingestion, a very small top_k, or a different llm_model. Any of these silently degrades retrieval relevance or answer quality. |
| 3 | 0.15 | ollama | none | A long-standing LLM saturation (in_flight pinned at 100, p50 near 105s at peaks) degrades the user experience. Slow streamed responses may be cut off or abandoned, which the user perceives as wrong or unrelated answers. This condition predates the window, so it is not a new incident. |

Evidence for #1:
- The symptom is answer relevance, while every health signal is nominal. Retrieval p50 is 0.026s and p95 0.054s, unchanged; embed p95 is 0.0475s, unchanged; embedding_fallbacks_per_min is 0.
- No knowledge-base version change is in the lookback window (kb=38ba55c908d1 loaded with deploy 1a290b0), so the content may be stale or incomplete for what the user asks.
- chat_outcomes answered/refused rates are proportional to traffic, so the pipeline completes. The problem is what it retrieves or generates, not whether it runs.

Evidence for #2:
- chat_stream builds the retrieval payload from get_settings_map(): top_k, embedding_model and ollama_base_url, each falling back to a default. These are editable at runtime via SettingsRequest and leave no deploy trace.
- No errors or fallbacks would be raised if the embedding model was swapped for one with the same dimension, or if top_k was lowered. Relevance drops silently.
- No metric departed from baseline, which fits a silent quality regression rather than a failure.

Evidence for #3:
- in_flight{service=llm} reached 100 in both windows; ollama_p95_s{generate} max was 118.5s in both.
- latency_p50_s /generate averaged 55.9s in the baseline and 39.9s in the incident window. The load is not new, only persistent.

## Proposed fix

**Kind:** action

No code, config diff or deploy is implicated, and no metric moved, so a code or config edit cannot be justified. The fastest way to confirm or rule out the knowledge-base and settings hypotheses is to replay the reported questions through retrieval and compare the context with what is expected. Nothing should be applied to the running system automatically.

**Recommended action:** Investigate before changing anything. (1) Get the user's example questions and their session_id. Replay each question through POST /api/retrieval/search with the same collection_name. Check whether the returned chunks are relevant and come from the expected documents. (2) Inspect the gateway settings table: embedding_model must equal the model used at ingestion (nomic-embed-text). Also check top_k, llm_model and ollama_base_url against defaults, and revert any unintended change. (3) Check the Chroma collection: document count, sources, and kb version 38ba55c908d1. If the expected documents are missing or stale, re-ingest the correct knowledge-base version. (4) Separately, track the persistent LLM saturation (in_flight 100, p95 about 118s) as its own capacity concern, for example by limiting concurrency or adding generation capacity.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

1 calls, 10067 prompt + 2775 completion tokens, $0.095768; reasoning 28.02s, total 28.24s
