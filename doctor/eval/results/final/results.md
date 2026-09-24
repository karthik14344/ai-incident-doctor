### Evaluation 20260924-084116

Incidents: 16; repeats per configuration: 3; ablation model: `ollama:llama3` (local stand-in: no cloud API key was configured).
Cells show the mean over repeats with the (min-max) range across repeats.

Not run: glm:glm-4.6 (no API key configured)

#### environment faults (no guilty commit) - the real score

| | acc@1 | acc@3 | class | false attr. | guilty retrieved | fix verified (suite) | fix correct (acceptance) | reasoning s | tokens | cost $ |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline: blame most recent deploy | 0.00 | 0.00 | 0.00 | 1.00 | - | - | - | - | 0.00 | 0.00 |
| ablation: logs_commits_incidents / ollama:llama3 | 0.17 (0.00-0.33) | 0.17 (0.00-0.33) | 1.00 (1.00-1.00) | 0.67 (0.50-0.83) | - | - | - | 7.99 (6.71-9.40) | 10387.33 (9933.33-11289.50) | 0.00 (0.00-0.00) |
| ablation: logs_commits / ollama:llama3 | 0.00 (0.00-0.00) | 0.00 (0.00-0.00) | 0.89 (0.83-1.00) | 0.83 (0.83-0.83) | - | - | - | 9.48 (6.32-14.90) | 9891.00 (9851.83-9919.17) | 0.00 (0.00-0.00) |
| ablation: logs_only / ollama:llama3 | 0.39 (0.33-0.50) | 0.39 (0.33-0.50) | 1.00 (1.00-1.00) | 0.00 (0.00-0.00) | - | - | - | 4.69 (4.03-5.50) | 4674.28 (4660.83-4693.83) | 0.00 (0.00-0.00) |
| models: logs_commits_incidents / ollama:llama3 | 0.17 (0.00-0.33) | 0.17 (0.00-0.33) | 1.00 (1.00-1.00) | 0.67 (0.50-0.83) | - | - | - | 7.99 (6.71-9.40) | 10387.33 (9933.33-11289.50) | 0.00 (0.00-0.00) |
| models: logs_commits_incidents / ollama:llama3.2 | 0.28 (0.17-0.33) | 0.44 (0.33-0.67) | 0.67 (0.50-0.83) | 0.22 (0.17-0.33) | - | - | - | 4.48 (3.70-5.96) | 9582.00 (8726.67-10013.00) | 0.00 (0.00-0.00) |

#### data faults (guilty knowledge-base version, no commit)

| | acc@1 | acc@3 | class | false attr. | guilty retrieved | fix verified (suite) | fix correct (acceptance) | reasoning s | tokens | cost $ |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline: blame most recent deploy | 0.00 | 0.00 | 0.00 | 1.00 | - | - | - | - | 0.00 | 0.00 |
| ablation: logs_commits_incidents / ollama:llama3 | 0.00 (0.00-0.00) | 0.00 (0.00-0.00) | 0.00 (0.00-0.00) | 1.00 (1.00-1.00) | - | - | - | 13.29 (8.49-20.52) | 8700.00 (7384.50-11318.00) | 0.00 (0.00-0.00) |
| ablation: logs_commits / ollama:llama3 | 0.00 (0.00-0.00) | 0.00 (0.00-0.00) | 0.17 (0.00-0.50) | 0.83 (0.50-1.00) | - | - | - | 14.86 (13.68-16.20) | 10035.17 (7476.00-11485.00) | 0.00 (0.00-0.00) |
| ablation: logs_only / ollama:llama3 | 0.50 (0.50-0.50) | 0.50 (0.50-0.50) | 0.00 (0.00-0.00) | 0.00 (0.00-0.00) | - | - | - | 15.98 (11.81-20.59) | 8241.00 (7374.50-9958.50) | 0.00 (0.00-0.00) |
| models: logs_commits_incidents / ollama:llama3 | 0.00 (0.00-0.00) | 0.00 (0.00-0.00) | 0.00 (0.00-0.00) | 1.00 (1.00-1.00) | - | - | - | 13.29 (8.49-20.52) | 8700.00 (7384.50-11318.00) | 0.00 (0.00-0.00) |
| models: logs_commits_incidents / ollama:llama3.2 | 0.33 (0.00-0.50) | 0.50 (0.50-0.50) | 1.00 (1.00-1.00) | 0.00 (0.00-0.00) | - | - | - | 4.94 (3.98-6.50) | 11186.83 (11158.50-11242.50) | 0.00 (0.00-0.00) |

