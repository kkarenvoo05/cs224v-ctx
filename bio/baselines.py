"""Cost-free reference policies over BioEnv.

    random       uniform over untested genes
    prior        rank once by ||cross-screen profile|| (no feedback; shows how much
                 the feature tool alone gives = leakage reference)
    knn          greedy: predicted value of an untested gene = mean y over its k
                 nearest *tested* genes in feature space; y = hit + 0.01*|z|
    ucb          knn mean + beta * (mean distance to those neighbours)

Round 1 of knn/ucb is random (no observations yet).

Usage:
    bio/.venv/bin/python -I bio/baselines.py --screens IFNG IL2 Carnevale22_Adenosine \
        --rounds 100 --batch 32 --seeds 0 1 2 3 4 --anonymize --out bio/runs/baselines.json
"""

from __future__ import annotations

import argparse
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


def run_policy(policy: str, screen: str, rounds: int, batch: int, seed: int, anonymize: bool,
               k: int = 10, beta: float = 0.05, features: str = "screens") -> BioEnv:
    env = BioEnv(screen, rounds=rounds, batch=batch, anonymize=anonymize, seed=seed, features=features)
    rng = np.random.default_rng(1000 + seed)
    X = env.features.X
    n = len(env.ids)
    prior_order = np.argsort(-np.linalg.norm(X, axis=1) + 1e-6 * rng.random(n))
    while not env.done:
        tested_mask = np.zeros(n, bool)
        tested_mask[[env.index[g] for g in env.tested]] = True
        untested = np.flatnonzero(~tested_mask)
        if policy == "random" or (policy in ("knn", "ucb") and not env.tested):
            pick = rng.choice(untested, size=min(batch, len(untested)), replace=False)
        elif policy == "prior":
            pick = [i for i in prior_order if not tested_mask[i]][:batch]
        elif policy in ("knn", "ucb"):
            tidx = np.flatnonzero(tested_mask)
            absz = np.abs(env._score[tidx]) / (np.abs(env._score).std() or 1)  # revealed values only
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
    ap.add_argument("--out", default="bio/runs/baselines.json")
    a = ap.parse_args(argv)
    res = []
    for sc in a.screens:
        for p in a.policies:
            for s in a.seeds:
                env = run_policy(p, sc, a.rounds, a.batch, s, a.anonymize, features=a.features)
                assert abs(env.hit_ratio_by_analyze() - env.log[-1].hit_ratio) < 1e-12
                curve = [l.hit_ratio for l in env.log]
                res.append({"screen": sc, "policy": p, "seed": s, "curve": curve, **env.totals()})
                print(f"{sc:28s} {p:7s} seed={s} R5={curve[min(4, len(curve) - 1)]:.3f} R10={curve[min(9, len(curve) - 1)]:.3f} "
                      f"R{a.rounds}={curve[-1]:.3f} repeats={env.totals()['repeats']}", flush=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"args": vars(a), "runs": res}))
    # aggregate
    print("\nscreen, policy: mean±sd hit ratio at R5 / R10 / R%d (n=%d seeds)" % (a.rounds, len(a.seeds)))
    for sc in a.screens:
        for p in a.policies:
            C = np.array([r["curve"] for r in res if r["screen"] == sc and r["policy"] == p])
            f = lambda j: f"{C[:, min(j, C.shape[1] - 1)].mean():.3f}±{C[:, min(j, C.shape[1] - 1)].std():.3f}"
            print(f"{sc:28s} {p:7s} {f(4)} / {f(9)} / {f(-1)}")


if __name__ == "__main__":
    main()
