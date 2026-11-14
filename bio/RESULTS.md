# bio/ — long-horizon BioDiscoveryAgent screen: week-2 results

Date: 2026-11-02. Everything runs locally; nothing from the cloned BDA repo is
imported or executed (only `tools.py` / `analyze.py` were read to mirror semantics).

## Files

| file | what |
|---|---|
| `env.py` | `BioEnv`: load screen, rounds × batch, propose/end_round, reveal only proposed scores, reject+count invalid / repeat (tested in earlier round) / in-batch dup / overflow, cumulative hit ratio (`analyze.py` semantics, essential=1 i.e. no CEG filter), anonymized mode (seeded permutation → `G00000..`), `lookup()` feature tool. |
| `baselines.py` | random, prior (rank by cross-screen profile norm, no feedback), greedy kNN, kNN-UCB. |
| `llm_agent.py` | qwen3:8b agent (local Ollama, thinking off), policies `full` / `summary`, BDA-style retry, recall probes; logs every call to `runs/<run>/calls.jsonl`. |
| `to_audit.py` | run.json → `audit/audit.py` events (+ `audit.summarize`). |
| `report.py` | prints tables from `runs/`. |
| `test_env.py` | pytest, 8 tests (env, anonymization, feature tool, audit mapping). |
| `runs/` | all outputs (baselines json/txt, LLM call logs, audit event files). |

## Exact commands

```bash
cd ~/projects/cs224v-ctx
uv venv bio/.venv && uv pip install --python bio/.venv/bin/python numpy pandas pytest
bio/.venv/bin/python -I -m pytest -q bio/test_env.py            # 8 passed
# long baselines (3 screens x 4 policies x 5 seeds, 100 x 32, anonymized)
bio/.venv/bin/python -I bio/baselines.py --screens IFNG IL2 Carnevale22_Adenosine \
    --rounds 100 --batch 32 --seeds 0 1 2 3 4 --anonymize --out bio/runs/baselines.json
# baselines at the LLM config (8 x 16, 10 seeds)
bio/.venv/bin/python -I bio/baselines.py --screens IFNG --rounds 8 --batch 16 \
    --seeds 0 1 2 3 4 5 6 7 8 9 --anonymize --out bio/runs/baselines_8x16.json
# LLM agent, 1 seed each
bio/.venv/bin/python -I bio/llm_agent.py --policy full    --rounds 8 --batch 16 --screen IFNG --anonymize --out bio/runs/llm_full
bio/.venv/bin/python -I bio/llm_agent.py --policy summary --threshold 32 --rounds 8 --batch 16 --screen IFNG --anonymize --out bio/runs/llm_summary
# v2 with BDA-style candidate menu
for p in full summary; do bio/.venv/bin/python -I bio/llm_agent.py --policy $p --threshold 32 --menu 64 \
    --rounds 6 --batch 16 --screen IFNG --anonymize --out bio/runs/llm_menu_$p; done
bio/.venv/bin/python -I bio/to_audit.py bio/runs/llm_full/run.json   # writes audit_events.jsonl + audit.summarize
bio/.venv/bin/python -I bio/report.py
```

## Feature tool (the learnable signal under anonymization)

`FeatureTool`: each gene's vector = its z-scored (clipped ±10) signed score in
the OTHER single-gene screens: IFNG, IL2, Carnevale22_Adenosine,
Steinhart_crispra_GD2_D22, Sanchez21, Scharenberg22, minus the target.
`Sanchez21_down` is never used (it is the other tail of Sanchez21). Genes
missing from a screen get 0 (Scharenberg covers only 1,061 genes, so its
column is mostly 0). `lookup(id)` returns the 8 nearest IDs by Euclidean
distance between these vectors. No new data was downloaded.

