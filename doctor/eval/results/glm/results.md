### Evaluation 20260924-141418

Incidents: 16; repeats per configuration: 3; ablation model: `glm:glm-4.5-flash` (cloud).
Cells show the mean over repeats with the (min-max) range across repeats.

#### environment faults (no guilty commit) - the real score

| | acc@1 | acc@3 | class | false attr. | guilty retrieved | fix verified (suite) | fix correct (acceptance) | reasoning s | tokens | cost $ |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline: blame most recent deploy | 0.00 | 0.00 | 0.00 | 1.00 | - | - | - | - | 0.00 | 0.00 |
| ablation: logs_commits_incidents / glm:glm-4.5-flash | 0.56 (0.50-0.67) | 0.89 (0.83-1.00) | 0.83 (0.83-0.83) | 0.11 (0.00-0.17) | - | - | - | 47.32 (41.29-50.93) | 14524.50 (13592.17-15062.00) | 0.01 (0.01-0.01) |
| ablation: logs_commits / glm:glm-4.5-flash | 0.44 (0.33-0.50) | 0.72 (0.67-0.83) | 0.33 (0.33-0.33) | 0.17 (0.17-0.17) | - | - | - | 45.81 (42.50-49.11) | 13977.50 (13495.83-14923.83) | 0.01 (0.01-0.01) |
| ablation: logs_only / glm:glm-4.5-flash | 0.44 (0.33-0.50) | 0.72 (0.67-0.83) | 0.78 (0.67-0.83) | 0.00 (0.00-0.00) | - | - | - | 44.71 (41.35-49.85) | 9642.94 (9002.33-9983.50) | 0.01 (0.01-0.01) |
| models: logs_commits_incidents / glm:glm-4.5-flash | 0.56 (0.50-0.67) | 0.89 (0.83-1.00) | 0.83 (0.83-0.83) | 0.11 (0.00-0.17) | - | - | - | 47.32 (41.29-50.93) | 14524.50 (13592.17-15062.00) | 0.01 (0.01-0.01) |
| models: logs_commits_incidents / ollama:llama3 | 0.17 (0.00-0.33) | 0.17 (0.00-0.33) | 1.00 (1.00-1.00) | 0.67 (0.50-0.83) | - | - | - | 7.99 (6.71-9.40) | 10387.33 (9933.33-11289.50) | 0.00 (0.00-0.00) |
| models: logs_commits_incidents / ollama:llama3.2 | 0.28 (0.17-0.33) | 0.44 (0.33-0.67) | 0.67 (0.50-0.83) | 0.22 (0.17-0.33) | - | - | - | 4.48 (3.70-5.96) | 9582.00 (8726.67-10013.00) | 0.00 (0.00-0.00) |

#### data faults (guilty knowledge-base version, no commit)

| | acc@1 | acc@3 | class | false attr. | guilty retrieved | fix verified (suite) | fix correct (acceptance) | reasoning s | tokens | cost $ |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline: blame most recent deploy | 0.00 | 0.00 | 0.00 | 1.00 | - | - | - | - | 0.00 | 0.00 |
| ablation: logs_commits_incidents / glm:glm-4.5-flash | 0.50 (0.50-0.50) | 1.00 (1.00-1.00) | 0.00 (0.00-0.00) | 0.50 (0.50-0.50) | - | - | - | 54.16 (40.62-79.30) | 12229.67 (7949.50-16552.50) | 0.01 (0.01-0.01) |
| ablation: logs_commits / glm:glm-4.5-flash | 0.17 (0.00-0.50) | 0.83 (0.50-1.00) | 0.00 (0.00-0.00) | 0.67 (0.50-1.00) | - | - | - | 63.81 (51.73-85.92) | 12355.50 (8179.50-16548.50) | 0.01 (0.01-0.01) |
| ablation: logs_only / glm:glm-4.5-flash | 0.67 (0.50-1.00) | 0.67 (0.50-1.00) | 0.00 (0.00-0.00) | 0.00 (0.00-0.00) | - | - | - | 121.61 (98.56-156.21) | 7083.67 (5259.00-10700.50) | 0.01 (0.00-0.01) |
| models: logs_commits_incidents / glm:glm-4.5-flash | 0.50 (0.50-0.50) | 1.00 (1.00-1.00) | 0.00 (0.00-0.00) | 0.50 (0.50-0.50) | - | - | - | 54.16 (40.62-79.30) | 12229.67 (7949.50-16552.50) | 0.01 (0.01-0.01) |
| models: logs_commits_incidents / ollama:llama3 | 0.00 (0.00-0.00) | 0.00 (0.00-0.00) | 0.00 (0.00-0.00) | 1.00 (1.00-1.00) | - | - | - | 13.29 (8.49-20.52) | 8700.00 (7384.50-11318.00) | 0.00 (0.00-0.00) |
| models: logs_commits_incidents / ollama:llama3.2 | 0.33 (0.00-0.50) | 0.50 (0.50-0.50) | 1.00 (1.00-1.00) | 0.00 (0.00-0.00) | - | - | - | 4.94 (3.98-6.50) | 11186.83 (11158.50-11242.50) | 0.00 (0.00-0.00) |

