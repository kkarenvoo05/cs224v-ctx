# Harder task design (option a: agent-written files allowed)

DRAFT, Nov 15. Nothing built yet; for Karen and Katherine to agree on before any code.

## Why the current task saturates

On DepMap 100x32 with history off, both arms kept an exact record on disk (one line or one file per
round) and scored 100/100 on the top-10 report. The task only ever asks for two things a flat log
answers by lookup: "was this gene tested?" and "which tested genes scored highest?". A memory test
that a `grep` or `sort` passes measures whether the agent thinks to keep a log, not how the harness
manages context.

Also, an information-matched heuristic (`nbr` in `bio/baselines.py`: look up neighbours of the best
genes, test them) gets 221 hits (5 seeds), the same as the two LLM arms (229, 212). So the hit count
doesn't reward anything a log-keeping script couldn't do either.

## What would make files insufficient

The record must be needed in a form that has to be *built and kept up to date*, not just stored, and
the cheap way to rebuild it from the raw log must cost more than the window allows.

1. **Evolving hypotheses, scored.** Every K rounds the agent submits a short model of the screen:
   e.g. 5 "modules" (groups of tested genes it believes act together, with a predicted sign). Scoring:
   held-out genes from those modules are tested by the evaluator and the prediction is graded. A flat
   log has the data, but the hypothesis is reasoning over hundreds of results; a harness that keeps
   structured state (clusters, neighbour graph) should carry it between compactions, and a raw-log
   agent has to re-derive it each time.
2. **Delayed, conditional rewards.** Some genes are "assays": testing one reveals nothing at first,
   but a hit is credited only if a *specific related gene* (named in the reveal) is tested within the
   next N rounds. The agent has to carry a set of open obligations across compactions; files can hold
   it, but only if the agent keeps them current (stale or missing entries cost hits).
3. **Batch constraints that depend on many past scores.** Each round's batch must include, say, at
   least 8 neighbours of the agent's current top-20 hits (by |score|) and no gene within distance d of
   a tested null. The evaluator checks it. The top-20 and the null set change every round, so the
   agent has to keep a derived structure (neighbour lists of a moving top set), not just the log.
4. **Budgeted recall instead of free lookup.** Keep files, but charge the read: each exec read of a
   workspace file costs model tokens anyway; at 16K the window can't hold a 3,200-row log, so the agent
   must summarise. Measure what each arm reads per round and whether its decisions use it (from the
   trace). This turns "has a log" into "uses a compact, current summary".

## Recommendation

Start with 3 (batch constraints): it reuses the evaluator, needs one new check in `propose`, is
scored automatically (violations + hits), and directly exercises the prototype's structured state
(neighbour lists of a moving top set) versus re-deriving it from a flat log each round. 1 is the most
interesting scientifically but needs a grading design. Pilot at 30x16, then 100x32, with the
`nbr` baseline extended to satisfy the constraint as the reference.

## Open questions

- Decided Nov 17 (Monica, via Heyu): option (a). No comparison against Codex without file memory.
- Do constraint violations reject the gene (lost slot) or the whole batch?

## Result of building option 3 (Nov 18): it does not make the task harder

Built: `--constraint-top K --constraint-min M --constraint-from R` in `bio/evaluator.py` / `env.py`
(tests in `test_evaluator.py`), `nbr_c` in `bio/baselines.py`, offline replay `bio/replay_constraint.py`.
Checked before spending quota:
- Plain `nbr` (no constraint logic) meets K=20, M=8 in every round at 100x32 and K=10, M=4 at 30x16
  (5 seeds each): testing neighbours of your best genes is the good strategy anyway.
