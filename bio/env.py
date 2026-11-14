"""Long-horizon BioDiscoveryAgent-style closed-loop screen environment.

Mirrors the semantics of BDA's `tools.agent_loop` / `analyze.py` (read, never
executed): each round the agent proposes genes; invalid or already-tested genes
are rejected; hidden scores are revealed only for accepted genes; the metric is
cumulative hit ratio = |tested ∩ topmovers| / |topmovers| (analyze.py with
essential=1, i.e. no essential-gene filter).

Differences from BDA, on purpose:
  * rounds x batch is configurable (default 100 x 32, BDA paper uses 5 x 128);
  * rejected proposals are *counted* per category (invalid / repeat of an
    earlier-round gene / duplicate inside the current batch / overflow);
    a repeat is the direct observable for forgotten state;
  * optional anonymized mode: symbols -> opaque IDs via a seeded permutation;
  * a feature/lookup tool built from the OTHER screens' scores (see
    FeatureTool for the leakage caveat).

Data files are read with pandas / numpy (allow_pickle=False); no code from the
external BDA repo is imported or executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "feasibility/data/biodiscoveryagent/datasets"

# Single-gene screens available locally. Sanchez21_down is the opposite tail of
# the Sanchez21 screen (r=0.24 with Sanchez21 on signed scores), so it is never
# used as a feature for any target (it would double-count one experiment).
SINGLE_GENE_SCREENS = [
    "IFNG", "IL2", "Carnevale22_Adenosine", "Steinhart_crispra_GD2_D22", "Sanchez21", "Scharenberg22",
]


@dataclass
class Screen:
    name: str
    scores: pd.Series  # symbol -> score (deduplicated, keep first)
    hits: frozenset  # symbols in topmovers

    @property
    def genes(self) -> list[str]:
        return list(self.scores.index)


def load_screen(name: str, data_dir: Path = DATA_DIR) -> Screen:
    s = pd.read_csv(Path(data_dir) / f"ground_truth_{name}.csv", index_col=0).iloc[:, 0]
    s = s[~s.index.duplicated(keep="first")].astype(float)
    hits = np.load(Path(data_dir) / f"topmovers_{name}.npy", allow_pickle=False)
    return Screen(name, s, frozenset(str(h) for h in hits))


class FeatureTool:
    """Per-gene profile = z-scored signed scores in the OTHER single-gene screens.

    The target screen (and its `_down` twin for Sanchez21) is excluded. Genes
    missing from a screen get 0 (= that screen's mean) in that column.

    Leakage caveat: these are real phenotypes from other published screens. For
    IFNG the IL2 screen comes from the same study (Schmidt22, primary T cells);
    signed r = 0.32 with IFNG and 222 shared hits, so most of the learnable
    signal for IFNG is "IL2 resembles IFNG". That is legitimate prior knowledge
    for a biologist, but it is a single strong axis, not a rich embedding, and
    the other 4 columns are nearly uncorrelated with IFNG (|r| <= 0.08).
    """

    def __init__(self, target: str, symbols: list[str], data_dir: Path = DATA_DIR):
        others = [s for s in SINGLE_GENE_SCREENS if s != target and not target.startswith(s + "_")]
        cols = []
        for o in others:
            sc = load_screen(o, data_dir).scores
            z = ((sc - sc.mean()) / (sc.std() or 1.0)).clip(-10, 10)  # heavy tails (Steinhart max z~105)
            cols.append(z.reindex(symbols).fillna(0.0).to_numpy(np.float32))
        self.screens = others
        self.X = np.stack(cols, axis=1)  # aligned with `symbols`

    def neighbors(self, idx: int, k: int = 8) -> list[tuple[int, float]]:
        d = np.sqrt(((self.X - self.X[idx]) ** 2).sum(1))
        d[idx] = np.inf
        nn = np.argpartition(d, k)[:k]
        nn = nn[np.argsort(d[nn])]
        return [(int(j), float(d[j])) for j in nn]


DEPMAP_CSV = Path(__file__).resolve().parent.parent / "data/depmap/achilles.csv"


class DepMapFeatureTool:
    """Per-gene profile = DepMap Achilles CRISPR gene effect across cell lines (co-essentiality).

    Same file BDA's gene_search tool uses (figshare 49843176): rows are cell lines (DepMap_ID),
    columns "SYMBOL (EntrezID)". This replaces the explicit sibling-screen feature source;
    it does not establish the absence of all contamination. Columns are centered across cell lines and reduced
    to `dim` principal components; X rows keep magnitude (prior baseline = how variable a gene's
    effect is), neighbours use cosine like BDA. Genes absent from DepMap get a zero row and no
    neighbours.
    """

    def __init__(self, symbols: list[str], csv_path: Path = DEPMAP_CSV, dim: int = 50):
        csv_path = Path(csv_path)
        cache = csv_path.with_suffix(f".pca{dim}.npz")
        digest = hashlib.sha256()
        with csv_path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        source_hash = digest.hexdigest()
        genes = E = None
        if cache.exists():
            with np.load(cache, allow_pickle=False) as z:
                if "source_sha256" in z and str(z["source_sha256"]) == source_hash:
                    genes, E = list(z["genes"]), z["E"]
        if E is None:
            df = pd.read_csv(csv_path)  # malformed records must fail validation
            df = df.drop(columns=[c for c in df.columns if c.lower() in ("depmap_id", "modelid")] +
                         ([df.columns[0]] if df.columns[0].startswith("Unnamed") else []))
            df.columns = [c.split(" (")[0] for c in df.columns]
            df = df.loc[:, ~df.columns.duplicated()].dropna(axis=0, how="any")
            M = df.to_numpy(np.float32)  # cell lines x genes
            if len(M) < 2 or not np.isfinite(M).all():
                raise ValueError("DepMap needs at least two complete, finite rows")
            M = M - M.mean(0, keepdims=True)
            U, S, Vt = np.linalg.svd(M, full_matrices=False)
            k = min(dim, len(S))
            E = (Vt[:k].T * S[:k]).astype(np.float32)  # genes x k
            genes = list(df.columns)
            tmp = cache.with_suffix(".npz.tmp")
            with tmp.open("wb") as f:
                np.savez(f, genes=np.array(genes), E=E, source_sha256=source_hash)
            tmp.replace(cache)
        pos = {g: i for i, g in enumerate(genes)}
        self.screens = [f"DepMap Achilles ({E.shape[1]} PCs)"]
        self.X = np.zeros((len(symbols), E.shape[1]), np.float32)
        self.present = np.zeros(len(symbols), bool)
        for i, g in enumerate(symbols):
            j = pos.get(str(g))
            if j is not None:
                self.X[i], self.present[i] = E[j], True
        n = np.linalg.norm(self.X, axis=1, keepdims=True)
        self._U = np.divide(self.X, n, out=np.zeros_like(self.X), where=n > 0)

    def neighbors(self, idx: int, k: int = 8) -> list[tuple[int, float]]:
        if not self.present[idx]:
            return []
        sim = self._U @ self._U[idx]
        sim[idx] = -np.inf
        sim[~self.present] = -np.inf
        k = min(k, int(self.present.sum()) - 1)
        if k <= 0:
            return []
        nn = np.argpartition(-sim, k - 1)[:k]
        nn = nn[np.argsort(-sim[nn])]
        return [(int(j), float(1 - sim[j])) for j in nn]  # cosine distance


@dataclass
class RoundLog:
    round: int
    accepted: list[str] = field(default_factory=list)
    revealed: dict = field(default_factory=dict)  # id -> score
    hits: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    repeats: list[str] = field(default_factory=list)  # tested in an EARLIER round
    dup_in_batch: list[str] = field(default_factory=list)
    overflow: list[str] = field(default_factory=list)
    cum_hits: int = 0
    hit_ratio: float = 0.0
    n_tested: int = 0


class BioEnv:
    def __init__(self, screen: str | Screen = "IFNG", rounds: int = 100, batch: int = 32,
                 anonymize: bool = False, seed: int = 0, features: bool | str = True,
                 data_dir: Path = DATA_DIR, depmap_csv: Path = DEPMAP_CSV):
        # features: True/"screens" = week-2 cross-screen profiles (leaks via sibling screen),
        #           "depmap" = DepMap Achilles co-essentiality, False = no lookup tool
        self.screen = screen if isinstance(screen, Screen) else load_screen(screen, data_dir)
        self.rounds, self.batch, self.anonymize = rounds, batch, anonymize
        symbols = self.screen.genes
        if anonymize:
            perm = np.random.default_rng(seed).permutation(len(symbols))
            self.ids = [f"G{int(p):05d}" for p in perm]  # ids[i] is the public name of symbols[i]
        else:
            self.ids = list(symbols)
        self.index = {g: i for i, g in enumerate(self.ids)}
        self._score = self.screen.scores.to_numpy()
        self._is_hit = np.array([s in self.screen.hits for s in symbols])
        self.n_hits_total = int(self._is_hit.sum())
        if features == "depmap":
            self.features = DepMapFeatureTool(symbols, depmap_csv)
        elif features:
            self.features = FeatureTool(self.screen.name, symbols, data_dir)
        else:
            self.features = None
        self.tested: dict[str, int] = {}  # id -> round tested
        self.log: list[RoundLog] = []
        self.round = 0
        self._cur = RoundLog(0)

    # ---- agent-facing API -------------------------------------------------
    @property
    def done(self) -> bool:
        return self.round >= self.rounds

    def remaining_in_batch(self) -> int:
        return self.batch - len(self._cur.accepted)

    def propose(self, genes: list[str]) -> RoundLog:
        """Submit proposals for the current round (may be called again to top up)."""
        assert not self.done, "episode finished"
        cur = self._cur
        for g in genes:
            g = str(g).strip()
            if g not in self.index:
                cur.invalid.append(g)
            elif g in self.tested:
                cur.repeats.append(g)
            elif g in cur.accepted:
                cur.dup_in_batch.append(g)
            elif len(cur.accepted) >= self.batch:
                cur.overflow.append(g)
            else:
                cur.accepted.append(g)
                i = self.index[g]
                cur.revealed[g] = float(self._score[i])
                if self._is_hit[i]:
                    cur.hits.append(g)
        return cur

    def end_round(self) -> RoundLog:
        cur = self._cur
        for g in cur.accepted:
            self.tested[g] = self.round
        cur.n_tested = len(self.tested)
        cur.cum_hits = (self.log[-1].cum_hits if self.log else 0) + len(cur.hits)
        cur.hit_ratio = cur.cum_hits / self.n_hits_total
        self.log.append(cur)
        self.round += 1
        self._cur = RoundLog(self.round)
        return cur

    def is_hit(self, gene_id: str) -> bool:
        """Revealed hit status; only valid for tested genes (BDA shows the hit list)."""
        assert gene_id in self.tested or gene_id in self._cur.revealed
        return bool(self._is_hit[self.index[gene_id]])

    def lookup(self, gene_id: str, k: int = 8) -> list[tuple[str, float]]:
        """Similar genes by distance between cross-screen profiles (no target-screen info)."""
        if self.features is None or gene_id not in self.index:
            return []
        return [(self.ids[j], d) for j, d in self.features.neighbors(self.index[gene_id], k)]

    # ---- metrics ----------------------------------------------------------
    def hit_ratio_at(self, r: int) -> float:
        """Cumulative hit ratio after round r (1-indexed); analyze.py semantics."""
        return self.log[min(r, len(self.log)) - 1].hit_ratio

    def totals(self) -> dict:
        f = lambda k: sum(len(getattr(l, k)) for l in self.log)
        return {"rounds": len(self.log), "tested": len(self.tested), "cum_hits": self.log[-1].cum_hits if self.log else 0,
                "hit_ratio": self.log[-1].hit_ratio if self.log else 0.0, "invalid": f("invalid"),
                "repeats": f("repeats"), "dup_in_batch": f("dup_in_batch"), "overflow": f("overflow"),
                "short_batches": sum(len(l.accepted) < self.batch for l in self.log)}

    def hit_ratio_by_analyze(self) -> float:
        """Independent recomputation exactly as analyze.py (set(pred) ∩ topmovers / |topmovers|)."""
        sym = self.screen.genes
        pred = {sym[self.index[g]] for g in self.tested}
        return len(pred & self.screen.hits) / len(self.screen.hits)