**Leakage caveat. Read this before interpreting any number.** Signed Pearson r
between IFNG and the other screens is IL2 0.32, Scharenberg −0.08, and about 0 for the rest.
IFNG and IL2 come from the same study (Schmidt22, primary T cells) and share 222
hits. So for IFNG and IL2, the "feature tool" is mostly the sibling screen.
The `prior` baseline uses no feedback at all. It just ranks genes by the norm of
the profile, and it is as good as the adaptive learners at R100. For Carnevale,
which has no sibling screen, all policies are close to random. In short, this tool gives a
real but narrow, one-axis signal, and it is not a substitute for a gene
embedding. Local alternatives found: `feasibility/data/biodiscoveryagent/data/schmidt_ifng_d{1,2}.gene_summary.txt`
are the raw replicates of the IFNG screen itself, so they would be target
leakage and are not used. No Achilles/DepMap file is present locally (BDA's
`achilles.py` expects a 300 MB csv that was not downloaded).

## Results

### Non-LLM baselines, 100 rounds × 32, anonymized, n = 5 seeds (mean ± sd of cumulative hit ratio)

| screen | policy | R5 | R10 | R100 | repeats |
|---|---|---|---|---|---|
| IFNG | random | 0.008 ± 0.002 | 0.020 ± 0.004 | 0.167 ± 0.006 | 0 |
| IFNG | prior (no feedback) | 0.068 | 0.120 | 0.402 | 0 |
| IFNG | kNN greedy | 0.046 ± 0.025 | 0.103 ± 0.023 | 0.380 ± 0.005 | 0 |
| IFNG | kNN-UCB | 0.084 ± 0.008 | 0.146 ± 0.009 | 0.399 ± 0.007 | 0 |
| IL2 | random | 0.007 ± 0.004 | 0.016 ± 0.002 | 0.166 ± 0.011 | 0 |
| IL2 | prior | 0.075 | 0.136 | 0.463 | 0 |
| IL2 | kNN greedy | 0.030 ± 0.031 | 0.058 ± 0.037 | 0.466 ± 0.015 | 0 |
| IL2 | kNN-UCB | 0.078 ± 0.012 | 0.182 ± 0.018 | 0.464 ± 0.006 | 0 |
| Carnevale22_Adenosine | random | 0.007 ± 0.002 | 0.015 ± 0.003 | 0.167 ± 0.011 | 0 |
| Carnevale22_Adenosine | prior | 0.016 | 0.033 | 0.208 | 0 |
| Carnevale22_Adenosine | kNN greedy | 0.007 ± 0.003 | 0.017 ± 0.003 | 0.178 ± 0.007 | 0 |
| Carnevale22_Adenosine | kNN-UCB | 0.017 ± 0.003 | 0.029 ± 0.005 | 0.190 ± 0.006 | 0 |

`prior` is deterministic, so its sd is 0. The expected hit ratio for random is 32·R/N, which is 0.174 at R100 for IFNG, so the random rows check out.
For scale (not comparable, because their config differs): paper's R5 numbers at 5 × 128 are random 0.037 and
Claude-3.5-Sonnet 0.095 for IFNG. 5 × 128 is the same number of genes as our R20.
kNN greedy's high variance at R5 and R10 comes from cold start. With a random first batch that
contains no hits, every kNN prediction is about 0 and it exploits noise. UCB fixes this.

### Baselines at the LLM config (IFNG, anonymized, 8 × 16, n = 10 seeds)

| policy | R5 | R8 | repeats |
|---|---|---|---|
| random | 0.004 ± 0.002 | 0.008 ± 0.003 | 0 |
| prior | 0.034 | 0.055 | 0 |
| kNN greedy | 0.023 ± 0.015 | 0.046 ± 0.022 | 0 |
| kNN-UCB | 0.045 ± 0.002 | 0.061 ± 0.004 | 0 |

At most 128 genes are tested, so the expected count for random is about 6.4 hits (0.007).

### LLM agent (qwen3:8b, IFNG anonymized, 8 rounds × 16, **1 seed per policy, small n**)

Run v1: `--retries 1`, no candidate menu. Prompts follow BDA: task, full results table or summaries, then "Solution:".