#### push faults (guilty commit; the deploy record nearly gives it away)

| | acc@1 | acc@3 | class | false attr. | guilty retrieved | fix verified (suite) | fix correct (acceptance) | reasoning s | tokens | cost $ |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline: blame most recent deploy | 0.00 | 0.00 | 1.00 | - | - | 0.00 | 0.00 | - | 0.00 | 0.00 |
| ablation: logs_commits_incidents / glm:glm-4.5-flash | 0.38 (0.38-0.38) | 0.38 (0.38-0.38) | 1.00 (1.00-1.00) | - | 0.62 (0.62-0.62) | 0.75 (0.75-0.75) | 0.71 (0.62-0.75) | 60.30 (56.74-66.64) | 14542.08 (14517.50-14563.38) | 0.01 (0.01-0.01) |
| ablation: logs_commits / glm:glm-4.5-flash | 0.38 (0.38-0.38) | 0.38 (0.38-0.38) | 1.00 (1.00-1.00) | - | 0.62 (0.62-0.62) | 0.71 (0.62-0.75) | 0.71 (0.62-0.75) | 58.91 (55.04-64.75) | 14565.12 (14495.38-14659.38) | 0.01 (0.01-0.01) |
| ablation: logs_only / glm:glm-4.5-flash | 0.00 (0.00-0.00) | 0.00 (0.00-0.00) | 0.46 (0.38-0.50) | - | 0.00 (0.00-0.00) | 0.25 (0.25-0.25) | 0.25 (0.25-0.25) | 55.75 (50.44-60.51) | 10536.96 (10108.12-10778.38) | 0.01 (0.01-0.01) |
| models: logs_commits_incidents / glm:glm-4.5-flash | 0.38 (0.38-0.38) | 0.38 (0.38-0.38) | 1.00 (1.00-1.00) | - | 0.62 (0.62-0.62) | 0.75 (0.75-0.75) | 0.71 (0.62-0.75) | 60.30 (56.74-66.64) | 14542.08 (14517.50-14563.38) | 0.01 (0.01-0.01) |
| models: logs_commits_incidents / ollama:llama3 | 0.33 (0.25-0.38) | 0.33 (0.25-0.38) | 0.62 (0.50-0.75) | - | 0.62 (0.62-0.62) | 0.33 (0.25-0.38) | 0.29 (0.25-0.38) | 12.92 (9.09-18.65) | 11952.42 (11287.38-13218.38) | 0.00 (0.00-0.00) |
| models: logs_commits_incidents / ollama:llama3.2 | 0.04 (0.00-0.12) | 0.04 (0.00-0.12) | 0.42 (0.38-0.50) | - | 0.62 (0.62-0.62) | 0.08 (0.00-0.12) | 0.08 (0.00-0.12) | 6.42 (4.12-7.86) | 11259.08 (10303.38-12221.50) | 0.00 (0.00-0.00) |

#### all faults together (for reference only - mixes easy and hard cases)

| | acc@1 | acc@3 | class | false attr. | guilty retrieved | fix verified (suite) | fix correct (acceptance) | reasoning s | tokens | cost $ |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline: blame most recent deploy | 0.00 | 0.00 | 0.50 | 1.00 | - | 0.00 | 0.00 | - | 0.00 | 0.00 |
| ablation: logs_commits_incidents / glm:glm-4.5-flash | 0.46 (0.44-0.50) | 0.65 (0.62-0.69) | 0.81 (0.81-0.81) | 0.21 (0.12-0.25) | 0.62 (0.62-0.62) | 0.75 (0.75-0.75) | 0.71 (0.62-0.75) | 54.67 (49.57-57.50) | 14246.44 (13893.12-14922.56) | 0.01 (0.01-0.01) |
| ablation: logs_commits / glm:glm-4.5-flash | 0.38 (0.38-0.38) | 0.56 (0.50-0.62) | 0.62 (0.62-0.62) | 0.29 (0.25-0.38) | 0.62 (0.62-0.62) | 0.71 (0.62-0.75) | 0.71 (0.62-0.75) | 54.62 (52.39-57.26) | 14068.56 (13331.06-14994.69) | 0.01 (0.01-0.01) |
| ablation: logs_only / glm:glm-4.5-flash | 0.25 (0.19-0.31) | 0.35 (0.31-0.44) | 0.52 (0.44-0.56) | 0.00 (0.00-0.00) | 0.00 (0.00-0.00) | 0.25 (0.25-0.25) | 0.25 (0.25-0.25) | 59.84 (55.97-63.44) | 9770.04 (9399.50-10455.38) | 0.01 (0.01-0.01) |
| models: logs_commits_incidents / glm:glm-4.5-flash | 0.46 (0.44-0.50) | 0.65 (0.62-0.69) | 0.81 (0.81-0.81) | 0.21 (0.12-0.25) | 0.62 (0.62-0.62) | 0.75 (0.75-0.75) | 0.71 (0.62-0.75) | 54.67 (49.57-57.50) | 14246.44 (13893.12-14922.56) | 0.01 (0.01-0.01) |
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
