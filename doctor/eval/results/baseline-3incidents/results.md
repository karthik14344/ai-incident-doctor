### Evaluation 20260923-184705

Incidents: 3; repeats per configuration: 3; ablation model: `ollama:llama3` (local stand-in: no cloud API key was configured).
Cells show the mean over repeats with the (min-max) range across repeats.

#### environment faults (no guilty commit) - the real score

| | acc@1 | acc@3 | class | false attr. | guilty retrieved | fix verified (suite) | fix correct (acceptance) | reasoning s | tokens | cost $ |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline: blame most recent deploy | 0.00 | 0.00 | 0.00 | 1.00 | - | - | - | - | 0.00 | 0.00 |

#### push faults (guilty commit; the deploy record nearly gives it away)

| | acc@1 | acc@3 | class | false attr. | guilty retrieved | fix verified (suite) | fix correct (acceptance) | reasoning s | tokens | cost $ |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline: blame most recent deploy | 0.00 | 0.00 | 1.00 | - | 0.00 | 0.00 | 0.00 | - | 0.00 | 0.00 |

#### all faults together (for reference only - mixes easy and hard cases)

| | acc@1 | acc@3 | class | false attr. | guilty retrieved | fix verified (suite) | fix correct (acceptance) | reasoning s | tokens | cost $ |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline: blame most recent deploy | 0.00 | 0.00 | 0.33 | 1.00 | 0.00 | 0.00 | 0.00 | - | 0.00 | 0.00 |

#### Commit retrieval (push faults)

| incident | time-filtered candidates | guilty in time filter | guilty in top-5 after rerank | rank |
|---|---|---|---|---|
| f1_embed_timeout-r1 | 26 | True | True | 1 |

Guilty commit inside the most recent deploy (deploy-level baseline hit rate, push faults): 1.00

#### Live runs: time unnoticed and time to report

| incident | delivery | first alert | expected alert? | break -> alert (s) | alert -> report (s) |
|---|---|---|---|---|---|
| f3_retrieval_down-r1 | environment | DownstreamCallFailures | True | 33.0 | 139.0 |
| f1_embed_timeout-r1 | push | EmbeddingFallbackActive | True | 103.6 | 162.4 |
| f2_capacity-r1 | environment | HighLatencyP95 | True | 113.5 | 376.5 |