| metric | full table | BDA-style summary (thr = 32 tested) |
|---|---|---|
| hit ratio R5 / R8 | 0.000 / 0.000 | 0.000 / 0.000 |
| genes actually tested (max 128) | 46 | 48 |
| repeat proposals (already-tested genes) | 176 | 176 |
| in-batch duplicates / invalid | 19 / 0 | 16 / 0 |
| short batches (of 8 rounds) | 6 | 5 |
| audit `use` accuracy (1 − repeat share) | 0.207 (error mix: 100% `stale_value`) | 0.214 (100% `stale_value`) |
| recall probes correct (tested=yes and score within 5e-4) | **9/9 = 1.00** | **3/9 = 0.33** |
| probe acc by delay (rounds) ≤1 / ≤2 / ≤4 | 1.0 / 1.0 / 1.0 (n = 3/3/3) | 0.67 / 0.33 / 0.0 (n = 3/3/3) |
| decoy probes (untested gene, said "tested") | 0/7 | 0/7 |
| LLM calls (propose / retry / probe / summary) | 22 (8/7/7/0) | 32 (8/7/7/10) |
| prompt / completion tokens | 23,934 / 2,120 | 24,320 / 3,477 |
| max prompt tokens | 1,553 | 1,343 |
| wall time (s/call) | 327 s (14.8) | 1,327 s (41.5, shared GPU contention) |

What happened, from reading `runs/llm_*/calls.jsonl`: from round 3 on, qwen3:8b
re-emits **the same 16-ID list** (its round-2 batch) on almost every call, and the one retry
does not get it out. So by round 4 every proposal is a repeat and 0 genes are
accepted. **Both policies collapse identically.** That means these repeats are mostly a
*generation mode collapse* of a small model given opaque IDs, **not** evidence of
forgotten state. The full-table agent answers recall probes perfectly
(9/9) about the very table it ignores when acting. That is a retrieval-vs-use dissociation, which is
interesting but n = 1. The summary agent loses recall as soon as the
table is replaced: 0/3 at delay 4, and it typically answers "tested=no". That is the expected
lossy-compression signature. 0 hits in 46–48 tested genes is consistent with
random (expected about 2.4 hits).

#### Run v2: with a candidate menu (`--menu 64`, 6 rounds × 16, thr = 32, 1 seed, **small n**)

This mirrors BDA's `gene_choices_prompt`: each round the prompt also lists 64 random untested IDs.

| metric | full table | summary |
|---|---|---|
| hit ratio R5 / R6 | 0.0022 / 0.0022 (2 hits) | 0.0022 / 0.0033 (3 hits) |
| genes tested (max 96) | 63 | 95 |
| repeat proposals | 93 | 35 |
| in-batch dup / short batches | 0 / 3 | 14 / 1 |
| audit `use` accuracy | 0.40 | 0.73 |
| probe accuracy (≤1 / ≤2 / ≤4) | 11/11 = 1.00 (1.0 / 1.0 / 1.0) | 3/11 = 0.27 (0.4 / 0.25 / 0.0) |
| probes parsed in the required format | 11/11 | 3/11 (unparsed counted as wrong) |
| decoy false "tested" | 0/5 | 0/5 |
| calls (propose/retry/probe/summary) | 15 (6/4/5/0) | 20 (6/3/5/6) |
| prompt / completion tokens, max prompt | 22,049 / 1,562, 2,280 | 19,997 / 2,277, 1,699 |
| wall (s/call) | 153 s (10.2) | 259 s (13.0) |

The menu removes the round-2 collapse. After that, **the full-table agent repeats
*more* than the summary agent**, 93 vs 35. The full agent copies IDs that appear in its own results
table (the calls log shows its tested batch reappearing verbatim in later "Solution:" lines). The
summary agent cannot copy them because they are no longer in context. So with this small model,
having the state in context *causes* repeats instead of preventing them, while
recall of that state when probed is perfect (11/11). With the lossy summary the agent forgets values
(probe accuracy 0.27, and it answers "not tested" or drifts off-format) but wastes fewer proposals.
**n = 1 per arm.** The direction could flip with another seed. Hit ratios at this
scale (2–3 hits) are indistinguishable from random (expected about 0.05 × 63–95 ≈ 3–5 hits) and
far below kNN-UCB at the same budget (0.061 at R8 ×16).

