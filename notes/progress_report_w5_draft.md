# Progress report draft (due Mon Nov 16)

DRAFT, updated Nov 15. Numbers are from `bio/RESULTS.md`; keep them in sync if anything is rerun.

## Where we are

- **Testbed:** BioDiscoveryAgent's IFNG screen, repurposed as a sequential experiment-design task
  with anonymized gene IDs. Each round the agent proposes a batch of genes and sees only the scores
  of genes it tested.
- **Measurements:** recall probes, repeat diagnosis (forgot vs. knew-but-repeated), compaction
  tracing (round, tokens before and after) and a step-level trace audit.
- **Opus 5.5, 100 rounds x 32 genes, full table:** 266 hits, 0 repeats, 385/385 recall probes
  correct, at a prompt of 31.5K tokens.
- **BDA-style summary policy:** 191 vs. 258 hits at round 98 (26% fewer) and 4/381 probes correct.
  The summaries drop both which genes were tested and their scores. A control that keeps the summary
  plus the exact tested-ID set (`--policy summary_set`) separates the two.
- **Prototype harness:** runs on the task through an MCP evaluator (scores, labels and gene names in
  a separate process). Karen added a restricted macOS sandbox that blocks reads of the repo and data.

## What we learned this week

1. **Why compaction never triggered.** The full-table prompt grows about 300 tokens per round at
   batch 32, so it crosses 48K only near round 153. Lowering `--context-window` to 16K makes the
   prototype compact.
2. **Code-capable agents script the episode.** Given one message, both harnesses wrote a loop that
   played every round itself, so context never grew: 10-21 model requests per 100-round run and
   0 compactions, in our pilot and in all four of Karen's paired runs. Those runs measure
   scripting, not memory.
3. **A round gate fixes it.** Each round opens only with a random token sent in that round's user
   message; the evaluator holds only the tokens' hashes. Gated 30x16 pilot at 16K, one seed:

   | Arm | Hits | Repeats | Compactions | Requests | Input tokens | How it kept state |
   |---|---|---|---|---|---|---|
   | Prototype | 28 | 0 | 28 | 268 | 3.25M | its memory files |
   | Plain Codex | 54 | 0 | 23 | 167 | 1.79M | re-read the history tool 41 times |

   Random averages 24.5 hits at this size and UCB gets 167, so neither arm plays well, and one seed
   can't separate them.
4. **The history tool was a perfect external memory.** With it, forgetting costs nothing, so the
   comparison can't show a memory effect. The evaluator now takes `--history full|last|none`; with
   `none` each result is shown once, in end_round's reply, and repeats measure forgetting.
5. **With history off, the baseline starts to forget.** Same gated 30x16 pilot, `--history none`:

   | Arm | Hits | Repeats | Compactions |
   |---|---|---|---|
   | Prototype | 14 | 0 | 25 |
   | Plain Codex | 24 | 6 | 16 |

   All 6 baseline repeats came in round 29, on genes first tested in rounds 1-26. Each of its
   compactions freed less room (13.4K → 9.2K at first, 14.2K → 13.3K later), so by the end its
   summary nearly filled the window. The prototype's files kept the tested set exact. Hits are near
   random in both arms, so this shows a bookkeeping difference, not a discovery difference.

6. **At 100x32 on DepMap, plain Codex builds its own memory.** Gated, 16K, history off, a top-10
   score report every 10 rounds, one seed:

   | Arm | Hits | Repeats | Reports correct | Compactions | Input tokens |
   |---|---|---|---|---|---|
   | Prototype | 229 | 16 (round 2 only) | 100/100 | 99 | 12.4M |
   | Plain Codex | 212 | 0 | 100/100 | 44 | 5.2M |

   Random averages 153, kNN 286, UCB 338 and a no-feedback prior 351 (5 seeds each), but those
   use every gene's full DepMap profile while the agents see only neighbor lists. A baseline limited to
   the agents' own lookups (`nbr`: test neighbours of your best genes) gets 221 (215-226), the same as
   both agents. With no history tool, plain Codex wrote each round's results to a
   file and read them back, so both arms had an exact memory on disk and nothing was forgotten.
   The probe can't separate them while the agent can write files: the memory gap we saw at 30x16
   came from baselines that wrote no files (as did the 100x32 week-2 baseline, which repeated 8 genes
   before the gate bug). Whether plain Codex writes files varies by run.

## Next steps

1. **Decide what the comparison isolates.** The prototype's memory is also agent-written files (it
   appends results to `data_structures/scores.jsonl`), so blocking writes for both arms would switch
   off its own mechanism. Options: compare on tasks where a flat log isn't enough, plus cost per hit;
   or block writes only for the baseline. `compare.py` now reports each run's workspace file count,
   so improvised file memory is visible, and `NOFILES=1` tells only the baseline not to write files
   (option b). Question for Yucheng.
2. **Scale the history-off pair:** 100x32 at 16K, where the tested set (3,200 IDs) can't fit in a
   summary, and 3 seeds, so the repeat gap can be tested rather than read off one run.
3. **Final runs on Karen's isolated stack** (`run_paired_pilot.py --gate --history none`), DepMap
   features, 3 seeds, then 100x32 at 16K and one run at the real 48K (batch 64 or about 200 rounds).
4. **summary_set control** for our own policies, to split membership loss from score loss.
5. **A task where a log isn't enough** (option a): draft in `notes/harder_task_design.md`; the
   recommended first version adds batch constraints that depend on a moving top set of hits.

## Benchmark design ideas

- **Longer horizon on the same screen:** 150-200 rounds, or larger batches. The screen has 18,418
  genes, so 200x32 = 6,400 tests is still feasible.
- **Longer recall delays:** probes at 16, 32 and 64 rounds, closed-book vs. memory-tool probes kept
  separate.
- **Cross-round dependencies:** a second screen in the same episode, or choices that need exact
  scores from much earlier rounds, so a lossy memory has to fail visibly.
- **Secondary:** Sonnet and Haiku as a capability study, separate from the main same-model comparison.
- **Fallback:** LongDS-Bench Lite, if the BDA testbed can't be made hard enough.

## Risks

- The prototype ships only for Apple silicon and the release is not for redistribution.
- Usage: a gated 30x16 pair used about 3% of the weekly Codex quota; 100x32 pairs with 3 seeds will
  use much more, and the prototype arm uses about 1.8x the tokens of the baseline.
- One seed per setting so far: all results are pilot observations. DepMap features are in (first
  pair Nov 15); the earlier runs used the week-2 features, which leak from the IL2 screen.
