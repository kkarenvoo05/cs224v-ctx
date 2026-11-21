"""Offline floor/reference for graded hypotheses (evaluator --hypothesis-every), no LLM.

Genes are picked by the info-matched `nbr` policy; at every K-th round (and the last) each strategy
submits 5 modules of 5 tested genes, graded with evaluator.grade_module:

    random     random tested genes, random sign (the floor)
    hits       tested hits of one sign, grouped at random (needs the scores, no neighbour reasoning)
    nbr_hits   tested hits of one sign grouped by shared lookup neighbours, ranked by how many of a
               hit's looked-up neighbours were themselves same-sign hits (perfect bookkeeping of
               scores and lookups; the reference for an agent that keeps both)

    bio/.venv/bin/python -I bio/hypothesis_baselines.py --rounds 30 --batch 16 --every 10 --seeds 0 1 2 3 4
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from baselines import _nbr_pick  # noqa: E402
from env import BioEnv  # noqa: E402
from evaluator import grade_module  # noqa: E402

N_MOD, N_GENES = 5, 5


def strategies(env, looked, rng):
    sc = {g: v for l in env.log for g, v in l.revealed.items() if g in l.accepted}
    tested = sorted(sc)
    hit = {g for g in tested if env.is_hit(g)}
    out = {"random": [{"genes": list(rng.choice(tested, N_GENES, replace=False)), "sign": rng.choice(["+", "-"])}
                      for _ in range(N_MOD)]}
    by_sign = {s: [g for g in hit if (sc[g] > 0) == (s == "+")] for s in "+-"}
    mods = []
    for s in sorted(by_sign, key=lambda s: -len(by_sign[s])):
        pool = list(by_sign[s]); rng.shuffle(pool)
        mods += [{"genes": pool[i:i + N_GENES], "sign": s} for i in range(0, len(pool) - N_GENES + 1, N_GENES)]
    out["hits"] = sorted(mods, key=lambda m: rng.random())[:N_MOD]
    # nbr_hits: enrichment from looked-up lists only
    mods = []
    for s, pool in by_sign.items():
        same = set(pool)
        enrich = {g: sum(h in same for h in looked.get(g, [])) for g in pool}
        used = set()
        for g in sorted(pool, key=lambda g: (-enrich[g], g)):
            if g in used:
                continue
            Ng = set(looked.get(g, []))
            mates = [x for x in pool if x != g and x not in used and (x in Ng or Ng & set(looked.get(x, [])))]
            mates = sorted(mates, key=lambda x: (-enrich[x], x))[:N_GENES - 1]
            if len(mates) + 1 >= 3:
                mods.append(({"genes": [g] + mates, "sign": s}, enrich[g] + sum(enrich[x] for x in mates)))
                used.update([g] + mates)
    out["nbr_hits"] = [m for m, _ in sorted(mods, key=lambda t: -t[1])[:N_MOD]]
    return out


def run(seed, rounds, batch, every, heldout, reserve):
    env = BioEnv("IFNG", rounds=rounds, batch=batch, anonymize=True, seed=seed, features="depmap")
    if reserve:
        env.set_reserve(reserve, seed + 1)
    rng = np.random.default_rng(2000 + seed)
    st = {"looked": set(), "cand": {}}
    looked = {}
    scores = {}
    n = len(env.ids)
    while not env.done:
        mask = np.zeros(n, bool); mask[[env.index[g] for g in env.tested]] = True
        before = set(st["looked"])
        mask[[env.index[g] for g in env.reserved]] = True  # never proposable
        pick = _nbr_pick(env, mask, np.flatnonzero(~mask), st, batch, 4, rng)
        for g in st["looked"] - before:
            looked[g] = [h for h, _ in env.lookup(g)]
        env.propose([env.ids[i] for i in pick]); env.end_round()
        if env.round % every == 0 or env.done:
            for name, mods in strategies(env, looked, rng).items():
                s = sum(grade_module(env, m["genes"], m["sign"], heldout)["score"] for m in mods) / N_MOD
                scores.setdefault(name, []).append(s)
    return {k: float(np.mean(v)) for k, v in scores.items()}, env.log[-1].cum_hits


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=30)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--every", type=int, default=10)
    ap.add_argument("--heldout", type=int, default=8)
    ap.add_argument("--reserve", type=float, default=0.15)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    a = ap.parse_args()
    rows = [run(s, a.rounds, a.batch, a.every, a.heldout, a.reserve) for s in a.seeds]
    for name in rows[0][0]:
        v = [r[0][name] for r in rows]
        print(f"{a.rounds}x{a.batch} {name:9s} mean hypothesis score {np.mean(v):.3f} (seeds {', '.join(f'{x:.3f}' for x in v)})")
    print(f"{a.rounds}x{a.batch} hits (nbr picks): {[r[1] for r in rows]}")
