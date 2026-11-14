# Progress report draft (due Mon Nov 16): next steps and benchmark design

DRAFT. Numbers are from `bio/RESULTS.md`; keep them in sync if anything is rerun.

## Where we are

- **Testbed:** BioDiscoveryAgent's IFNG screen, repurposed as a sequential experiment-design task
  with anonymized gene IDs. Each round the agent proposes a batch of genes and sees only the scores
  of genes it tested.
- **Measurements:** recall probes, repeat diagnosis (forgot vs. knew-but-repeated) and a step-level
  trace audit.
- **Opus 5.5, 100 rounds x 32 genes, full table:** 266 hits, 0 repeats, 385/385 recall probes
  correct, at a prompt of 31.5K tokens.
- **BDA-style summary policy:** 191 vs. 258 hits at round 98 (26% fewer) and 4/381 probes correct.
  Accepted tests differ by only 1.7%, so the loss is not just wasted repeats: the summaries also drop
  the scores the agent needs to choose genes.
- **Baselines:** no LLM run yet beats the UCB/prior baselines.
- **Leakage:** the week-2 similarity features leak from the sibling IL2 screen. The DepMap
  replacement is implemented but the data isn't downloaded yet.

## The current problem: compaction never triggers

The prototype compacts at 48K tokens, and our runs never get there. The full-table prompt grows about
300 tokens per round at batch 32 (4.5K at round 10, 16.7K at round 50, 31.5K at round 99), so it
would cross 48K only around round 153. A 100-round run therefore can't stress the prototype's
compaction at all. This is also the benchmark-difficulty concern raised by Yucheng and Monica.

## Next steps

1. **Make compaction fire.** For the matched pilot, lower the threshold or context window to 16-20K
   (compaction near round 50-60, same cost as now). Then one run at the real 48K, using batch 64
   (crosses near round 78) or about 200 rounds.
2. **Trace it.** Log every compaction event (round, size before and after) in every run. Done for our
   own policies (`run.json["compactions"]`); to add for the prototype.
3. **Matched prototype vs. baseline pilot.** Fix the model, features, task seed and budget, starting at
   30x16 and then 100x32. Pin the release version. The baseline needs the prototype's memory turned
   off (asked Yucheng how).
4. **Isolation.** The prototype can run code, so the agent reaches the screen only through an
   evaluator service (`bio/evaluator.py`): propose, lookup, history. Scores, hit labels and gene
   names stay in a separate process. Before trusting results we will check it can't read them.
5. **Separate what summaries lose.** A control keeps the summary plus the exact list of tested IDs
   (`--policy summary_ids`). If hits recover, membership was the problem; if not, it's the scores.
6. **Final features.** Switch to DepMap, rerun baselines, then a second seed of full and summary.

## Benchmark design ideas

- **Longer horizon on the same screen:** 150-200 rounds, or larger batches. The screen has 18,418
  genes, so 200x32 = 6,400 tests is still feasible.
- **Longer recall delays:** add probes at 16, 32 and 64 rounds. Keep closed-book probes separate from
  probes where the agent may use its memory tools.
- **Cross-round dependencies:** add a second screen (IL2) in the same episode, or tasks where later
  choices require exact scores from much earlier rounds, so a lossy memory has to fail visibly.
- **Secondary:** Sonnet and Haiku as a capability study, separate from the main same-model policy
  comparison.
- **Fallback:** LongDS-Bench Lite, if the BDA testbed can't be made hard enough.

## Risks

- The prototype only ships for Apple silicon, and only Karen has access so far.
- Usage: Opus 100x32 runs cost about $27-30 each in reported usage; long runs grow faster than
  linearly, since every round re-sends the whole table.
- One seed and leaky features so far: all results are pilot observations.
