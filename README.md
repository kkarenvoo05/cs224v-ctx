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
2. **Tests** (should print 11 passed and 5 passed; the BDA tests take ~3 min):
   ```
   bio/.venv/bin/python -m pytest -q bio/test_env.py
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

Local integration review and revised priorities: [notes/week3_integration_review.md](notes/week3_integration_review.md).
Evaluator API, smoke checks, and remaining prototype gates: [bio/EVALUATOR.md](bio/EVALUATOR.md).
# cs224v-ctx
