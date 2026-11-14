#!/bin/bash
# Run the BDA task under ours: run_bda.sh NAME HARNESS CONTEXT_WINDOW ROUNDS BATCH [WALL_S]
#   HARNESS: codex (prototype, structured memory) | codex-shipped (plain Codex baseline)
# Evaluator state, requests and scoring go to ours/evals/NAME (outside the agent workspace).
set -eu
NAME=$1; HARNESS=$2; CW=$3; R=$4; B=$5; WALL=${6:-3600}
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(dirname "$HERE")
EVAL="$HERE/evals/$NAME"; [ -e "$EVAL" ] && { echo "exists: $EVAL"; exit 1; }
mkdir -p "$HERE/evals" "$HERE/runs" "$HERE/seed_empty" "$HERE/mcp"
cat > "$HERE/mcp/$NAME.json" <<JSON
{"bda": {"command": "$ROOT/bio/.venv/bin/python",
         "args": ["-I", "$ROOT/bio/bda_mcp.py", "--rounds", "$R", "--batch", "$B", "--anonymize",
                  "--features", "${FEATURES:-screens}", "--secret-seed", "--out", "$EVAL"]}}
JSON
PROMPT="You are running a pooled CRISPR screen to identify genes that regulate the production of Interferon-gamma (IFNG). The measured score is the log fold change in IFNG normalized read counts. There are 18,418 genes, identified by opaque IDs G00000..G18417 (gene names are hidden, so prior knowledge of gene names cannot help). About 5% are hits (largest |score|). You have $R rounds. In each round: propose exactly $B new, untested gene IDs with the bda propose tool (up to 3 propose calls per round to top up rejected IDs), then call end_round to get their measured scores and hit flags. You may call lookup on up to 4 IDs per round to see the 8 most similar genes to each (similar genes often behave alike). Maximize the cumulative number of hits over all $R rounds. Never re-test a gene. Keep going until status reports done, then reply with the total number of hits."
echo "$(date) ours run $NAME harness=$HARNESS cw=$CW ${R}x${B}" | tee -a "$HERE/runs.log"
~/.ours/bin/ours run --harness "$HARNESS" --model gpt-6.1-terra --context-window "$CW" --lane subscription \
  $([ "$HARNESS" = codex ] && echo --model-info-dir "$HERE/model_info") --prompt "$PROMPT" --task "$NAME" --seed "$HERE/seed_empty" \
  --mcp-servers "$HERE/mcp/$NAME.json" --wall-clock-s "$WALL" --runs-root "$HERE/runs"
