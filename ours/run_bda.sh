#!/bin/bash
# Run the BDA task under ours: run_bda.sh NAME HARNESS CONTEXT_WINDOW ROUNDS BATCH [WALL_S]
#   HARNESS: codex (prototype, structured memory) | codex-shipped (plain Codex baseline)
#   GATE=1 (default): one model turn per round. Each round opens only with a random token sent in that
#     round's user message (--follow-up); the MCP server holds only the tokens' sha256 hashes, so a
#     script written in an earlier turn cannot run later rounds. GATE=0: one message, the agent may
#     script the whole episode (the Nov 13 pilot did, so context never grew).
#   FEATURES=screens|depmap (default screens)
# Evaluator state, requests and scoring go to ours/evals/NAME (outside the agent workspace).
set -eu
NAME=$1; HARNESS=$2; CW=$3; R=$4; B=$5; WALL=${6:-3600}; GATE=${GATE:-1}
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(dirname "$HERE")
EVAL="$HERE/evals/$NAME"; [ -e "$EVAL" ] && { echo "exists: $EVAL"; exit 1; }
mkdir -p "$HERE/evals" "$HERE/runs" "$HERE/seed_empty" "$HERE/mcp"

TOKENS=(); HASHES=""
if [ "$GATE" = 1 ]; then
  for _ in $(seq "$R"); do TOKENS+=("$(python3 -I -c 'import secrets; print(secrets.token_hex(4))')"); done
  HASHES=$(for t in "${TOKENS[@]}"; do printf %s "$t" | shasum -a 256 | cut -d' ' -f1; done | paste -sd, -)
fi
# The evaluator runs for the whole episode (Codex restarts MCP servers on every turn); bda_mcp.py relays to it.
"$ROOT/bio/.venv/bin/python" -I "$ROOT/bio/evaluator.py" --rounds "$R" --batch "$B" --anonymize \
  --features "${FEATURES:-screens}" --secret-seed --round-token-hashes "$HASHES" --port 0 --out "$EVAL" \
  > "$HERE/evals/$NAME.server.log" 2>&1 &
EVPID=$!; trap 'kill $EVPID 2>/dev/null' EXIT
for _ in $(seq 120); do [ -s "$EVAL/port" ] && break; sleep 1; done
[ -s "$EVAL/port" ] || { echo "evaluator did not start"; cat "$HERE/evals/$NAME.server.log"; exit 1; }
cat > "$HERE/mcp/$NAME.json" <<JSON
{"bda": {"command": "$ROOT/bio/.venv/bin/python",
         "args": ["-I", "$ROOT/bio/bda_mcp.py", "--url", "http://127.0.0.1:$(cat "$EVAL/port")"]}}
JSON

TASK="You are running a pooled CRISPR screen to identify genes that regulate the production of Interferon-gamma (IFNG). The measured score is the log fold change in IFNG normalized read counts. There are 18,418 genes, identified by opaque IDs G00000..G18417 (gene names are hidden, so prior knowledge of gene names cannot help). About 5% are hits (largest |score|). You have $R rounds. In each round: propose exactly $B new, untested gene IDs with the bda propose tool (up to 3 propose calls per round to top up rejected IDs), then call end_round to get their measured scores and hit flags. You may call lookup on up to 4 IDs per round to see the 8 most similar genes to each (similar genes often behave alike). Maximize the cumulative number of hits over all $R rounds. Never re-test a gene."
FOLLOW=()
if [ "$GATE" = 1 ]; then
  PROMPT="$TASK Rounds are run one per message: each message gives that round's round_token, which you must pass to propose. Run only that round, call end_round, then stop and wait for the next message. This is round 1 of $R; round_token: ${TOKENS[0]}"
  for k in $(seq 2 "$R"); do
    last=""; [ "$k" = "$R" ] && last=" This is the last round: after end_round, reply with the total number of hits."
    FOLLOW+=(--follow-up "Round $k of $R. round_token: ${TOKENS[$((k-1))]}$last")
  done
else
  PROMPT="$TASK Keep going until status reports done, then reply with the total number of hits."
fi

echo "$(date) ours run $NAME harness=$HARNESS cw=$CW ${R}x${B} gate=$GATE" | tee -a "$HERE/runs.log"
MI=(); [ "$HARNESS" = codex ] && MI=(--model-info-dir "$HERE/model_info")
~/.ours/bin/ours run --harness "$HARNESS" --model gpt-6.1-terra --context-window "$CW" --lane subscription \
  ${MI[@]+"${MI[@]}"} --prompt "$PROMPT" ${FOLLOW[@]+"${FOLLOW[@]}"} --task "$NAME" --seed "$HERE/seed_empty" \
  --mcp-servers "$HERE/mcp/$NAME.json" --wall-clock-s "$WALL" --runs-root "$HERE/runs"