- Replaying the six DepMap agent runs under K=20, M=8: the constraint is vacuous in ~70% of rounds
  (the top-20's neighbourhoods are already tested, so the requirement drops to 0), and where it is
  live the agents already meet it. Violations: prototype 0 / 1 / 0, plain Codex with files 0,
  no-files 1 and 27.
- General point: with code execution and files, any deterministic function of past observations can
  be recomputed by a short script from a raw log. A bookkeeping constraint can't make a flat log
  insufficient; the agent only fails if it didn't log the inputs. Harder tasks need judgment over past
  results (option 1, graded hypotheses) or observations that aren't structured enough to script.

## Option 1 built (Nov 18): graded hypotheses

- `evaluator.py --hypothesis-every K --reserve F` (`HYPOTHESIS_EVERY=K` in `ours/run_bda.sh`, RESERVE
  defaults to 0.15 when on). A seeded F of genes is held out: lookups still list them, propose rejects
  them (`held_out`). After every K-th and the last round the agent must call `hypothesis` with up to 5
  modules (3-10 tested genes + a sign) before proposing again. `grade_module`: the 8 held-out genes
  most often in the members' lookup lists; score = fraction that are hits with that sign; missing
  modules and short neighbourhoods count as 0. Not revealed to the agent.
- Why a reserve: grading on *untested* neighbours penalised good play. An agent that tests its hits'
  neighbourhoods leaves only leftovers, so sensible modules scored below random (100x32: random 0.027,
  same-sign hits 0.009, neighbour-grouped hits 0.001).
- Offline reference with the reserve (`bio/hypothesis_baselines.py`, nbr picks, 5 seeds):

  | strategy | 30x16 | 100x32 |
  |---|---|---|
  | random modules | 0.015 | 0.032 |
  | same-sign hits, random groups | 0.040 | 0.083 |
  | same-sign hits grouped by shared lookup neighbours (perfect bookkeeping) | 0.030 | 0.162 (0.03-0.29) |

  Ordered and far from the 1.0 ceiling at 100x32; at 30x16 there are too few hits to group, so the
  30x16 pilot only checks mechanics (tool use, compliance, held-out rejections). Seed spread is large,
  so final comparisons need 3+ seeds and should report per-checkpoint scores.
- Tests: `test_hypothesis_graded_on_untested_neighbours`, `test_reserve_held_out_and_used_for_grading`,
  `test_mcp_lists_hypothesis_only_when_on`.

### Pilot (Nov 19): 30x16, one seed, quota 80% -> 84%

| arm | hits | hypothesis score | modules per checkpoint | member precision | held-out proposals | repeats | workspace files |
|---|---|---|---|---|---|---|---|
| prototype (hyp_ours_30x16) | 48 | 0.050 | 1, 2, 3 | 1.0 in all 6 | 94 | 0 | 8 |
| plain Codex, files allowed (hyp_base_30x16) | 35 | 0.008 | 5, 5, 1 | 0.33-1.0 (mostly 0.33-0.6) | 88 | 17 | 0 |

Offline at 30x16: random 0.015, hits 0.040, nbr_hits 0.030. Mechanics work: both arms called the
hypothesis tool at all 3 checkpoints, held-out genes were rejected, grades were not revealed.
Plain Codex wrote no files (unlike dm_base_s0), lost track of tested genes (round 21 batch fully
rejected: repeats plus held-out), padded batches with patterned IDs (G00001, G01001, ...), and put
non-hits in modules. The prototype under-submitted (scores divide by 5 modules). One seed only.

### 100x32, 3 seeds per arm (Nov 20-21)

Full table in `bio/RESULTS.md`. Hypothesis score: prototype 0.156* / 0.047 / 0.137 (mean 0.113),
plain Codex 0.102 / 0.192 / 0.082 (mean 0.125): no difference. Hits: prototype 198* / 215 / 218,
plain Codex 188 / 185 / 189; plain Codex repeated 161 and 195 genes in s0 and s2 despite writing
120+ files. (\* s0 stopped at round 99 on the usage limit.) Both arms submitted 5 modules every
checkpoint (the prompt fix worked); member precision 0.82-0.97.

What this says about the task:
- The score barely moves after about round 30: most runs resubmit identical modules, so it tests
  early grouping, not memory over 100 rounds.
- Members' neighbour lists contain 2-5 held-out genes on average (of 8 graded), so the ceiling
  per module is often 0.25-0.6. Grading on the held-out genes actually present (or a fixed
  per-module set drawn from a larger reserve) would cut this noise.
- Possible fixes: require modules to change (e.g. grade only modules containing a gene tested
  since the last checkpoint), or grade at the end only on modules built from late-tested genes.