## Caveats

* **Small n.** The LLM results are 1 seed × 8 rounds × 16 per policy, with 9 scored probes each. None of
  the LLM differences are statistically supported. Treat them as a pipeline check plus
  qualitative observations.
* **The v1 LLM runs are degenerate** (0 hits, so the hit ratio carries no information). Repeats here come from
  mode collapse, not from lost state. To measure forgetting, the agent first has to be
  competent: a candidate menu, more retries (BDA uses 20), a bigger model, or a
  structured "tested set" tool as the treatment.
* **Feature leakage.** For IFNG and IL2 the feature tool is basically the sibling screen (r = 0.32).
  The no-feedback `prior` matches the adaptive learners, so the baselines measure "use the
  sibling screen" more than sequential learning. Carnevale has no informative feature (all
  policies ≈ random + 0.01–0.04).
* **Metric.** Hit ratio is All-genes (analyze.py with essential=1). The N-E (non-essential) variant is not computed.
  `hit_ratio_by_analyze()` independently recomputes the metric from symbols, and the baselines assert equality.
* **Repeat semantics.** In BDA, repeats are silently dropped and re-prompted. We count every
  rejected repeat, including repeats inside retries, so 176 counts proposals, not distinct genes.
* **Audit mapping.** Every proposal is a `use` of `<id>.tested=False`. A repeat is labelled `stale_value`,
  because the truth was updated to True when the gene was tested. Every repeat therefore gets the same
  label, so the error *mix* is uninformative here. Only the rate matters. `read` events are emitted
  (the full table each round), but audit.py's labeler only consults reads when the value is neither
  current nor stale. Probe correctness uses a 5e-4 tolerance, because tables show 4 decimals.
* **Probe delays** are in rounds (bins 1/2/4/8/16). The runs were short, so only delays ≤ 4 occurred. Probes about
  genes are drawn from batches actually accepted, and late rounds accepted 0 genes, so there are few probes.
* **Shared GPU.** Wall-clock and s/call depend on the other agent's load (4–73 s per call
  observed). They are not a property of the policy.
* Runs use `think: false` on Ollama's native `/api/chat` (not the OpenAI endpoint), so that qwen3's
  thinking can be disabled. An early timing probe of mine set `num_ctx=16384`, which may have
  forced one model reload on the shared server. Later calls leave num_ctx at the server default.

## Week 3 (2026-11-04): in progress

### Code changes
- **Repeat diagnosis** (`llm_agent.py --diagnose 1`, default on). After each round, every
  re-proposed gene (up to 12) is asked back under the *same* prompt context the agent proposed
  with: "was this tested?"
  - yes → `knew_but_repeated`;
  - no → `forgot`.

  `to_audit.py` attaches the answer as `belief` on the use event. `audit.py` has a new label,
  `ignored_known` (knew the current value, acted on another), so repeats split into action
  failures (`ignored_known`) vs memory failures (`stale_value`). `diagnosis_stats` reports the
  split by age (rounds since tested).
- **Third memory policy `retrieval`.** The prompt shows only the hits table and counts. Before
  proposing, the agent lists up to 2×batch candidate IDs after `Check:`, and the experiment log
  answers tested/score for each (one extra call per round). This stands in for an external
  memory harness until the host harness is available. Note: recall probes measure *in-context*
  recall, and under `retrieval` non-hits are not in context by design, so probe accuracy for
  that policy is expected to be low. Its repeat rate and diagnosis are the informative numbers.
- **DepMap features** (`--features depmap`, env `DepMapFeatureTool`).
  - Gene profiles come from DepMap Achilles gene effect across cell lines, centered and
    reduced to 50 PCs, with cosine neighbours as in BDA's `gene_search`.
  - The source has no information from any target screen, so it fixes the sibling-screen leak.
  - **Blocked on data:** figshare (`https://figshare.com/ndownloader/files/49843176`, the file
    BDA uses) returns a bot-check page to scripts, so it must be downloaded in a browser and
    saved as `data/depmap/achilles.csv`. Then run `bio/run_depmap_baselines.sh`.
