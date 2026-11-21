#!/bin/bash
# Run the BDA task under ours: run_bda.sh NAME HARNESS CONTEXT_WINDOW ROUNDS BATCH [WALL_S]
#   HARNESS: codex (prototype, structured memory) | codex-shipped (plain Codex baseline)
#   GATE=1 (default): one model turn per round. Each round opens only with a random token sent in that
#     round's user message (--follow-up); the MCP server holds only the tokens' sha256 hashes, so a
#     script written in an earlier turn cannot run later rounds. GATE=0: one message, the agent may
#     script the whole episode (the Nov 13 pilot did, so context never grew).
#   FEATURES=screens|depmap (default screens)
#   HISTORY=full|last|none (default full): what the history tool returns. With full, an agent can re-read every
#     past result after compaction, so it never has to remember anything (the gated Nov 13 baseline did this 41
#     times). none removes the tool: each result is shown once, in end_round's reply.
#   REPORT_EVERY=K (default 0 = off): after every K-th and the last round the agent must name its 10 tested
#     genes with the largest |score| before proposing again (needs exact scores, not just the tested set).
#   REPEAT_COST=1 (default 0): proposing an already-tested gene uses up that batch slot (a wasted experiment), so
#     forgetting the tested set costs hits. Default 0 = rejected repeats can be re-filled for free (all runs to Nov 15).
#   NOFILES=1 (default 0): tell the plain-Codex arm (codex-shipped only) not to create or write files, so it has
#     to keep results in its context; the prototype keeps its own file memory. Enforced by instruction only (ours run
#     has no write-blocking flag); compare.py's workspace_files column shows whether it complied.
#   HYPOTHESIS_EVERY=K (default 0 = off): after every K-th and the last round the agent submits up to 5 modules of
#     tested genes plus a predicted sign, graded on held-out genes (RESERVE, default 0.15 when on) that the agent
#     can see in lookups but never test. Needs judgment over many past results, not only a record of them.
# Evaluator state, requests and scoring go to ours/evals/NAME (outside the agent workspace).
set -eu
NAME=$1; HARNESS=$2; CW=$3; R=$4; B=$5; WALL=${6:-3600}; GATE=${GATE:-1}; HISTORY=${HISTORY:-full}; REPORT_EVERY=${REPORT_EVERY:-0}; NOFILES=${NOFILES:-0}; REPEAT_COST=${REPEAT_COST:-0}
HYPOTHESIS_EVERY=${HYPOTHESIS_EVERY:-0}; RESERVE=${RESERVE:-$([ "$HYPOTHESIS_EVERY" -gt 0 ] && echo 0.15 || echo 0)}
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
  --features "${FEATURES:-screens}" --secret-seed --history "$HISTORY" --report-every "$REPORT_EVERY" $([ "$REPEAT_COST" = 1 ] && echo --repeat-cost) --hypothesis-every "$HYPOTHESIS_EVERY" --reserve "$RESERVE" --round-token-hashes "$HASHES" --port 0 --out "$EVAL" \
  > "$HERE/evals/$NAME.server.log" 2>&1 &
EVPID=$!; trap 'kill $EVPID 2>/dev/null' EXIT
for _ in $(seq 120); do [ -s "$EVAL/port" ] && break; sleep 1; done
[ -s "$EVAL/port" ] || { echo "evaluator did not start"; cat "$HERE/evals/$NAME.server.log"; exit 1; }
cat > "$HERE/mcp/$NAME.json" <<JSON
{"bda": {"command": "$ROOT/bio/.venv/bin/python",
         "args": ["-I", "$ROOT/bio/bda_mcp.py", "--url", "http://127.0.0.1:$(cat "$EVAL/port")", "--history", "$HISTORY", "--report-every", "$REPORT_EVERY", "--hypothesis-every", "$HYPOTHESIS_EVERY"]}}
JSON