#### push faults (guilty commit; the deploy record nearly gives it away)

| | acc@1 | acc@3 | class | false attr. | guilty retrieved | fix verified (suite) | fix correct (acceptance) | reasoning s | tokens | cost $ |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline: blame most recent deploy | 0.00 | 0.00 | 1.00 | - | - | 0.00 | 0.00 | - | 0.00 | 0.00 |
| ablation: logs_commits_incidents / ollama:llama3 | 0.33 (0.25-0.38) | 0.33 (0.25-0.38) | 0.62 (0.50-0.75) | - | 0.62 (0.62-0.62) | 0.33 (0.25-0.38) | 0.29 (0.25-0.38) | 12.92 (9.09-18.65) | 11952.42 (11287.38-13218.38) | 0.00 (0.00-0.00) |
| ablation: logs_commits / ollama:llama3 | 0.21 (0.12-0.25) | 0.21 (0.12-0.25) | 0.38 (0.38-0.38) | - | 0.62 (0.62-0.62) | 0.25 (0.25-0.25) | 0.25 (0.25-0.25) | 12.40 (8.77-17.11) | 12003.83 (11347.62-12336.12) | 0.00 (0.00-0.00) |
| ablation: logs_only / ollama:llama3 | 0.00 (0.00-0.00) | 0.00 (0.00-0.00) | 0.54 (0.38-0.62) | - | 0.00 (0.00-0.00) | 0.25 (0.25-0.25) | 0.25 (0.25-0.25) | 9.99 (7.20-13.81) | 6270.46 (6040.50-6719.00) | 0.00 (0.00-0.00) |
| models: logs_commits_incidents / ollama:llama3 | 0.33 (0.25-0.38) | 0.33 (0.25-0.38) | 0.62 (0.50-0.75) | - | 0.62 (0.62-0.62) | 0.33 (0.25-0.38) | 0.29 (0.25-0.38) | 12.92 (9.09-18.65) | 11952.42 (11287.38-13218.38) | 0.00 (0.00-0.00) |
| models: logs_commits_incidents / ollama:llama3.2 | 0.04 (0.00-0.12) | 0.04 (0.00-0.12) | 0.42 (0.38-0.50) | - | 0.62 (0.62-0.62) | 0.08 (0.00-0.12) | 0.08 (0.00-0.12) | 6.42 (4.12-7.86) | 11259.08 (10303.38-12221.50) | 0.00 (0.00-0.00) |

#### all faults together (for reference only - mixes easy and hard cases)

