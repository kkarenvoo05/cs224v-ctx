"""Replay finished evaluator runs under the batch constraint, offline: python -I bio/replay_constraint.py TOP MIN FROM ours/evals/RUN ..."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import BioEnv
top, mn, frm = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
cache = {}
for d in sys.argv[4:]:
    d = Path(d); cfg = json.loads((d / "config.json").read_text())
    seed = int((d / "seed_revealed.txt").read_text())
    env = BioEnv(cfg["screen"], rounds=cfg["rounds"], batch=cfg["batch"], anonymize=True, seed=seed, features="depmap")
    env.constraint_top, env.constraint_min, env.constraint_from = top, mn, frm
    for r in json.loads((d / "run.json").read_text())["rounds"]:
        env.propose(r["accepted"]); env.end_round()
    t = env.totals()
    met = [l.cons_met for l in env.log if l.cons_active]
    print(f"{d.name:12s} hits={t['cum_hits']} valid_hits={t['valid_hits']} violations={t['violations']}/{t['constrained_rounds']} "
          f"median_met={sorted(met)[len(met)//2]}")
