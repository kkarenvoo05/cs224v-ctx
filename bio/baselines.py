"""Cost-free reference policies over BioEnv.

    random       uniform over untested genes
    prior        rank once by ||cross-screen profile|| (no feedback; shows how much
                 the feature tool alone gives = leakage reference)
    knn          greedy: predicted value of an untested gene = mean y over its k
                 nearest *tested* genes in feature space; y = hit + 0.01*|z|
    ucb          knn mean + beta * (mean distance to those neighbours)
    nbr          information-matched with the LLM agents: no feature vectors, only what the evaluator
                 exposes. Each round it looks up (8 neighbours each) the up-to-4 tested genes with the
                 largest |score| not yet looked up, then proposes untested neighbours ranked by their best
                 parent (hit first, then |score|), filling the rest of the batch at random.
    nbr_c        nbr that obeys the batch constraint (--constraint-top/-min) with perfect bookkeeping: it
                 keeps every neighbour list it looked up, spends lookups first on current top-set genes it
                 hasn't looked up, and puts min(M, known) untested neighbours of the current top set in
                 each batch. The reference for an agent that keeps its derived state exact.

Round 1 of knn/ucb is random (no observations yet).

Usage:
    bio/.venv/bin/python -I bio/baselines.py --screens IFNG IL2 Carnevale22_Adenosine \
        --rounds 100 --batch 32 --seeds 0 1 2 3 4 --anonymize --out bio/runs/baselines.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import BioEnv  # noqa: E402


def _knn_scores(X, tested_idx, y, untested_idx, k=10, beta=0.0, chunk=2048):
    T = X[tested_idx]
    tn = (T ** 2).sum(1)
    out = np.empty(len(untested_idx), np.float32)
    k = min(k, len(tested_idx))
    for s in range(0, len(untested_idx), chunk):
        U = X[untested_idx[s:s + chunk]]
        with np.errstate(all="ignore"):  # spurious macOS Accelerate matmul warnings; inputs finite
            d2 = (U ** 2).sum(1)[:, None] + tn[None, :] - 2 * U @ T.T
        nn = np.argpartition(d2, k - 1, axis=1)[:, :k]
        mean = y[nn].mean(1)
        bonus = np.sqrt(np.maximum(np.take_along_axis(d2, nn, 1), 0)).mean(1)
        out[s:s + chunk] = mean + beta * bonus
    return out


def _nbr_pick(env, tested_mask, untested, st, batch, lookups, rng):
    """Info-matched greedy: lookups on the best tested genes, propose their untested neighbours."""
    seen = {g: (env.is_hit(g), abs(float(v))) for l in env.log for g, v in l.revealed.items()}
    best = sorted((g for g in seen if g not in st["looked"]), key=lambda g: seen[g], reverse=True)[:lookups]
    for g in best:
        st["looked"].add(g)
        for h, _ in env.lookup(g):
            st["cand"][h] = max(st["cand"].get(h, (False, 0.0)), seen[g])
    ranked = sorted((h for h in st["cand"] if not tested_mask[env.index[h]]), key=lambda h: st["cand"][h], reverse=True)
    pick = [env.index[h] for h in ranked[:batch]]
    if len(pick) < batch:
        chosen = set(pick)
        rest = np.array([i for i in untested if i not in chosen])
        pick += list(rng.choice(rest, size=min(batch - len(pick), len(rest)), replace=False))
    return np.array(pick)


def _nbr_c_pick(env, tested_mask, untested, st, batch, lookups, rng):
    seen = {g: (env.is_hit(g), abs(float(v))) for l in env.log for g, v in l.revealed.items()}
    absv = {g: v[1] for g, v in seen.items()}
    top = sorted(absv, key=lambda g: (-absv[g], g))[:env.constraint_top] if env.constraint_top else []
    want = [g for g in top if g not in st["nl"]]
    want += sorted((g for g in seen if g not in st["nl"] and g not in want), key=lambda g: seen[g], reverse=True)
    for g in want[:lookups]:
        st["nl"][g] = [h for h, _ in env.lookup(g)]
        for h in st["nl"][g]:
            st["cand"][h] = max(st["cand"].get(h, (False, 0.0)), seen[g])
    untested_ok = lambda h: not tested_mask[env.index[h]]
    key = lambda h: st["cand"].get(h, (False, 0.0))
    req = []
    if env.constraint_top and env.round + 1 >= env.constraint_from:
        known = {h for g in top for h in st["nl"].get(g, []) if untested_ok(h)}
        req = sorted(known, key=key, reverse=True)[:env.constraint_min]
    rest = [h for h in sorted(st["cand"], key=key, reverse=True) if untested_ok(h) and h not in req]
    pick = [env.index[h] for h in (req + rest)[:batch]]
    if len(pick) < batch:
        chosen = set(pick)
        pool = np.array([i for i in untested if i not in chosen])
        pick += list(rng.choice(pool, size=min(batch - len(pick), len(pool)), replace=False))
    return np.array(pick)


def run_policy(policy: str, screen: str, rounds: int, batch: int, seed: int, anonymize: bool,
               k: int = 10, beta: float = 0.05, features: str = "screens", lookups: int = 4,
               constraint: tuple[int, int, int] = (0, 0, 3)) -> BioEnv:
    env = BioEnv(screen, rounds=rounds, batch=batch, anonymize=anonymize, seed=seed, features=features)
    env.constraint_top, env.constraint_min, env.constraint_from = constraint
    rng = np.random.default_rng(1000 + seed)
    X = env.features.X
    n = len(env.ids)
    nbr_state = {"looked": set(), "cand": {}, "nl": {}}
    prior_order = np.argsort(-np.linalg.norm(X, axis=1) + 1e-6 * rng.random(n))
    while not env.done:
        tested_mask = np.zeros(n, bool)
        tested_mask[[env.index[g] for g in env.tested]] = True
        untested = np.flatnonzero(~tested_mask)
        if policy == "random" or (policy in ("knn", "ucb") and not env.tested):
            pick = rng.choice(untested, size=min(batch, len(untested)), replace=False)
        elif policy == "prior":
            pick = [i for i in prior_order if not tested_mask[i]][:batch]
        elif policy == "nbr":
            pick = _nbr_pick(env, tested_mask, untested, nbr_state, batch, lookups, rng)
        elif policy == "nbr_c":
            pick = _nbr_c_pick(env, tested_mask, untested, nbr_state, batch, lookups, rng)
        elif policy in ("knn", "ucb"):
            tidx = np.flatnonzero(tested_mask)
            observed_abs = np.abs(env._score[tidx])
            absz = observed_abs / (observed_abs.std() or 1)  # revealed values only
            y = np.array([env.is_hit(env.ids[i]) for i in tidx], np.float32) + 0.01 * absz.astype(np.float32)
            sc = _knn_scores(X, tidx, y, untested, k=k, beta=beta if policy == "ucb" else 0.0)
            sc += 1e-6 * rng.random(len(sc))
            pick = untested[np.argsort(-sc)[:batch]]
        else:
            raise ValueError(policy)
        env.propose([env.ids[i] for i in pick])
        env.end_round()
    return env


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--screens", nargs="+", default=["IFNG"])
    ap.add_argument("--policies", nargs="+", default=["random", "prior", "knn", "ucb"])
    ap.add_argument("--rounds", type=int, default=100)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--anonymize", action="store_true")
    ap.add_argument("--features", choices=["screens", "depmap"], default="screens")
    ap.add_argument("--constraint", type=int, nargs=3, default=[0, 0, 3], metavar=("TOP", "MIN", "FROM"),
                    help="batch constraint: top-set size, required neighbours per round, first round (0 0 3 = off)")
    ap.add_argument("--out", default="bio/runs/baselines.json")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if out.exists():
        raise FileExistsError(f"Choose a fresh output file: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"baseline_rewards": "observed-score standard deviation only",
                "code_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (Path(__file__), Path(__file__).with_name("env.py"))}}
    if a.features == "depmap":
        from env import DEPMAP_CSV
        h = hashlib.sha256()
        with DEPMAP_CSV.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        metadata["features_sha256"] = h.hexdigest()
    res = []
    for sc in a.screens:
        for p in a.policies:
            for s in a.seeds:
                env = run_policy(p, sc, a.rounds, a.batch, s, a.anonymize, features=a.features,
                                 constraint=tuple(a.constraint))
                assert abs(env.hit_ratio_by_analyze() - env.log[-1].hit_ratio) < 1e-12
                curve = [l.hit_ratio for l in env.log]
                res.append({"screen": sc, "policy": p, "seed": s, "curve": curve, **env.totals()})
                tmp = out.with_suffix(out.suffix + ".tmp")
                tmp.write_text(json.dumps({"args": vars(a), "metadata": metadata, "runs": res,
                                           "status": "partial"}))
                tmp.replace(out)
                print(f"{sc:28s} {p:7s} seed={s} R5={curve[min(4, len(curve) - 1)]:.3f} R10={curve[min(9, len(curve) - 1)]:.3f} "
                      f"R{a.rounds}={curve[-1]:.3f} repeats={env.totals()['repeats']}"
                      + (f" valid_hits={env.totals()['valid_hits']} violations={env.totals()['violations']}"
                         if a.constraint[0] else ""), flush=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps({"args": vars(a), "metadata": metadata, "runs": res, "status": "complete"}))
    tmp.replace(out)
    # aggregate
    print("\nscreen, policy: mean±sd hit ratio at R5 / R10 / R%d (n=%d seeds)" % (a.rounds, len(a.seeds)))
    for sc in a.screens:
        for p in a.policies:
            C = np.array([r["curve"] for r in res if r["screen"] == sc and r["policy"] == p])
            f = lambda j: f"{C[:, min(j, C.shape[1] - 1)].mean():.3f}±{C[:, min(j, C.shape[1] - 1)].std():.3f}"
            print(f"{sc:28s} {p:7s} {f(4)} / {f(9)} / {f(-1)}")


if __name__ == "__main__":
    main()
