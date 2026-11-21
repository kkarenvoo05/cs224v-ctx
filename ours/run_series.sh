#!/bin/bash
# Run matched prototype/baseline pairs: run_series.sh PREFIX CW ROUNDS BATCH N_PAIRS [WALL_S]
# Env passes through to run_bda.sh (GATE, HISTORY, REPORT_EVERY, FEATURES). Arm order alternates by pair.
# Stops before any arm once the weekly Codex quota (latest session log) is above MAX_WEEKLY (default 70%).
set -u
PREFIX=$1; CW=$2; R=$3; B=$4; N=$5; WALL=${6:-14400}; MAX=${MAX_WEEKLY:-70}
HERE=$(cd "$(dirname "$0")" && pwd)
weekly() {
  f=$(ls -t $(find "$HERE/runs" -path '*sessions*' -name '*.jsonl' 2>/dev/null) 2>/dev/null | head -1)
  [ -n "$f" ] && grep -o '"primary":{"used_percent":[0-9.]*' "$f" | tail -1 | grep -o '[0-9.]*$' || echo 0
}
for i in $(seq 0 $((N - 1))); do
  arms="ours:codex base:codex-shipped"; [ $((i % 2)) = 1 ] && arms="base:codex-shipped ours:codex"
  for a in $arms; do
    u=$(weekly); echo "$(date) weekly quota ${u}%"
    if python3 -c "import sys; sys.exit(0 if float('$u') <= $MAX else 1)"; then :; else
      echo "STOP: weekly quota ${u}% > ${MAX}%"; exit 2; fi
    "$HERE/run_bda.sh" "${PREFIX}_${a%%:*}_s$i" "${a#*:}" "$CW" "$R" "$B" "$WALL" > "$HERE/${PREFIX}_${a%%:*}_s$i.log" 2>&1
    echo "$(date) ${PREFIX}_${a%%:*}_s$i exit $?"
  done
done
echo "$(date) series done; weekly $(weekly)%"
