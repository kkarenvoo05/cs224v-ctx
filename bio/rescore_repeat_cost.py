"""Re-score a finished evaluator run as if --repeat-cost had been on (repeats use up batch slots).

    python3 -I bio/rescore_repeat_cost.py ours/evals/nf_base_s0 ours/evals/dm_base_s0 ...

Replays requests.jsonl in order: within a round each proposed ID is taken in the order sent; an
already-tested ID spends a slot, and an accepted ID counts only while slots remain. Hits come from the
logged end_round results. Approximation: a gene dropped here stays "tested" in the log, so a later
proposal of it is still counted as a repeat (the real run would have accepted it). This slightly
over-penalises, and the agent might have acted differently had it seen the cost, so treat the numbers
as a bound, not a rerun.
"""
import json
import sys
from pathlib import Path


def rescore(ev_dir: Path) -> dict:
    cfg = json.loads((ev_dir / "config.json").read_text())
    batch = cfg["batch"]
    kept_hits = actual_hits = wasted = dropped = 0
    slots, kept = batch, set()
    for line in (ev_dir / "requests.jsonl").read_text().splitlines():
        r = json.loads(line)
        resp = r.get("response") or {}
        if r["path"] == "/propose" and "accepted" in resp:
            acc, rep = set(resp["accepted"]), set(resp["rejected"]["already_tested"])
            for g in (r.get("body") or {}).get("ids", []):
                g = str(g).strip()
                if g in rep and slots > 0:
                    slots -= 1; wasted += 1; rep.discard(g)
                elif g in acc:
                    acc.discard(g)
                    if slots > 0:
                        slots -= 1; kept.add(g)
                    else:
                        dropped += 1
        elif r["path"] == "/end_round" and "results" in resp:
            for x in resp["results"]:
                actual_hits += bool(x["hit"])
                kept_hits += bool(x["hit"]) and x["id"] in kept
            slots, kept = batch, set()
    return {"run": ev_dir.name, "hits": actual_hits, "hits_if_repeats_cost": kept_hits,
            "slots_wasted": wasted, "genes_dropped": dropped}


if __name__ == "__main__":
    rows = [rescore(Path(p)) for p in sys.argv[1:]]
    print("| run | hits | hits if repeats cost a slot | slots wasted | genes dropped |\n|---|---|---|---|---|")
    for x in rows:
        print(f"| {x['run']} | {x['hits']} | {x['hits_if_repeats_cost']} | {x['slots_wasted']} | {x['genes_dropped']} |")
