Subject: CS224V context management: results from 100-round runs, and the comparison question

Hi Yucheng,

Monica and Heyu suggested we share our latest results and logs with you, and ask for your feedback
on where we're taking the task next.

**Setup.** BioDiscoveryAgent's IFNG screen, 100 rounds x 32 genes, prototype (`--harness codex`) vs.
`codex-shipped`, same model. We set `--context-window 16000` so compaction fires every 1-2 rounds, and
gate rounds so the agent takes one turn per round (without the gate, both arms wrote a script that
played every round and never compacted). Each result is shown once, and every 10 rounds the agent
must name its 10 highest-|score| tested genes.

**What we found.**
- **When both arms can write files, they tie.** The prototype keeps its memory in files it writes
  (`data_structures/scores.jsonl`), and plain Codex did the same on its own (one file per round). Both
  had an exact record: no repeats after round 2, all top-10 reports correct. Hits: prototype 229, 210,
  223 (3 seeds); plain Codex 212.
- **When plain Codex is told not to write files, it forgets the tested set.** It re-proposed 811 and
  1,167 already-tested genes (2 seeds), but still named the top 10 correctly every time. Its hits
  (211, 215) didn't drop only because our evaluator lets the agent refill a rejected slot. Re-scored
  so a repeat uses up its slot, it falls to 180 and 176; the prototype barely changes.
- **The task is easy for a flat log.** A no-LLM heuristic using the same lookups gets 221 hits, so
  hits alone don't separate the arms.

**Plan.** Monica and Heyu suggested not comparing against Codex without file memory, since that isn't a
fair setup. So we keep files allowed for both arms and make the task need more than a flat log. Every
10 rounds the agent must now submit up to 5 "modules": groups of 3-10 genes it has tested, each with a
predicted sign, that it thinks act together. Each module is graded on 8 genes we hold out from testing
(15% of genes are never testable), chosen as the held-out genes that appear most often in the module
members' neighbour lists; the score is the fraction of those that are hits of the predicted sign. The
agent never sees the grade. Doing well means keeping scores, signs and lookup results together and
grouping hits by shared neighbours. A no-LLM reference that does this with perfect bookkeeping scores
0.16 at 100x32, against 0.03 for random modules (max 1.0). In a 30x16 pilot (one seed) the prototype
scored 0.05 and plain Codex 0.008; plain Codex wrote no files this time and put non-hits in most of its
modules. The prototype also under-submitted (1-3 modules per checkpoint
instead of 5), so the task text now says the score averages over 5. The 100x32 runs, 3 seeds per arm,
started Nov 20 and should finish by Nov 21; we'll send those results and logs when they're in.

**Questions.**
1. Does this kind of task test what the prototype's structured memory is meant to do? Is there a
   task shape you'd expect to show its advantage more clearly?
2. Is gating one round per user message (with `--follow-up`) a fair way to use the prototype for a
   long multi-turn task, or is there a mode you'd rather we use?
3. Is a 16K window reasonable, or should we also run one at the real 48K (batch 64 or about 200 rounds)?

**Logs.** [LINK] has, for each of the 6 runs, the `ours run` output folder (traces, requests,
workspace) and our evaluator's request log, plus a results table and the launch commands. They're
shared only with you, since the release isn't for redistribution.

Thanks,
Karen and Katherine
