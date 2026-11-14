"""Validate BDA's supplied Achilles file and record evaluator-only provenance."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import DEPMAP_CSV, SINGLE_GENE_SCREENS, DepMapFeatureTool, load_screen


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, default=DEPMAP_CSV)
    p.add_argument("--out", type=Path, default=DEPMAP_CSV.parent / "manifest.json")
    p.add_argument("--metadata", type=Path, default=DEPMAP_CSV.parent / "figshare_metadata.json")
    a = p.parse_args()
    metadata = json.loads(a.metadata.read_text())
    entry = next(f for f in metadata["files"] if f["id"] == 49843176)
    md5 = hashlib.md5()
    with a.csv.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            md5.update(chunk)
    if a.csv.stat().st_size != entry["size"] or md5.hexdigest() != entry["computed_md5"]:
        raise ValueError("Download does not match Figshare size/checksum")
    raw = pd.read_csv(a.csv)
    if "DepMap_ID" not in raw or not raw["DepMap_ID"].str.match(r"^ACH-\d+$").all():
        raise ValueError("Unexpected cell-line identifier column")
    if raw["DepMap_ID"].duplicated().any():
        raise ValueError("Duplicate cell-line IDs")
    features = raw.drop(columns="DepMap_ID")
    if not all(" (" in c and c.endswith(")") for c in features):
        raise ValueError("Unexpected gene column names")
    symbols = pd.Index([c.split(" (")[0] for c in features])
    complete = features.loc[:, ~symbols.duplicated()].dropna(axis=0, how="any")
    if len(complete) < 2 or not np.isfinite(complete.to_numpy(dtype=float)).all():
        raise ValueError("Insufficient finite complete rows")
    report = {"file_id": 49843176,
              "source": "https://api.figshare.com/v2/file/download/49843176",
              "original_readme_url": "https://figshare.com/ndownloader/files/49843176",
              "source_description": "BDA-supplied Achilles CSV; upstream DepMap release not yet verified",
              "upstream_release": None, "upstream_release_date": None,
              "figshare_doi": metadata["doi"], "figshare_version": metadata["version"],
              "figshare_published_date": metadata["published_date"],
              "license": metadata["license"], "md5_matches_figshare": True,
              "verified_at": datetime.now(timezone.utc).isoformat(),
              "sha256": sha256(a.csv), "bytes": a.csv.stat().st_size,
              "cell_lines": len(raw), "gene_columns": len(features.columns),
              "duplicate_symbols": int(symbols.duplicated().sum()),
              "missing_cells": int(features.isna().sum().sum()),
              "complete_cell_lines": len(complete), "dropped_cell_lines": len(raw) - len(complete),
              "preprocessing": "Keep first duplicate symbol; drop rows missing any retained gene; center columns; exact SVD; 50 PCs",
              "gene_symbols_matching_screen_names": [s for s in SINGLE_GENE_SCREENS if s in symbols],
              "coverage": {},
              "contamination_limit": "Replaces explicit sibling-screen feature table. Gene symbols can coincide with screen names; no claim of clean model training data or complete source provenance."}
    for name in SINGLE_GENE_SCREENS:
        sc = load_screen(name)
        ft = DepMapFeatureTool(sc.genes, a.csv)
        if not np.isfinite(ft.X).all():
            raise ValueError("Nonfinite PCA features")
        report["coverage"][name] = {"genes": len(sc.genes), "present": int(ft.present.sum()),
                                     "missing": int((~ft.present).sum()),
                                     "fraction": float(ft.present.mean()),
                                     "missing_symbols": [g for g, found in zip(sc.genes, ft.present) if not found]}
    a.out.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "coverage"}, indent=2))
    for name, coverage in report["coverage"].items():
        print(name, {k: v for k, v in coverage.items() if k != "missing_symbols"})


if __name__ == "__main__":
    main()