| | acc@1 | acc@3 | class | false attr. | guilty retrieved | fix verified (suite) | fix correct (acceptance) | reasoning s | tokens | cost $ |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline: blame most recent deploy | 0.00 | 0.00 | 0.50 | 1.00 | - | 0.00 | 0.00 | - | 0.00 | 0.00 |
| ablation: logs_commits_incidents / ollama:llama3 | 0.23 (0.19-0.31) | 0.23 (0.19-0.31) | 0.69 (0.62-0.75) | 0.75 (0.62-0.88) | 0.62 (0.62-0.62) | 0.33 (0.25-0.38) | 0.29 (0.25-0.38) | 11.12 (9.62-13.91) | 10958.96 (10327.62-11292.00) | 0.00 (0.00-0.00) |
| ablation: logs_commits / ollama:llama3 | 0.10 (0.06-0.12) | 0.10 (0.06-0.12) | 0.54 (0.50-0.56) | 0.83 (0.75-0.88) | 0.62 (0.62-0.62) | 0.25 (0.25-0.25) | 0.25 (0.25-0.25) | 11.61 (8.80-15.99) | 10965.44 (10321.56-11293.94) | 0.00 (0.00-0.00) |
| ablation: logs_only / ollama:llama3 | 0.21 (0.19-0.25) | 0.21 (0.19-0.25) | 0.65 (0.56-0.69) | 0.00 (0.00-0.00) | 0.00 (0.00-0.00) | 0.25 (0.25-0.25) | 0.25 (0.25-0.25) | 8.75 (7.05-11.54) | 5918.21 (5700.25-6041.50) | 0.00 (0.00-0.00) |
| models: logs_commits_incidents / ollama:llama3 | 0.23 (0.19-0.31) | 0.23 (0.19-0.31) | 0.69 (0.62-0.75) | 0.75 (0.62-0.88) | 0.62 (0.62-0.62) | 0.33 (0.25-0.38) | 0.29 (0.25-0.38) | 11.12 (9.62-13.91) | 10958.96 (10327.62-11292.00) | 0.00 (0.00-0.00) |
| models: logs_commits_incidents / ollama:llama3.2 | 0.17 (0.12-0.25) | 0.25 (0.19-0.31) | 0.58 (0.50-0.69) | 0.17 (0.12-0.25) | 0.62 (0.62-0.62) | 0.08 (0.00-0.12) | 0.08 (0.00-0.12) | 5.51 (3.94-6.98) | 10621.15 (10299.00-11260.44) | 0.00 (0.00-0.00) |

#### Commit retrieval (push faults)

| incident | time-filtered candidates | guilty in time filter | guilty in top-5 after rerank | rank |
|---|---|---|---|---|
| f1_embed_timeout-r1 | 26 | True | True | 1 |
| f5_typo-r1 | 22 | True | True | 4 |
| f6_tight_timeout-r1 | 33 | True | True | 1 |
| f4_memory_leak-r1 | 37 | True | False | 11 |
| f1_embed_timeout-r2 | 32 | True | True | 1 |
| f5_typo-r2 | 37 | True | False | 7 |
| f6_tight_timeout-r2 | 42 | True | True | 2 |
| f4_memory_leak-r2 | 46 | True | False | 7 |

Guilty commit inside the most recent deploy (deploy-level baseline hit rate, push faults): 0.50

#### Live runs: time unnoticed and time to report

| incident | delivery | first alert | expected alert? | break -> alert (s) | alert -> report (s) |
|---|---|---|---|---|---|
| f3_retrieval_down-r1 | environment | DownstreamCallFailures | True | 33.0 | 139.0 |
| f1_embed_timeout-r1 | push | EmbeddingFallbackActive | True | 103.6 | 162.4 |
| f2_capacity-r1 | environment | HighLatencyP95 | True | 113.5 | 376.5 |
| f5_typo-r1 | push | HighErrorRate | True | 620.0 | 96.0 |
| f3b_retrieval_bad_address-r1 | environment | DownstreamCallFailures | True | 79.0 | 96.0 |
| f6_tight_timeout-r1 | push | DownstreamCallFailures | True | 323.0 | 102.0 |
| f7_kb_missing_docs-r1 | data | - | None | - | 29.0 |
| f4_memory_leak-r1 | push | MemoryClimbing | True | 821.2 | 104.8 |
| f2_capacity-r2 | environment | HighLatencyP95 | True | 108.5 | 246.5 |
| f1_embed_timeout-r2 | push | EmbeddingFallbackActive | True | 142.6 | 139.4 |
| f5_typo-r2 | push | HighErrorRate | True | 323.0 | 101.0 |
| f3_retrieval_down-r2 | environment | ServiceDown | True | 47.9 | 97.1 |
| f6_tight_timeout-r2 | push | DownstreamCallFailures | True | 321.0 | 105.0 |
| f7_kb_missing_docs-r2 | data | - | None | - | 32.0 |
| f4_memory_leak-r2 | push | MemoryClimbing | True | 877.2 | 105.8 |
| f3b_retrieval_bad_address-r2 | environment | DownstreamCallFailures | True | 77.0 | 101.0 |
