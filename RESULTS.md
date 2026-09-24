# Results

Everything below was measured on the **development laptop**: Windows 11, an
RTX 5070 with 8 GB, 15 GB RAM, Docker Desktop and local Ollama. Every deploy went
through the **local pipeline stand-in** (`pipeline: local` in every deploy record;
DECISIONS.md D-47..D-51). Nothing here was measured on the Pavilion or with
GitHub Actions. Those numbers must be produced there and reported separately
(PAVILION.md), never merged into these tables.

**No cloud model was evaluated.** This machine had no `DOCTOR_API_KEY`, so the GLM
rows are empty. The ablation instead runs on the larger local model, llama3 (8B),
as a stand-in (D-67). With a key in `.env`, `python -m doctor.eval.run_eval` fills
in the GLM rows with no other change.

The one command that produced every table below is:

```
python -m doctor.eval.run_eval --out doctor/eval/results/final
```

Its outputs are `results.md` (tables), `results.json` (every aggregate) and
`runs.jsonl` (192 scored replays, each with its full report). They are in
`doctor/eval/results/final/`.

---

## How the numbers were produced

1. **Live campaign** (`python -m faults.campaign`).
   - **Faults.** Eight faults were each run twice, with 10-minute cool-downs:
     4 push, 3 environment and 1 data.
   - **Background traffic** ran the whole time: 0.2 chats/s and 0.4 searches/s.
   - **Push faults** were real commits placed among harmless distractor commits
     (D-53). They were shipped with `git push pipeline main`, which runs
     `verify.sh` and then a SHA-tagged `deploy.sh`. All 8 push runs went through
     a real `git push`. None was applied by editing files on the running machine.
   - **Environment and data faults** were applied by the recorded scripts in
     `faults/`.
   - **What woke the doctor.** In every run, only the alert woke it (Alertmanager
     -> alert-sink -> `/incident`). The one exception is when monitoring missed a
     fault: then a user ticket (`/ticket`) woke it (D-78). A push never woke it
     (D-42).
2. **Snapshots.** Each run's evidence snapshot (`bundle.json`), ground truth,
   timeline and live report are in `incidents/recorded/<fault>-r<n>/`.
3. **Evaluation.**
   - `doctor.eval.run_eval` replays those snapshots only, so nothing live is
     touched.
   - Settings are held constant: 16k context, a 6.5k-token prompt budget and a
     2.5k-token answer budget.
   - Each configuration runs three times, with seeds 1000, 1001 and 1002 (D-68).
   - Past incidents for the third evidence arm are the ground-truth resolutions
     of **earlier** recorded incidents only (D-69).

**Runs that were discarded, and why.** They are kept under
`runtime/fault-runs/_*` and not counted:
- one run contaminated by a real memory leak I had introduced (D-71);
- one lost to a race in the doctor's incident store (D-65);
- one early run that picked up an alert caused by a deploy (D-59, D-72);
- two faults that did not reproduce with their first parameters: f2's surge was
  too small and f6's 3 s timeout never tripped (D-74, D-79);
- one data fault undone by compose re-running kb-loader (D-80);
- one typo fault the linter would have caught, so it could never have shipped
  (D-75);
- one typo run where the alert rule was too slow to fire (D-77).

---

## Headline numbers

The tables are split by how the fault was delivered, as specified. **Environment
faults are the real score.** No commit is guilty, so the only right answer is to
blame the environment. The deploy history cannot help there, and it can only
mislead.

### Environment faults: the real score (6 incidents x 3 repeats)

| configuration | acc@1 | class correct | false attribution (blamed a commit) |
|---|---|---|---|
| baseline: blame the most recent deploy | 0.00 | 0.00 | **1.00** |
| llama3, logs only | **0.39** | **1.00** | **0.00** |
| llama3, logs + commits | 0.00 | 0.89 | 0.83 |
| llama3, logs + commits + past incidents | 0.17 | 1.00 | 0.67 |
| llama3.2 (3B), logs + commits + past incidents | 0.28 | 0.67 | 0.22 |

**Findings:**
- **The baseline is always wrong here.** "Blame the most recent deploy" always
  blames a commit, because there is always a deploy in the window.
- **Showing the model the commits makes it blame one.** With logs alone, llama3
  never blamed a commit for an environment fault. With the recent commits added,
  it blamed one in 83% of runs.
- **Past incidents help, but not enough.** They pull false attribution back to
  67%.
- **The smaller model blames commits less** (22%), but it also gets the incident
  class wrong more often.
- **The commit evidence needs better gating.** Commits should only be shown when
  something in the logs or metrics points at a code change. This is the clearest
  improvement the numbers point to.

