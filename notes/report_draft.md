# Final report draft: methods and related work (started 2026-11-04)

Draft text for the final report. Numbers live in `bio/RESULTS.md` and `leaderboard/RESULTS.md`;
this file should only describe setup. Citations come from the proposal's reference list. Anything
marked [verify] still needs checking against the paper itself.

## 1. Problem setting

An agent works over a horizon of T steps. At each step it observes tool results, keeps some of
them in a working context, and acts. A *context policy* decides what the working context holds:
everything (full), an LLM-written summary (lossy compaction), or a compact index plus read-back
by reference (retrieval, the host harness's design). We ask where each policy breaks as T grows,
and *why*. Final-answer accuracy alone cannot separate a memory failure from a reasoning or
planning failure, so every testbed logs a step-level trace that an audit compares against the
true state.

## 2. Testbeds

Both testbeds follow the mentor's criterion of using existing data and benchmarks rather than
new synthetic worlds.

### 2.1 Closed-loop genetic screen (from BioDiscoveryAgent)

We repurpose the published IFNG screen as a sequential experimental-design task. In each
round, the agent proposes a batch of genes and observes measured scores for accepted tests.
The evaluator defines hits using BDA's provided topmovers set (920 IFNG genes). Its primary
metric is cumulative hit recall, hits found / 920, rather than the fraction of tests that hit.
We scale the task to 100 rounds of 32 proposals and log rejections, retries and short batches.
Repeated tests are rejected; they consume proposal capacity and retry calls, but do not count
as new experiments. Thus repeats do not necessarily reduce the number of accepted experiments.

The agent must retain experiment membership and scores to avoid repeats and guide later
choices. Full-table prompts resupply the complete observed results; summary prompts replace
the table with BDA-style positive and negative summaries above 32 tested genes; retrieval
prompts expose hits and counts plus an experiment-log query. These are local policies, not
implementations of the newly released prototype. The summary policy recomputes summaries
from the full table, rather than recursively summarizing an earlier summary.

Seeded opaque IDs hide gene symbols. This reduces direct use of memorized gene identities;
it does not prove absence of training contamination. Existing runs use cross-screen features
that include the sibling IL2 screen and therefore have a known information-leakage concern.
DepMap co-essentiality is implemented but the real data file is absent locally. Final
comparisons must fix and hash the feature source, report coverage and missing-gene behavior,
and avoid describing anonymization alone as a contamination audit.

The saved Opus full-table run reaches 100 rounds with no repeats and perfect scored recall
at delays 1/2/4/8. This establishes successful behavior at the measured prompt size (~31.5K),
not a context-length failure threshold. At the common 98-round endpoint, summary has 191 hits
versus full's 258, with 3,082 versus 3,136 unique tests. The 26.0% hit difference cannot be
attributed solely to rejected repeats: accepted test counts differ by only 1.7%. Summary
removes both membership and score information, so candidate quality is another possible
mechanism. One seed and leaky features limit this to a pilot observation.

Probes measure closed-book access to scores under each policy; retrieval probes currently
forbid lookup, so low probe scores do not establish failure of external memory. Diagnoses
are sampled self-reports, not proof of the model's internal knowledge. For the prototype
comparison, include both closed-book and tool-enabled probes, report their cost separately,
and measure end-task hits plus accepted tests at matched budgets.

### 2.2 Leaderboard construction (GSM8K pilot)
- **Data.** 54 arXiv papers with GSM8K results. The gold is Papers with Code leaderboard rows,
  checked against paper text (`value_in_paper_text`).
- **Task.** Read each paper (top-2 most relevant chunks) and keep a running leaderboard of
  (model, setting, value, evidence excerpt) across papers. Model names must be resolved across
  papers, via an alias map.
- **Why it stresses context.** State builds up across documents. A look-alike name
  (Phi-2 vs Phi-GSM) or a stale alias can silently corrupt a row.
- **Metrics.**
  - recall against gold: strict (paper + value + name, with identity-conflict checks on size,
    family version and verifier setting), lenient, and value-only;
  - evidence verification (the excerpt must appear in the paper and contain the value);
  - a precision lower bound;
  - the cross-paper name-leak rate.

### 2.3 LOCA-bench
Used as a sanity check, as in the proposal [Zeng, Huang, He 2026]. Its mock MCP servers needed
pinned dependencies, documented in `loca/NOTES.md`.

### 2.4 Prototype comparison on the screen (ours run)

We run the mentor's prototype (`ours run --harness codex`, release 2026.11.09-166c433f) against
plain Codex (`--harness codex-shipped`) with the same model on the IFNG screen, served by our
evaluator as an MCP tool server outside the agent's folder. Settings common to all runs:
- `--context-window 16000`, so compaction fires about every round at 100x32;
- a round gate: each user message carries a one-round token, so the agent takes one turn per
  round (ungated, every agent wrote a script that played all rounds and never compacted);
- no history tool: each result is shown once, so what the agent knows must survive compaction
  in whatever memory it keeps;
- DepMap neighbour lookups (4 genes per round, 8 neighbours each) as the only gene features;
- a probe every 10 rounds: name the 10 tested genes with the largest |score|;
- `--repeat-cost` (later runs): a re-proposed gene uses up its batch slot.

Both arms may write files. The prototype keeps its memory in files it writes; plain Codex
sometimes does the same unprompted. A run that told only plain Codex not to write files was
dropped as an unfair control (course staff, Nov 17).

**Graded hypotheses.** Hits alone do not separate the arms: a no-LLM policy using the same
lookups matches both, because a flat log of tested genes suffices. We therefore add a task
that needs scores, signs and lookup results combined. 15% of genes are held out (seeded, never
testable; proposing one is rejected as `held_out`). After every 10th round and the last, the
agent must submit up to 5 modules, each 3-10 tested genes with a predicted sign, before it may
propose again. A module is graded on the 8 held-out genes that occur most often in its members'
lookup lists; its score is the fraction that are hits of the predicted sign, and the
checkpoint score is the sum over modules divided by 5. Grades are never shown. Grading on
held-out rather than untested genes matters: an agent that tests its hits' neighbours would
otherwise use up the genes it is graded on, and sensible strategies scored below random.
No-LLM references (`bio/hypothesis_baselines.py`): random modules, same-sign hits grouped at
random, and same-sign hits grouped by shared looked-up neighbours with perfect bookkeeping.
An earlier design (each batch must contain untested neighbours of the current top hits) was
dropped because a simple heuristic satisfied it every round.

**Results (100x32, 3 seeds per arm, Nov 20-21).**

| arm | hits | hypothesis score | repeats | top-10 reports | input tokens / run |
|---|---|---|---|---|---|
| prototype | 198* / 215 / 218 (mean 210) | 0.156* / 0.047 / 0.137 (0.113) | 28 / 3 / 3 | 1.0 all | 21-24M |
| plain Codex | 188 / 185 / 189 (mean 187) | 0.102 / 0.192 / 0.082 (0.125) | 161 / 4 / 195 | 0.82 / 1.0 / 0.72 | 11-12M |

\* stopped by the usage limit after round 99 (9 of 10 checkpoints). Offline references at 100x32:
random 0.03, same-sign hits 0.08, nbr_hits 0.16 (0.03-0.29 across seeds).

On hypothesis scores the arms tie: the seed spread is larger than the gap, and both sit between
same-sign hits and nbr_hits. The prototype is ahead on hits in every seed, because plain Codex lost
the tested set in two of three seeds (161 and 195 repeats, each costing a slot), even though it
wrote 121-238 files in each. The one plain Codex seed with an exact record (s1, 4 repeats) had the
best hypothesis score of all six runs. Most runs resubmit the same modules from about round 30,
so the hypothesis score reflects early choices more than long-horizon memory. The prototype used
about twice the tokens, wall time and quota.

## 3. Trace audit

### 3.1 Event schema and labels
Each testbed adapter emits one JSONL trace, using these event types: `observe`, `update`,
`retract`, `alias`, `read`, `use`, `probe`. The labeler replays the trace and labels every
`use` with one of:

| label | meaning |
|---|---|
| correct | used the current true value |
| missed_invalidation | used a fact that had been retracted |
| misattributed | right value, wrong entity (alias resolves elsewhere) |
| stale_value | used a value the key held earlier |
| ignored_known | asked under the same context, the agent reports the current value, yet acted on a different one |
| never_read | the needed item was never read back before use |
| wrong_item | read items for the key, still used a wrong value |

`ignored_known` (added week 3) separates **action failures** from **memory failures**. Week 2
showed that a full-table agent can answer every recall probe correctly and still re-propose
tested genes. The bare audit labeled all of those `stale_value`.

### 3.2 Repeat diagnosis (BioDiscoveryAgent)
After each round, every re-proposed gene is asked back under the exact prompt context that
produced the proposal ("was this tested?"):
- yes → `knew_but_repeated` (audit `ignored_known`);
- no → `forgot` (audit `stale_value`).

Diagnoses are bucketed by the gene's age (rounds since it was tested).

### 3.3 Recall probes
Probes ask about genes tested d rounds earlier under the context the agent will use next. That
gives a recall-decay curve over the horizon, as in the proposal's probe design. Decoy probes
measure false "tested" claims.

## 4. Related work (to expand)
- **Context compaction and folding:** ACON [Kang et al. 2025]; AgentFold [2025]; production
  auto-compaction in Claude Code and Codex.
- **Structured memory:** Zep temporal knowledge graph [Rasmussen et al. 2025]; StructRAG
  [Li et al., ICLR 2025]. StructRAG chooses a structure per task, but for one-shot retrieval.
- **Benchmarks:**
  - LOCA-bench [Zeng et al. 2026], controllable context growth;
  - MemoryAgentBench, where multi-hop conflict resolution reaches at most 7%;
  - WideSearch, 7% success on large table-filling tasks;
  - Context Rot [Hong, Troynikov, Huber 2025], where length and difficulty are confounded.

  Our probes and audit hold per-step difficulty fixed while the delay grows.
- **Science agents:** BioDiscoveryAgent; SHELDON [Joshi, Shethia, Lam]; SLIDERS [Joshi et al.,
  NeurIPS 2026]; DiscoveryWorld; MetaSyn.

## 5. Threats to validity (keep updated)
- Graded hypotheses: modules are scored on at most 8 held-out neighbours, but members' lookup lists
  hold only 2-5 on average and missing ones count as misses, which caps most module scores well
  below 1; agents also freeze their modules early, so later checkpoints add little signal.
- Qwen3-8B runs and one-seed Opus pilots have different capability and sampling controls;
  compare context policies within a fixed model, scaffold and feature source.
- Anonymized-screen features leak from sibling screens; DepMap code exists but real-data
  validation and reruns are pending.
- Papers with Code gold is incomplete, so precision is only a lower bound. One row may be
  pass@k.
- Probes and diagnoses are self-reports. A model may answer a recall question differently from
  how it would act, which is exactly the gap `ignored_known` measures, but it also means probes
  are not ground truth about the model's internal state.
- Prototype comparisons rest on 1-3 seeds per arm, and offline hypothesis scores vary widely
  across seeds (0.03-0.29 for the same strategy at 100x32). Whether plain Codex keeps files is
  itself variable across runs, so the no-memory failure mode appears in some baseline runs and
  not others.
- The prototype uses about 2.4x the baseline's input tokens; comparisons are at matched rounds
  and batch size, not matched cost.
