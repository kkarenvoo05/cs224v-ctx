#!/bin/bash
# Run arms in order with the weekly-quota guard: run_list.sh CW ROUNDS BATCH WALL_S NAME:HARNESS[:ENV=VAL,...] ...
# Common env (FEATURES, HISTORY, REPORT_EVERY, GATE) passes through; per-arm ENV=VAL pairs are added for that arm.
set -u
CW=$1; R=$2; B=$3; WALL=$4; shift 4; MAX=${MAX_WEEKLY:-70}
HERE=$(cd "$(dirname "$0")" && pwd)
weekly() {
  f=$(ls -t $(find "$HERE/runs" -path '*sessions*' -name '*.jsonl' 2>/dev/null) 2>/dev/null | head -1)
  [ -n "$f" ] && grep -o '"primary":{"used_percent":[0-9.]*' "$f" | tail -1 | grep -o '[0-9.]*$' || echo 0
}
for spec in "$@"; do
  IFS=: read -r name harness extra <<< "$spec"
  u=$(weekly); echo "$(date) weekly quota ${u}%"
  python3 -c "import sys; sys.exit(0 if float('$u') <= $MAX else 1)" || { echo "STOP: weekly quota ${u}% > ${MAX}%"; exit 2; }
  env ${extra:+$(echo "$extra" | tr , ' ')} "$HERE/run_bda.sh" "$name" "$harness" "$CW" "$R" "$B" "$WALL" > "$HERE/$name.log" 2>&1
  echo "$(date) $name exit $?"
done
echo "$(date) list done; weekly $(weekly)%"