### Push faults (4 incidents x 2 runs x 3 repeats)

| configuration | acc@1 (commit) | class correct | guilty commit in retrieved top-5 | fix passes the suite | fix passes the acceptance test |
|---|---|---|---|---|---|
| baseline: blame the newest commit of the most recent deploy | 0.00 | 1.00 | - | 0.00 | 0.00 |
| llama3, logs only | 0.00 | 0.54 | 0.00 | 0.25 | 0.25 |
| llama3, logs + commits | 0.21 | 0.38 | 0.62 | 0.25 | 0.25 |
| llama3, logs + commits + past incidents | **0.33** | **0.62** | 0.62 | **0.33** | **0.29** |
| llama3.2, logs + commits + past incidents | 0.04 | 0.42 | 0.62 | 0.08 | 0.08 |

**Findings:**
- **The commit-level baseline scores 0 by construction.** In every push run a
  distractor commit shipped after the guilty one: in the same deploy (r1), or the
  guilty commit went out in an earlier deploy (r2). "Newest commit" therefore
  never named it. The fair comparison is the **deploy-level** baseline: the
  guilty commit was inside the most recent deploy in **0.50** of push runs.
  Rolling back that deploy would have fixed half the push faults. The doctor
  named the exact guilty commit in a third of them.
- **Each evidence arm helps on push faults.** Commits lift acc@1 from 0 to 0.21.
  Past incidents lift it to 0.33.
- **Retrieval sets the ceiling.**
  - The time filter always contained the guilty commit (8/8).
  - The re-ranked top 5 contained it in 5 of 8 incidents, so no model can exceed
    0.62 acc@1 on this set.
  - The memory leak (f4) ranked 7th and 11th. Its diff adds a cache, which reads
    like an optimisation, not like "memory climbing".
  - The f1 r1 ranking was used while fixing the retrieval scorer (D-76), so that
    one incident is not held out.
- **Fixes.**
  - The doctor proposes search/replace edits. They are applied to a copy of the
    patient at the running commit, then the patient's test suite and the fault's
    own acceptance test are run (nothing touches the live system).
  - With the full evidence, llama3 produced a fix that passed the suite in 33% of
    push runs, and one that also passed the fault's acceptance test in 29%.
  - **Reversed edits.** Sometimes the model copied the guilty diff's direction
    instead of reversing it, and the doctor applied the edit the other way round
    (D-81). This happened in 3 of 96 push-fault replays:
    - full evidence (llama3): 1 run, whose fix failed the acceptance test;
    - logs + commits (llama3): 2 runs, which account for 2 of that arm's 6
      acceptance passes.

    So the acceptance rate without this correction is 0.29 with full evidence,
    unchanged, and 0.17 for logs + commits.
  - f5 r2's fix passed the acceptance test in all three repeats, even though the
    model named the wrong commit. The fix is judged by the file it repairs, not
    by the commit it blames.

### Data fault (f7: partial knowledge base; 2 runs x 3 repeats)

| configuration | acc@1 | class correct | false attribution |
|---|---|---|---|
| baseline | 0.00 | 0.00 | 1.00 |
| llama3, logs only | 0.50 | 0.00 | 0.00 |
| llama3, logs + commits | 0.00 | 0.17 | 0.83 |
| llama3, logs + commits + past incidents | 0.00 | 0.00 | 1.00 |
| llama3.2, logs + commits + past incidents | 0.33 | 1.00 | 0.00 |

- Only two incidents, so treat these as anecdotes, not rates.
- The same pattern as for environment faults: once commits are in the prompt,
  llama3 blames one.
- **Monitoring missed f7 both times.** Refusals rose to about 20%, below the 30%
  alert threshold. In both runs a user ticket woke the doctor instead (below).

### Cost and time per diagnosis (replay, local models)

| configuration | reasoning s (mean) | tokens per incident | cost |
|---|---|---|---|
| llama3, logs only | 8.8 | 5.9k | $0 (local) |
| llama3, logs + commits | 11.6 | 11.0k | $0 |
| llama3, logs + commits + past incidents | 11.1 | 11.0k | $0 |
| llama3.2, logs + commits + past incidents | 5.5 | 10.6k | $0 |

The cloud cost column is computed from token counts and per-token prices. It
stays at $0 until a cloud model is run.

---

## Live runs: break -> alert -> report

These are the times from the live campaign: the real alert pipeline and the live
doctor (llama3.2, 4k context, D-63).
- For a push fault, "break" is the moment of `git push`, so break -> alert
  includes verify, build and deploy.
