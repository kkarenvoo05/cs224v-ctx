"""Print markdown tables for baselines + LLM runs.

    bio/.venv/bin/python -I bio/report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from to_audit import summarize_run  # noqa: E402


def baselines(path: Path):
    d = json.loads(path.read_text())
    a = d["args"]
    R = a["rounds"]
    marks = sorted({min(5, R), min(10, R), R})
    print(f"\n### Baselines `{path.name}`: {R} rounds x {a['batch']}, anonymized={a['anonymize']}, "
          f"n={len(a['seeds'])} seeds (mean ± sd)\n")
    print("| screen | policy | " + " | ".join(f"R{m}" for m in marks) + " | repeats |")
    print("|---|---|" + "---|" * len(marks) + "---|")
    for sc in a["screens"]:
        for p in a["policies"]:
            rs = [r for r in d["runs"] if r["screen"] == sc and r["policy"] == p]
            C = np.array([r["curve"] for r in rs])
            cells = [f"{C[:, m - 1].mean():.3f} ± {C[:, m - 1].std():.3f}" for m in marks]
            print(f"| {sc} | {p} | " + " | ".join(cells) + f" | {sum(r['repeats'] for r in rs)} |")


def llm(run_dir: Path):
    run = json.loads((run_dir / "run.json").read_text())
    calls = [json.loads(l) for l in (run_dir / "calls.jsonl").read_text().splitlines() if l.strip()]
    s = summarize_run(run_dir / "run.json")
    a, t, c = run["args"], run["totals"], run["curve"]
    kinds = {}
    for x in calls:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    return {
        "policy": a["policy"], "config": f"{a['screen']} anon={a['anonymize']} {a['rounds']}x{a['batch']} seed={a['seed']}"
                  + (f" thr={a['threshold']}" if a["policy"] == "summary" else ""),
        "R5": c[min(5, len(c)) - 1], f"R{len(c)}": c[-1], "cum_hits": t["cum_hits"], "tested": t["tested"],
        "repeats": t["repeats"], "invalid": t["invalid"], "dup_in_batch": t["dup_in_batch"],
        "short_batches": t["short_batches"], "calls": len(calls), "calls_by_kind": kinds,
        "prompt_tok": sum(x["prompt_tokens"] or 0 for x in calls),
        "completion_tok": sum(x["completion_tokens"] or 0 for x in calls),
        "max_prompt_tok": max(x["prompt_tokens"] or 0 for x in calls),
        "wall_s": run["wall_s"], "s_per_call": run["wall_s"] / max(len(calls), 1),
        "audit_use_accuracy": s["accuracy"], "audit_error_mix": s["error_mix"],
        "probe_acc": s["probe_accuracy_overall"], "probe_decay": s["probe_decay"], "decoys": s["decoys"],
        "curve": [round(x, 4) for x in c],
    }


if __name__ == "__main__":
    for p in sorted((HERE / "runs").glob("baselines*.json")):
        baselines(p)
    rows = [llm(d) for d in sorted((HERE / "runs").glob("llm_*")) if (d / "run.json").exists()]
    if rows:
        print("\n### LLM runs\n")
        for r in rows:
            print(json.dumps(r))