- Tests: `bio/test_env.py` 10 pass (diagnosis mapping and DepMap tool on a synthetic CSV);
  `audit/test_audit.py` 5 pass.

### Running overnight
`bio/run_week3.sh`: IFNG anonymized (week-2 features), 30 rounds × 16, menu 64, policies
full / summary / retrieval × seeds 0–2, two in parallel on local qwen3:8b. Outputs go to
`bio/runs/w3_<policy>_s<seed>/` and logs to `bio/runs/w3_*.log`. At about 4 min per round,
expect roughly 10 h for all 9 runs.

### Overnight results (2026-11-05), preliminary: 5 of 9 runs (superseded by the 9-run table below)

IFNG anonymized, 30 rounds × 16, menu 64, qwen3:8b. Four runs (full s1/s2, retrieval s1/s2)
died on a 900 s request timeout from a runaway generation. Fixed with a 1024-token output cap
and one retry (`NUM_PREDICT` in `llm_agent.py`); they are being rerun (`bio/run_week3_rerun.sh`).
Table from `bio/report_w3.py`:

| run | tested (max 480) | hits | repeat proposals | diagnosed | said "not tested" (forgot) | said "tested" (knew_but_repeated) | probe recall ≤1 / ≤2 / ≤4 / ≤8 |
|---|---|---|---|---|---|---|---|
| full s0 | 125 | 3 | 755 | 300 | 181 | 118 | 8/8, 8/8, 8/8, 8/8 |
| summary s0 | 472 | 22 | 221 | 165 | 69 | 91 | 3/29, 1/28, 0/26, 1/22 |
| summary s1 | 430 | 15 | 263 | 182 | 92 | 84 | 3/29, 2/28, 0/26, 0/22 |
| summary s2 | 452 | 26 | 339 | 276 | 169 | 101 | 2/28, 1/27, 1/25, 1/21 |
| retrieval s0 | 471 | 19 | 31 | 27 | 5 | 21 | 1/29, 0/28, 1/26, 1/22 |

Non-LLM baselines at the same config (`runs/baselines_30x16.json`, 10 seeds), hits: random
24.5 ± 5.3, prior 144, kNN 112.8 ± 26.1, kNN-UCB 167.2 ± 7.7.

Reading (small n: 1 seed for full and retrieval, 3 for summary):
- **No LLM run beats random on hits.** Hit counts (3–26) are at or below random (24.5 ± 5.3).
  This testbed is still measuring memory behaviour, not discovery skill, with an 8B model.
- **The full-table agent collapses on repeats.** It made 755 repeat proposals and only 125 new
  tests, re-emitting earlier batches. Probes look perfect, but there are only 8 per bucket,
  because probes draw from rounds that accepted genes and most of its rounds accepted none.
- **The repeat diagnosis splits repeats into two failure types.**
  - *Full table:* 181 of 300 diagnosed repeats were answered "not tested" even though the
    table with that gene was in the prompt. So for `full`, "forgot" means it failed to find the
    item in context, not that the item was missing. The other 118 were "knew and repeated
    anyway".
  - *Summary:* about half of repeats are knew-but-repeated (91/165, 84/182, 101/276), even
    though the summary rarely contains the gene. That suggests the model also answers "tested"
    from vague familiarity, so self-report is noisy in both directions. Decoy probes never got
    a false "tested" (0/29 in every run), so the "yes" answers are not blanket yes-bias.
  - *Retrieval:* far fewer repeats (31 vs 221–755). In 21 of 27 diagnosed repeats, the agent
    had just been told by its own `Check:` query that the gene was tested, and proposed it
    anyway. That is a clean action failure: correct information was retrieved and then ignored.
- **Probes:** as expected, retrieval and summary have near-zero in-context recall. For
  retrieval that is by design; the useful contrast is retrieval's low repeat count.

### Week-3 results, all 9 runs (2026-11-05)

The reruns used the output cap and retry; no call failed. Per-run table: `bio/.venv/bin/python -I bio/report_w3.py`.