- For f1 r1 that was 58 s of the 103.6 s; the alert fired 45.6 s after the deploy
  finished.

| delivery | runs | break -> alert, median (range) | alert -> report, median (range) |
|---|---|---|---|
| environment | 6 | 78 s (33-114) | 120 s (96-377) |
| push | 8 | 323 s (104-877) | 105 s (96-162) |
| data | 2 | **not alerted**: monitoring missed it, so a ticket was filed | 29 s and 32 s after the ticket |

| incident | delivery | first alert | break -> alert (s) | alert -> report (s) | live doctor's class (truth) |
|---|---|---|---|---|---|
| f3 retrieval down r1 | environment | DownstreamCallFailures | 33.0 | 139.0 | capacity (dependency_failure) |
| f3 retrieval down r2 | environment | ServiceDown | 47.9 | 97.1 | capacity (dependency_failure) |
| f3b retrieval bad address r1 | environment | DownstreamCallFailures | 79.0 | 96.0 | capacity (dependency_failure) |
| f3b retrieval bad address r2 | environment | DownstreamCallFailures | 77.0 | 101.0 | capacity (dependency_failure) |
| f2 capacity r1 | environment | HighLatencyP95 | 113.5 | 376.5 | **capacity** (capacity) |
| f2 capacity r2 | environment | HighLatencyP95 | 108.5 | 246.5 | **capacity** (capacity) |
| f1 embed timeout r1 | push | EmbeddingFallbackActive | 103.6 | 162.4 | data_issue (code_defect) |
| f1 embed timeout r2 | push | EmbeddingFallbackActive | 142.6 | 139.4 | **code_defect** (code_defect) |
| f5 typo r1 | push | HighErrorRate | 620.0 | 96.0 | capacity (code_defect) |
| f5 typo r2 | push | HighErrorRate | 323.0 | 101.0 | **code_defect** (code_defect) |
| f6 tight timeout r1 | push | DownstreamCallFailures | 323.0 | 102.0 | capacity (code_defect) |
| f6 tight timeout r2 | push | DownstreamCallFailures | 321.0 | 105.0 | capacity (code_defect) |
| f4 memory leak r1 | push | MemoryClimbing | 821.2 | 104.8 | capacity (code_defect) |
| f4 memory leak r2 | push | MemoryClimbing | 877.2 | 105.8 | capacity (code_defect) |
| f7 KB missing docs r1 | data | - (ticket) | - | 29.0 after ticket | capacity (data_issue) |
| f7 KB missing docs r2 | data | - (ticket) | - | 32.0 after ticket | code_defect (data_issue) |

**Findings:**
- **Monitoring caught 14 of 16 faults without help.** Every alert described the
  symptom, never a cause. The slow ones are slow for real reasons:
  - A memory leak needs minutes of growth to separate from noise (the 3-minute
    `for`, D-71).
  - Intermittent errors must persist across 4 of 5 minutes, so that a deploy blip
    does not page (D-72, D-77).
- **The live doctor got the class right in only 4 of 16 runs.** It ran on llama3.2
  with a 4k context, a budget forced by sharing one GPU with the patient (D-63).
  It answered "capacity" in 12 of them. This is the main reason the replay
  evaluation exists: the same evidence, replayed with a 16k context, scores well
  above this. A cloud model, which is the intended setup, would not compete with
  the patient for the GPU at all.

---

## What these numbers do not show

- **No cloud model.** The GLM/cloud vs local comparison is unmeasured. llama3 (8B)
  stands in for the primary model.
- **Only the local pipeline.** Every run went through the local bare-repo pipeline
  on one laptop. The GitHub Actions + self-hosted Pavilion path is the same
  scripts (D-48). It has not been run, and its break -> alert times will differ,
  because Ollama is across Wi-Fi there.
- **The sample is small.** There are 16 incidents: 8 push, 6 environment, 2 data.
  The min-max ranges across repeats are in the full tables. With 2-8 incidents per
  class, one incident moves a rate by 0.12-0.5.
- **Retrieval was tuned on f1 r1** (D-76), so that one push incident is not held
  out.
- **One mid-run engineering change.** ChromaDB lost an index segment mid-run, and
  every doctor index moved to exact JSON search. Stored vectors were carried over
  unchanged (D-82). Rows before and after the change use identical embeddings.

---

## Full generated tables

These come from `doctor/eval/results/final/results.md`, unedited. Each cell is the
mean over 3 repeats with the (min-max) range across repeats. The `models:` rows
for llama3 are the same 48 replays as the full-evidence `ablation:` row. They are
reused, not re-run.

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
