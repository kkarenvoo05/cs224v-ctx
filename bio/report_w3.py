"""Week-3 table: per run hits, repeats, repeat diagnosis (forgot vs knew), probe recall by delay."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from to_audit import summarize_run  # noqa: E402

RUNS = Path(__file__).resolve().parent / "runs"
TOL = 5e-4


def probe_by_delay(run):
    out = {}
    for d in (1, 2, 4, 8, 16):
        ps = [p for p in run["probes"] if p["delay"] is not None and d // 2 < p["delay"] <= d]
        ok = [p["said_tested"] and p["said_score"] is not None and abs(p["said_score"] - p["truth_score"]) <= TOL
              for p in ps]
        out[d] = f"{sum(ok)}/{len(ok)}" if ok else "-"
    return out


print("| run | tested | hits | repeats | diagnosed | forgot | knew_but_repeated | audit ignored_known / stale | "
      "probe ≤1 | ≤2 | ≤4 | ≤8 | ≤16 | decoy false-yes |")
print("|---|" + "---|" * 13)
for rj in sorted(RUNS.glob("w3_*/run.json")):
    run = json.loads(rj.read_text())
    t = run["totals"]
    c = Counter(d["label"] for d in run.get("diagnoses", []))
    s = summarize_run(rj)
    em = s["error_mix"]
    pb = probe_by_delay(run)
    print(f"| {rj.parent.name} | {t['tested']} | {t['cum_hits']} | {t['repeats']} | {sum(c.values())} | "
          f"{c['forgot']} | {c['knew_but_repeated']} | {em.get('ignored_known', 0):.2f} / {em.get('stale_value', 0):.2f} | "
          + " | ".join(pb[d] for d in (1, 2, 4, 8, 16)) + f" | {s['decoys']['decoy_false_yes']}/{s['decoys']['n_decoys']} |")
