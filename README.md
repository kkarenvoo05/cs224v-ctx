# CS224V context-policies project: run kit (week 4)

Everything needed to run the BioDiscoveryAgent (BDA) context-policy experiments on your own machine and
your own Claude plan. The findings and next steps are in the Week 4 update doc; all numbers so far
are in `bio/RESULTS.md`.

## What's in here

| Path | What |
| --- | --- |
| `bio/llm_agent.py` | The agent: three context policies (full, summary, retrieval), recall probes, repeat diagnosis, Claude backend |
| `bio/env.py` | Screen environment, gene anonymization, gene-similarity features (week-2 cross-screen, or DepMap) |
| `bio/baselines.py` | Non-LLM baselines: random, prior, kNN, UCB |
| `bio/to_audit.py`, `audit/` | Trace audit and failure labels |
| `bio/costguard.sh` | Usage stop: kills a run once reported usage passes a cap |
| `bio/test_env.py`, `audit/test_audit.py` | Tests |
| `feasibility/data/biodiscoveryagent/datasets/` | Published BDA screens (IFNG, IL2, ...) and task prompts, from the BDA repo (see its LICENSE) |
| `bio/runs/` | Week-4 Opus runs (logs + every call) and baseline results, for comparison |
| `data/depmap/` | Empty: DepMap goes here (step 4) |
| `notes/report_draft.md` | Report draft: methods and related work |

Keep the folder layout as is: the code finds the data by relative path.

## Setup

1. **Python 3.10+ venv** (from the unzipped folder):
   ```
   python3 -m venv bio/.venv
   bio/.venv/bin/pip install -r bio/requirements.txt
   ```
2. **Tests** (should print 17 passed and 5 passed; the BDA tests take ~3 min):
   ```
   bio/.venv/bin/python -m pytest -q bio/test_env.py bio/test_checkpoint.py bio/test_compaction.py bio/test_evaluator.py
   bio/.venv/bin/python -m pytest -q audit/test_audit.py
   ```
3. **Claude Code**: install it, run `claude` once and log in. `claude auth status` shows which plan it
   uses. Usage goes to whatever account you're logged in to, so check that first. The agent calls
   `claude -p` with tools, settings, MCP servers and skills turned off and an empty working folder, so
   each call costs ~600 tokens of overhead and the model can't see the answer files.
   Quick check (one tiny call):
   ```
   echo "Reply with OK" | claude -p --tools "" --strict-mcp-config --setting-sources "" --model claude-sonnet-5-5 --output-format json
   ```
4. **DepMap features** (needed for final hit numbers; the default week-2 features leak information):
   download https://figshare.com/ndownloader/files/49843176 in a browser and save it as
   `data/depmap/achilles.csv`. Then add `--features depmap` to runs.

## Running

Start the run in the background, then put the usage stop on it right away:
```
nohup bio/.venv/bin/python -I bio/llm_agent.py --policy full --rounds 100 --batch 32 \
  --screen IFNG --anonymize --features depmap --threshold 32 --menu 64 \
  --backend claude --model claude-sonnet-5-5 --seed 0 \
  --out bio/runs/sonnet_full_100x32_s0 > bio/runs/sonnet_full_100x32_s0.log 2>&1 &
bio/costguard.sh bio/runs/sonnet_full_100x32_s0 $! 30
```
- `--policy full|summary|retrieval`; `--model` is required for the Claude backend
  (e.g. `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`).
- Week-4 Opus runs used the same settings without `--features depmap`. Compare only runs that share
  features and size, and keep the model fixed when comparing policies.
- Rough usage at Opus prices (reported, not billed on a subscription): full 100x32 ~$27, summary
  100x32 ~$30. Sonnet/Haiku should be well below that.
- Outputs: `bio/runs/<name>/calls.jsonl` (every call: prompt, response, tokens, reported cost),
  `run.json` (atomic partial snapshots of totals, curve, probes and diagnoses; status marks completion), `<name>.log`.
- If the stop kills a run, `run.json` preserves the last checkpoint. This does not implement resume. Use a fresh output directory for each run.
- Claude Code auto-updates can briefly remove the `claude` binary; the agent waits and retries.

Baselines (free, local, ~1 min):
```
bio/.venv/bin/python -I bio/baselines.py --screens IFNG --policies random prior knn ucb \
  --rounds 100 --batch 32 --seeds 0 1 2 3 4 --anonymize --features depmap \
  --out bio/runs/baselines_100x32_depmap.json
```

