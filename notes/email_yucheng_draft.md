DRAFT, for Karen and Katherine to edit before sending.

Subject: CS224V context management: why compaction hasn't triggered yet, and a few questions

Hi Yucheng,

A short update before Monday's progress report, plus a few questions about the prototype.

**Why we haven't seen compaction yet.** Our BioDiscoveryAgent testbed never reaches the 48K threshold.
With the full results table in the prompt, the prompt grows about 300 tokens per round (batch 32):
4.5K at round 10, 16.7K at round 50, 31.5K at round 100. At that rate it reaches 48K only around
round 150. So far Opus with the full table shows no forgetting at all up to 31.5K (0 repeats, every
recall probe correct), which tells us about the model, not the harness.

**What we plan to do.**
1. Lower the compaction threshold to about 16-20K for a matched pilot (prototype vs. baseline, same
   model, features, task seed and budget, 30 rounds x 16 genes first). Compaction should start around
   round 50 at batch 32.
2. One run where compaction fires at the real 48K: either batch 64 (crosses around round 78) or about
   200 rounds, so the result doesn't depend only on a small window.
3. Trace every compaction event (round, size before and after) in every run.
4. We built an evaluator service so a code-capable agent only reaches the screen through an API
   (propose, lookup, history), with scores and gene names kept in a separate process.

From our own summary policy we already see a large effect: BDA-style summaries lose 26% of hits by
round 98 vs. the full table, mostly because the summaries drop which genes were tested and their
scores (the model answers 4 of 381 recall probes correctly). We're adding a control that keeps the
summary plus the exact tested-ID list to separate the two.

**Questions.**
1. How do we turn off the prototype's structured memory to get a fair baseline with the same runtime?
2. Which flag sets the compaction threshold or context window, and is 16-20K a supported value?
3. Is there a Linux build? Karen works on Linux; for now Katherine will run it on an Apple-silicon Mac.
4. How should we connect a task's tools: is a command-line client the agent can call (our
   `eval_client.py`) enough, or does it need MCP or another interface?
5. Can Katherine get access to the release repo? Only Karen has it at the moment.
6. Monica and you mentioned the benchmark needs to be harder for long horizons. Is ~150-200 rounds on
   this screen what you had in mind, or would you rather we add a second screen or tasks with more
   cross-round dependencies?

Thanks,
Karen and Katherine
