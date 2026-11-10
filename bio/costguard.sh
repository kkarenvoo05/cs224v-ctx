#!/bin/bash
# Usage stop for a running llm_agent.py job.
#   bio/costguard.sh RUNDIR PID LIMIT_USD
# Every 30 s it sums the reported cost_usd in RUNDIR/calls.jsonl, prints progress every 10 rounds,
# and kills PID once the total passes LIMIT_USD. Results up to that round stay in calls.jsonl and RUNDIR.log.
# Example:
#   nohup bio/.venv/bin/python -I bio/llm_agent.py ... --out bio/runs/myrun > bio/runs/myrun.log 2>&1 &
#   bio/costguard.sh bio/runs/myrun $! 30
D=$1; PID=$2; LIM=$3; last=0
PY="$(cd "$(dirname "$0")" && pwd)/.venv/bin/python"
[ -x "$PY" ] || PY=python3
while kill -0 "$PID" 2>/dev/null; do
  if [ -f "$D/calls.jsonl" ]; then
    read -r cost calls failed <<<"$("$PY" -I -c "
import json,sys
c=f=n=0
for l in open(sys.argv[1]):
    try: x=json.loads(l)
    except Exception: continue
    n+=1; c+=x.get('cost_usd') or 0; f+=bool(x.get('failed'))
print(round(c,2),n,f)" "$D/calls.jsonl")"
    rnd=$(grep -oE '^round [0-9]+' "$D.log" 2>/dev/null | tail -1 | awk '{print $2}'); rnd=${rnd:-0}
    if awk "BEGIN{exit !($cost > $LIM)}"; then echo "COST LIMIT hit: \$$cost at round $rnd, stopping $PID"; kill "$PID"; exit 0; fi
    if [ $((rnd/10)) -gt $last ]; then last=$((rnd/10)); echo "round $rnd: calls=$calls cost=\$$cost failed=$failed"; fi
  fi
  grep -q Traceback "$D.log" 2>/dev/null && { echo "TRACEBACK in $D.log"; tail -3 "$D.log"; exit 1; }
  sleep 30
done
echo "run finished (round ${rnd:-?})"