| policy (3 seeds) | new genes tested (max 480) | hits | repeat proposals | diagnosed repeats: said "tested" (knew) / said "not tested" | probe recall, all delays |
|---|---|---|---|---|---|
| full table | 125 / 319 / 137 (mean 194) | 3 / 9 / 4 | 755 / 788 / 859 | 593 / 307 (66% knew; seeds 39%, 68%, 89%) | 116/119 |
| summary | 472 / 430 / 452 (mean 451) | 22 / 15 / 26 | 221 / 263 / 339 | 276 / 330 (46% knew) | 15/308 |
| retrieval | 471 / 460 / 480 (mean 470) | 19 / 19 / 24 | 31 / 127 / 157 | 126 / 105 (55% knew) | 11/313 |
| random (no LLM, 10 seeds) | 480 | 24.5 ± 5.3 | 0 | – | – |

Decoy probes: 0 false "tested" out of 29 in every run.

What holds across seeds:
1. **Showing more state produced the most repeats.** The full-table agent always has the
   answer in its prompt and recalls it when asked (116/119 probes). Yet it re-proposes
   tested genes about 800 times per run and tests only ~40% as many new genes as the other two
   policies. It recalls well but acts badly. This is the opposite of a pure memory story, and
   it matches the leaderboard finding that showing the alias map hurt.
2. **Retrieval repeats least** (mean 105 vs 274 summary vs 801 full) and nearly exhausts the
   budget, while its in-context recall is near zero by design.
3. **Most repeats are not memory loss.** Asked under the same context, the agent says "tested"
   for 46–66% of the genes it just re-proposed, so `ignored_known` is a large share of errors
   under every policy. Seed 0's retrieval split (21/27 knew) did not hold up; pooled it is
   126/235.
4. **No policy beats random on hits** (3–26 vs 24.5 ± 5.3), so none of this is a discovery
   result.

Caveats: 3 seeds; one 8B model; self-reported diagnosis (the knew share varies a lot by seed
for `full`: 39–89%); week-2 features, which leak from the sibling screen (DepMap rerun pending
the download).

## Week 4 pilot: Opus 5.5 via `claude -p` (2026-11-07)

IFNG anonymized, 30 rounds x 16, seed 0, week-2 (leaky) features, threshold 32, menu 64.
Backend: `--backend claude --model claude-opus-5-5`, no tools, empty cwd, no user settings.
Claude CLI has no temperature/seed control, so model sampling is not reproducible.

| policy | hits | unique tested | repeats | recall probes (exact score) | decoy "tested" | repeat diagnosis | calls | input tok | reported $ |
|---|---|---|---|---|---|---|---|---|---|
| full | 61 | 480 | 0 | 105/105 | 0/29 | none needed | 59 | 204K | 1.86 |
| summary | 24 | 362 | 467 (+75 in-batch dup) | 7/105 | 0/29 | 306/306 forgot | 167 | 418K | 5.19 |
| retrieval | 31 | 480 | 0 | 7/105 | 0/29 | none needed | 88 | 138K | 1.58 |

Non-LLM baselines at 30x16 (same features): random 24.5, kNN 112.8, UCB 167.2.

Notes:
- Summary run first crashed at round 22 (Claude Code auto-update removed the binary mid-run;
  partial run kept as `runs/w4_opus_summary_s0_crashed`, 121 calls, $3.70 reported). Backend now
  retries 4x with 30/60/90 s backoff on OSError; the rerun hit the same thing once at r20 and recovered.
- Summary: repeats start at round 4, right after the table is replaced by BDA's summaries. Every
  diagnosed repeat was "forgot", at every age including 1 round: the summary does not list tested
  genes, so this is information removed by the policy, not decay over the horizon.
- Retrieval: the agent issued `Check:` in 29/30 rounds and never repeated. Probes (no lookup allowed)
  recall only 7/105: memory is in the log, not the prompt. Fewer hits than full (31 vs 61), plausibly
  because non-hit scores are not in view to steer by (not tested).
