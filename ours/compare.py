"""Compare ours runs on the BDA task: evaluator scoring + trace audit, one row per run.

    python3 -I ours/compare.py pilot_ours_30x16 pilot_base_30x16

Each NAME needs ours/evals/NAME (scoring, from bda_mcp.py) and one ours/runs/NAME-* folder.
Prints a markdown table and writes ours/compare_<names>.json.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_trace  # noqa: E402

HERE = Path(__file__).resolve().parent


def row(name: str) -> dict:
    ev = json.loads((HERE / "evals" / name / "run.json").read_text())
    runs = sorted((HERE / "runs").glob(f"{name}-*"))
    au = audit_trace.main(runs[-1]) if runs else {}
    run = json.loads((runs[-1] / "run.json").read_text()) if runs else {}
    t = ev["totals"]
    return {"name": name, "harness": au.get("harness"), "status": au.get("status"),
            "rounds": t["rounds"], "tested": t["tested"], "hits": t["cum_hits"],
            "hit_ratio": round(t["hit_ratio"], 4), "recount_agrees": abs(ev["hit_ratio_recount"] - t["hit_ratio"]) < 1e-12,
            "repeats": t["repeats"], "dup_in_batch": t["dup_in_batch"], "invalid": t["invalid"],
            "short_batches": t["short_batches"], "requests": au.get("requests"),
            "max_input_tokens": au.get("max_input_tokens"), "compactions": len(au.get("compactions", [])),
            "isolation_flags": len(au.get("isolation_flags", [])),
            "input_tokens_total": (run.get("usage") or {}).get("input_tokens"),
            "wall_min": round((json.loads(json.dumps(ev))["wall_s"]) / 60, 1), "curve": ev["curve"]}


def main(names: list[str]) -> None:
    rows = [row(n) for n in names]
    cols = ["name", "harness", "status", "rounds", "hits", "repeats", "dup_in_batch", "short_batches",
            "requests", "max_input_tokens", "compactions", "isolation_flags", "input_tokens_total", "wall_min"]
    print("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols))
    for r in rows:
        print("| " + " | ".join(str(r[c]) for c in cols) + " |")
    (HERE / f"compare_{'_'.join(names)}.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
