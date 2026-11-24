## Live runs: the doctor on two models

| Model | Runs | Right class | Right cause @1 | Right cause @3 | Blamed a commit when none was guilty | Fix verified (push faults) | Median s alert->report | Median evidence tokens | Doctor cost $ |
|---|---|---|---|---|---|---|---|---|---|
| Llama 3.2 (laptop, Sept) | 16 | 4/16 (25%) | 5/16 (31%) | 5/16 (31%) | 0/8 (0%) | 0/8 (0%) | 103 | 2985 | 0.00 |
| Claude Opus 5.5 (GCP VM, Nov) | 16 | 15/16 (94%) | 14/16 (88%) | 14/16 (88%) | 0/8 (0%) | 6/8 (75%) | 105 | 6229 | 2.13 |

### Right cause @1 by fault type

| Model | Environment | Data | Push |
|---|---|---|---|
| Llama 3.2 (laptop, Sept) | 2/6 (33%) | 2/2 (100%) | 1/8 (12%) |
| Claude Opus 5.5 (GCP VM, Nov) | 6/6 (100%) | 2/2 (100%) | 6/8 (75%) |

### Run by run

| Fault run | Type | Llama 3.2 class / cause@1 | Claude Opus 5.5 class / cause@1 |
|---|---|---|---|
| f1_embed_timeout-r1 | push | data_issue / no | data_issue / no |
| f1_embed_timeout-r2 | push | code_defect / yes | code_defect / no |
| f2_capacity-r1 | environment | capacity / no | capacity / yes |
| f2_capacity-r2 | environment | capacity / no | capacity / yes |
| f3_retrieval_down-r1 | environment | capacity / no | dependency_failure / yes |
| f3_retrieval_down-r2 | environment | capacity / yes | dependency_failure / yes |
| f3b_retrieval_bad_address-r1 | environment | capacity / yes | dependency_failure / yes |
| f3b_retrieval_bad_address-r2 | environment | capacity / no | dependency_failure / yes |
| f4_memory_leak-r1 | push | capacity / no | code_defect / yes |
| f4_memory_leak-r2 | push | capacity / no | code_defect / yes |
| f5_typo-r1 | push | capacity / no | code_defect / yes |
| f5_typo-r2 | push | code_defect / no | code_defect / yes |
| f6_tight_timeout-r1 | push | capacity / no | code_defect / yes |
| f6_tight_timeout-r2 | push | capacity / no | code_defect / yes |
| f7_kb_missing_docs-r1 | data | capacity / yes | data_issue / yes |
| f7_kb_missing_docs-r2 | data | code_defect / yes | data_issue / yes |