- Qwen3-8B week-3 contrast: full-table Qwen made ~800 repeats with 66% "knew"; Opus makes 0. The
  week-3 `ignored_known` failures were mostly model weakness at this context size (~6K tokens).
- Total reported usage for the pilot: $12.33 (incl. crashed run), against the Max plan limits.

### 100 x 32 full table, Opus 5.5, seed 0 (2026-11-07)

`runs/w4_opus_full_100x32_s0`: 266 hits (ratio 0.289 of 920), 3200/3200 unique, 0 repeats, 0 invalid.
Recall probes 385/385 exact (delays 1/2/4/8 all 100%, no drop across the run), decoys 0/99.
Final propose prompt 31.5K tokens (about 10 tok/gene, below the 15 assumed, so not 48K).
199 calls, 3.25M input / 61K output tokens, $27.23 reported, 19 min, 0 failed calls.

Baselines at 100x32 (`runs/baselines_100x32.json`, 5 seeds, same leaky features), hit ratio R100:
random 0.167, prior 0.402, kNN 0.380, UCB 0.399. Opus full table 0.289.

So at ~32K tokens the full table shows no context failure on this task: no repeats and no recall
decay. The context-pressure regime has not been reached.

### 100 x 32 summary, Opus 5.5, seed 0 (2026-11-07), stopped by $30 cap at round 99

`runs/w4_opus_summary_100x32_s0` (calls.jsonl + log only; killed before run.json was written, so
probe scores and repeat diagnoses are not graded yet). Compared over the 98 complete rounds:

| | full | summary |
|---|---|---|
| hits @30 / @50 / @98 | 47 / 104 / 258 | 56 / 95 / 191 |
| unique genes tested | 3136 | 3082 |
| repeats (rejected, then retried) | 0 | 1513 |
| in-batch duplicates | 0 | 981 |
| rounds short of 32 after retry | 0 | 5 |
| largest propose prompt | ~31K | 3.6K |
| reported $ | ~26.5 | 30.08 (582 calls, incl. 96 diagnose calls) |

Summary is ahead early (it re-reads its own summaries of hits), falls behind after ~round 40, and
ends 26% below full. It does not save usage here: summarizing, retries and diagnosis calls cost
more than the full table's long prompts. To do: write run.json incrementally so a stopped run keeps
graded probes and diagnoses.


### Local recovery audit (2026-11-09; no new model calls)

`replay_calls.py` replayed all 582 saved summary calls with exact prompt/kind/round equality,
using the full run's matched configuration with policy overridden to summary. Separate outputs:
`runs/w4_opus_summary_100x32_s0_recovered/{run,audit}.json`. All 98 rounds recovered:
191 hits, 3,082 accepted tests, 1,513 repeat proposals, 981 batch duplicates, five short batches.
Recall: **4/381** exact-score probes; 349/381 parsed, unparsed responses counted incorrect.
Decoys: 0/98 false tested claims. Diagnoses: **1,000 forgot, 1 knew_but_repeated**, sampled
with a cap of 12 genes per round; these are not diagnoses of all 1,513 repeat occurrences.
The full run has 266 hits at round 100; **258 is its round-98 count**, used for the 26.0% gap.
Accepted tests differ by only 54 (1.7%); repeats alone do not explain the hit gap.

`llm_agent.py` now writes atomic partial snapshots after completed rounds, diagnoses and probes,
and refuses to reuse an existing result directory. This is checkpoint preservation, not resume.

## Week 5: prototype (`ours`) on BDA (2026-11-13)

Setup: `ours` release 2026.11.09-166c433f (pinned), gpt-6.1-terra, `--lane subscription`,
`--context-window 16000` (effective 15,200). Prototype = `--harness codex` (structured memory in
`data_structures/`); baseline = `--harness codex-shipped` (plain Codex 0.159). Task tools via
`bio/bda_mcp.py` relaying to `bio/evaluator.py`; gene IDs scrambled with a secret per-run seed;
week-2 (leaky) features; IFNG. Launcher `ours/run_bda.sh`, audit `ours/audit_trace.py`,
table `ours/compare.py`.

### Ungated pilot, 30x16: invalid as a context test