TASK="You are running a pooled CRISPR screen to identify genes that regulate the production of Interferon-gamma (IFNG). The measured score is the log fold change in IFNG normalized read counts. There are 18,418 genes, identified by opaque IDs G00000..G18417 (gene names are hidden, so prior knowledge of gene names cannot help). About 5% are hits (largest |score|). You have $R rounds. In each round: propose exactly $B new, untested gene IDs with the bda propose tool (up to 3 propose calls per round to top up rejected IDs), then call end_round to get their measured scores and hit flags. You may call lookup on up to 4 IDs per round to see the 8 most similar genes to each (similar genes often behave alike). Maximize the cumulative number of hits over all $R rounds. Never re-test a gene."
case "$HISTORY" in
  none) TASK="$TASK There is no history tool: each round's results are shown once, in end_round's reply, so keep whatever record you need." ;;
  last) TASK="$TASK The history tool returns only the last closed round's results; older results are shown once, in end_round's reply, so keep whatever record you need." ;;
esac
[ "$REPORT_EVERY" -gt 0 ] && TASK="$TASK Every $REPORT_EVERY rounds and after the last round, end_round will say a report is due: call report with the 10 genes you have tested whose |score| is largest so far, before proposing again. Report accuracy is scored along with hits."
[ "$HYPOTHESIS_EVERY" -gt 0 ] && TASK="$TASK Some genes ($(python3 -I -c "print(round($RESERVE*100))")%) are held out: you can see them in lookup results but propose rejects them (held_out), so propose others. Every $HYPOTHESIS_EVERY rounds and after the last round, end_round will say a hypothesis is due: before proposing again, call hypothesis with 5 modules (the score averages over 5, so submitting fewer scores lower), each 3-10 genes you have tested that you believe act together, with the sign (+ or -) you predict for their held-out neighbours. Each module is graded on the 8 held-out genes that appear most often in its members' lookup lists: the more of them are hits with the sign you gave, the better. Hypothesis quality is scored along with hits; the grade is not shown."
[ "$REPEAT_COST" = 1 ] && TASK="$TASK Proposing a gene you already tested wastes that slot: it is not re-tested and cannot be refilled this round."
[ "$NOFILES" = 1 ] && [ "$HARNESS" = codex-shipped ] && TASK="$TASK Do not create, write or modify any files (no scripts, notes or logs on disk): keep everything you need in this conversation."
FOLLOW=()
if [ "$GATE" = 1 ]; then
  PROMPT="$TASK Rounds are run one per message: each message gives that round's round_token, which you must pass to propose. Run only that round, call end_round, then stop and wait for the next message. This is round 1 of $R; round_token: ${TOKENS[0]}"
  for k in $(seq 2 "$R"); do
    last=""; [ "$k" = "$R" ] && last=" This is the last round: after end_round (and any report or hypothesis that is due), reply with the total number of hits."
    FOLLOW+=(--follow-up "Round $k of $R. round_token: ${TOKENS[$((k-1))]}$last")
  done
else
  PROMPT="$TASK Keep going until status reports done, then reply with the total number of hits."
fi

echo "$(date) ours run $NAME harness=$HARNESS cw=$CW ${R}x${B} gate=$GATE history=$HISTORY report_every=$REPORT_EVERY nofiles=$NOFILES repeat_cost=$REPEAT_COST hypothesis_every=$HYPOTHESIS_EVERY reserve=$RESERVE" | tee -a "$HERE/runs.log"
MI=(); [ "$HARNESS" = codex ] && MI=(--model-info-dir "$HERE/model_info")
~/.ours/bin/ours run --harness "$HARNESS" --model gpt-6.1-terra --context-window "$CW" --lane subscription \
  ${MI[@]+"${MI[@]}"} --prompt "$PROMPT" ${FOLLOW[@]+"${FOLLOW[@]}"} --task "$NAME" --seed "$HERE/seed_empty" \
  --mcp-servers "$HERE/mcp/$NAME.json" --wall-clock-s "$WALL" --runs-root "$HERE/runs"