## Your suggested runs (from the Week 4 doc)

1. Full table at 100x32 with `claude-sonnet-5-5`, then `claude-haiku-5-5`, seed 0. Does a weaker model
   forget where Opus didn't (Opus: 0 repeats, 385/385 probes)?
2. If it does: summary and retrieval at 100x32 on that same model.
3. Codex with the context-policies library from Yucheng's group, once it arrives (not wired in yet).

Local integration review and revised priorities: [notes/week4_integration_review.md](notes/week4_integration_review.md).
# cs224v-ctx

## Added in week 5 (Nov 13)

- **Token-based compaction** for the summary policies: `--threshold-tokens N` keeps the full table until
  the prompt would pass ~N tokens, then compacts, like a harness's auto-compaction. Without it the old
  gene-count rule (`--threshold`) applies. Every round's estimated prompt size and each compaction
  event go to `run.json["context"]` and `run.json["compactions"]`, and the log prints `COMPACTION r<N>`.
  Estimate: 1.65 characters per token, calibrated on the Opus runs (30.3K estimated vs 31.5K counted at
  round 99).
- **`--policy summary_ids`**: the summary view plus the exact list of tested IDs, without scores. It
  separates forgetting *which* genes were tested from losing their scores.
- **Evaluator service** for code-capable agents such as the prototype: `bio/evaluator.py` holds the
  screen, scores and ID mapping in its own process; the agent only gets `bio/eval_client.py` (standard
  library only) and the URL. Limits per round on proposals and lookups; every request is logged to
  `OUT/requests.jsonl`; `OUT/run.json` is saved after every round.
  ```
  bio/.venv/bin/python -I bio/evaluator.py --screen IFNG --rounds 30 --batch 16 --anonymize \
    --features depmap --seed 0 --port 8765 --out bio/runs/eval_NAME
  EVAL_URL=http://127.0.0.1:8765 python3 eval_client.py help
  ```
  It only keeps hidden state out of the API: also run the agent in a folder without this repo or the
  data, and check it can't read them.
- Tests: `bio/test_compaction.py`, `bio/test_evaluator.py` (22 total with the others, no model calls).

Example: compaction at ~16K tokens on a 100x32 run (fires around round 50):
```
... --policy summary --threshold-tokens 16000 ...
```

## Running the prototype (`ours`) on the BDA task

Mac with Apple silicon only. Needs read access to Yucheng's release repo and a ChatGPT plan with Codex
(runs use that plan's quota, not Claude's).

1. Install and pin a version so runs match:
   ```
   gh release download --repo Yucheng-Jiang/context-management-codex-integration-release --pattern install.sh --output - | sh
   ~/.ours/bin/ours use 2026.11.09-166c433f
   ~/.ours/bin/ours login            # skip if `~/.ours/current/codex/bin/codex login status` says logged in
   cd ours && ~/.ours/bin/ours fetch-model gpt-6.1-terra --out model_info/gpt-6.1-terra.json
   ```
2. Run: `ours/run_bda.sh NAME HARNESS CONTEXT_WINDOW ROUNDS BATCH [WALL_S]`.
   - `HARNESS=codex` is the prototype (structured memory under `data_structures/`).
   - `HARNESS=codex-shipped` is plain Codex 0.159, the matched baseline.
   - The task's tools come from `bio/bda_mcp.py`, an MCP server that holds the screen, scores and
     gene mapping in its own process. It scrambles gene IDs with a random seed it keeps in memory, and
     writes only the seed's hash until the episode ends. The scoring goes to `ours/evals/NAME/`.
   ```
   ours/run_bda.sh pilot_ours_30x16 codex 16000 30 16
   ours/run_bda.sh pilot_base_30x16 codex-shipped 16000 30 16
   ```
3. Audit: `python3 -I ours/audit_trace.py ours/runs/<run>` gives tool calls, input tokens per request,
   each compaction (tokens before and after), and isolation flags. macOS's sandbox lets the agent
   *read* the whole disk, so isolation here is detection: any shell or JavaScript command that touches
   project files or paths outside the workspace is flagged. Check every flag by hand.

Notes from the smoke tests (Nov 13):
- `--context-window 16000` gives an effective window of 15,200 tokens. The first prompt is about
  8K tokens.
- At 4 genes a round, the prototype grows about 600-900 tokens per request (it also writes its data
  files), and the baseline about 200. The prototype compacted once in 8 rounds (15.5K → 9.2K).