| arm | hits | repeats | model requests | peak input tokens | compactions |
|---|---|---|---|---|---|
| prototype | 11 | 0 | 8 | 13.4K | 0 |
| baseline | 116 | 0 | 11 | 13.6K | 0 |

Both agents wrote a JavaScript (code mode) loop in their first turns that ran the rounds by itself,
so the model never saw most rounds, context never grew, and compaction never fired. The hit gap
is the gap between two one-shot heuristics: the baseline ranks neighbors of strong genes by the
*sum* of squared |score| (genes near several strong genes win); the prototype ranks by the *max*
and spends lookups on any high-|score| gene, not just hits. The prototype's 11 is below random
(24.5 at 30x16). One seed; this says nothing about memory.

**Design fix: one model turn per round.** `run_bda.sh` (GATE=1, default) draws a random token per
round and sends round k's token in round k's user message (`--follow-up`). The evaluator holds only
the tokens' sha256 hashes and refuses `propose` for a round until its token arrives, so a script from
an earlier turn cannot run later rounds. Codex restarts MCP servers on every follow-up, so state
lives in one evaluator process per run and `bda_mcp.py --url` relays to it. Gated smoke test (3x4,
prototype): one round per turn, 21 requests, compaction once (13.1K -> 9.4K), 225K input tokens.

Isolation caveat: the macOS Codex sandbox can read the whole disk (writes only to the workspace),
and future round tokens are on the `ours` command line. The secret seed makes the screen files
useless without the evaluator's memory; the audit flags any shell or JS command touching project
paths or listing processes. 0 flags so far.

### Gated pilot, 30x16, 16K window (one model turn per round)

Same task seed scheme (secret per-run seed), week-2 features, gpt-6.1-terra, release 166c433f.
Arms ran one after the other (the baseline's first launch failed on a launcher bug before any
model call).

| arm | hits | repeats | compactions (avg tokens before -> after) | model requests | input tokens (cached) | wall | state kept in |
|---|---|---|---|---|---|---|---|
| prototype (`codex`) | 28 | 0 | 28 (14.9K -> 9.7K) | 268 | 3.25M (91%) | 24 min | `data_structures/` files: measurements, neighbors, strategy (432 references in commands) |
| baseline (`codex-shipped`) | 54 | 0 | 23 (12.9K -> 8.5K) | 167 | 1.79M | 11 min | re-reading the evaluator's `history` tool (41 calls); empty workspace |

0 isolation flags in either arm. Weekly Codex quota 6% -> 9% for both arms.

Reading:
- The gate works: context now accumulates and both harnesses compact every ~1-1.5 rounds.
- Neither arm forgets which genes it tested, but for a different reason each: the prototype keeps
  its own tables, the baseline just asks the evaluator. **`history` is a perfect external memory,
  so this task cannot show a memory failure in the baseline.** Next design change: remove `history`
  (or limit it to the last round) so state must survive compaction in the agent's own memory.
- Hits: both are near random (24.5) and far below UCB (167) at this size; the baseline's hit rate
  rises after round 20. One seed each, so the 28 vs 54 gap is not evidence about memory.
- The prototype spends 1.8x the tokens and 2.3x the time, mostly maintaining its files.

### Karen's paired runs (Nov 10-13, ungated, 48K window, DepMap, restricted sandbox)

| pair | prototype | baseline | diff | model requests (proto/base) | compactions |
|---|---|---|---|---|---|
| 30x16 seed 0 (corrected) | 83 | 53 | +30 | 12 / 12 | 0 |
| 100x32 seed 0 | 292 | 313 | -21 | 21 / 10 | 0 |
| 100x32 seed 1 | 287 | 314 | -27 | 16 / 12 | 0 |
| 100x32 seed 2 | 217 | 254 | -37 | 14 / 17 | 0 |

Each finished in ~2-3 minutes with 10-21 model requests and no compaction: the agents scripted the
rounds in code. These compare one-shot programs, not context handling. Her guarded stack
(`bio/run_paired_pilot.py`) now has `--gate` for the next pairs.
