"""Convert a bio/llm_agent.py run log (run.json) into audit/audit.py events.

Step = round index (0-based round in which the event happens). Probe-decay bins
are therefore in rounds: (1, 2, 4, 8, 16).

Mapping (documented choice):
  * every proposed gene first gets `observe` key "<id>.tested" value False at
    step 0 (item "pool") -- the agent starts knowing nothing is tested;
  * every revealed score -> `observe` key "<id>.score" value <score>,
    item "r<round>:<id>", and `update` "<id>.tested" -> True at that round;
  * every proposal -> `use` key "<id>.tested" value False ("I believe this is
    untested"), at the round it was proposed. For a fresh gene this is
    `correct`; for a repeat of an earlier-round gene the truth is True, the
    agent used the value it had before the update, so audit labels it
    `stale_value`. (In-batch duplicates are not state errors and are skipped;
    invalid IDs have no key and are reported separately, not as uses.)
  * `read` events: for the `full` policy every tested result is re-presented
    each round, so we emit `read` of each item at every later round; for the
    `summary` policy we emit reads only for rounds where the table was shown
    (n_tested <= threshold). audit._label only consults reads when the value
    is neither current nor stale, so with this mapping repeats are always
    `stale_value`; reads are emitted for completeness / future labelers.
    If the run has repeat diagnoses, a diagnosed repeat carries `belief`
    (True if the agent, asked back under the same view, said "tested"), so the
    labeler splits repeats into `ignored_known` (knew) vs `stale_value` (forgot).
  * recall probes -> `probe` key "<id>.score". Answer = the true score if the
    model said tested=yes and its number is within 5e-4 of the truth (the table
    shows 4 decimals), otherwise the parsed number (or None). Decoy probes
    (untested genes) have no observed key, so audit.probe_decay skips them;
    their false-positive rate is reported by `decoy_stats` instead.

Usage:
    bio/.venv/bin/python -I bio/to_audit.py bio/runs/llm_full/run.json > bio/runs/llm_full/audit.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "audit"))
import audit  # noqa: E402

BINS = (1, 2, 4, 8, 16)
TOL = 5e-4


def to_events(run: dict) -> list[dict]:
    a = run["args"]
    ev: list[dict] = []
    proposed: set[str] = set()
    for rl in run["rounds"]:
        proposed |= set(rl["accepted"]) | set(rl["repeats"])
    for g in sorted(proposed):
        ev.append({"type": "observe", "step": 0, "key": f"{g}.tested", "value": False, "item_id": "pool"})
    diag = {(d["round"], d["gene"]): d["said"] for d in run.get("diagnoses", [])}
    shown: list[str] = []
    n_tested = 0
    for rl in run["rounds"]:
        r = rl["round"]
        # what the agent saw this round (results of rounds < r)
        table_shown = a.get("policy") == "full" or n_tested <= a.get("threshold", 10**9)
        if table_shown:
            ev += [{"type": "read", "step": r, "item_id": i} for i in shown]
        for g in rl["repeats"]:
            u = {"type": "use", "step": r, "key": f"{g}.tested", "value": False, "entity": f"{g}.tested"}
            said = diag.get((r, g))
            if said in ("yes", "no"):  # repeat diagnosis: what the agent says when asked back
                u["belief"] = said == "yes"
            ev.append(u)
        for g in rl["accepted"]:
            ev.append({"type": "use", "step": r, "key": f"{g}.tested", "value": False, "entity": f"{g}.tested"})
        for g in rl["accepted"]:
            iid = f"r{r}:{g}"
            # Same step as this round's uses but appended after them; audit.load sorts
            # stably by step, so this round's uses still see the pre-update state.
            ev.append({"type": "observe", "step": r, "key": f"{g}.score", "value": rl["revealed"][g], "item_id": iid})
            ev.append({"type": "update", "step": r, "key": f"{g}.tested", "value": True})
            shown.append(iid)
        n_tested += len(rl["accepted"])
    for p in run.get("probes", []):
        if p["obs_round"] is None:
            continue
        ok = p["said_tested"] and p["said_score"] is not None and abs(p["said_score"] - p["truth_score"]) <= TOL
        ev.append({"type": "probe", "step": p["step"], "key": f"{p['gene']}.score",
                   "answer": p["truth_score"] if ok else p["said_score"]})
    return ev


def decoy_stats(run: dict) -> dict:
    real = [p for p in run.get("probes", []) if p["obs_round"] is not None]
    dec = [p for p in run.get("probes", []) if p["obs_round"] is None]
    return {"n_probes": len(real), "parsed": sum(p["parsed"] for p in real),
            "said_tested_rate": sum(p["said_tested"] for p in real) / max(len(real), 1),
            "n_decoys": len(dec), "decoy_false_yes": sum(p["said_tested"] for p in dec)}


def diagnosis_stats(run: dict) -> dict:
    """Forgot vs knew-but-repeated among diagnosed repeats, overall and by age (rounds since tested)."""
    from collections import Counter, defaultdict
    ds = run.get("diagnoses", [])
    by_age: dict[int, Counter] = defaultdict(Counter)
    for d in ds:
        by_age[d["age"]][d["label"]] += 1
    return {"n": len(ds), "labels": dict(Counter(d["label"] for d in ds)),
            "by_age": {a: dict(c) for a, c in sorted(by_age.items())}}


def summarize_run(run_path: str | Path) -> dict:
    run = json.loads(Path(run_path).read_text())
    ev = to_events(run)
    out_path = Path(run_path).with_name("audit_events.jsonl")
    out_path.write_text("\n".join(json.dumps(e) for e in ev) + "\n")
    s = audit.summarize(out_path, bins=BINS)
    s["probe_accuracy_overall"] = _probe_overall(ev)
    s["decoys"] = decoy_stats(run)
    s["repeat_diagnosis"] = diagnosis_stats(run)
    s["events_file"] = str(out_path)
    return s


def _probe_overall(ev):
    pr = [e for e in ev if e["type"] == "probe"]
    truth = {e["key"]: e["value"] for e in ev if e["type"] == "observe"}
    return sum(e["answer"] == truth.get(e["key"]) for e in pr) / max(len(pr), 1)


if __name__ == "__main__":
    print(json.dumps(summarize_run(sys.argv[1]), indent=2))
