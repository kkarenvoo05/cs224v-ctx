"""Recover metrics offline by replaying recorded responses; never invokes a model.

Requires exact prompt equality at every call. Outputs are separate from source logs.
Usage: python -I bio/replay_calls.py CALLS_JSONL --args-from RUN_JSON --out NEW_DIR
Use a run with the same configuration as --args-from; policy may be overridden.
"""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_agent


class EndOfLog(Exception):
    pass


def replay(calls_path, args_path, out, policy=None):
    records = [json.loads(line) for line in Path(calls_path).read_text().splitlines()]
    args = json.loads(Path(args_path).read_text())["args"].copy()
    args["out"] = str(out)
    if policy:
        args["policy"] = policy

    instances = []

    class RecordedLLM:
        def __init__(self, *a, **kw):
            self.n = 0
            instances.append(self)

        def __call__(self, prompt, kind, round_):
            if self.n == len(records):
                raise EndOfLog()
            rec = records[self.n]
            if (prompt, kind, round_) != (rec["prompt"], rec["kind"], rec["round"]):
                raise ValueError(f"Replay mismatch at call {self.n}: {kind} round {round_}")
            self.n += 1
            return rec["response"]

    original = llm_agent.LLM
    llm_agent.LLM = RecordedLLM
    try:
        try:
            llm_agent.run(SimpleNamespace(**args))
        except EndOfLog:
            pass
    finally:
        llm_agent.LLM = original
    if not instances or instances[0].n != len(records):
        raise ValueError("Replay ended before consuming every recorded call")
    p = Path(out) / "run.json"
    recovered = json.loads(p.read_text())
    recovered["recovery"] = {"calls_file": str(Path(calls_path).resolve()),
                             "args_file": str(Path(args_path).resolve()),
                             "exact_prompt_replay": True, "recorded_calls": len(records)}
    p.write_text(json.dumps(recovered))
    return recovered


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("calls")
    ap.add_argument("--args-from", required=True)
    ap.add_argument("--policy", choices=["full", "summary", "retrieval"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    r = replay(a.calls, a.args_from, a.out, a.policy)
    print(json.dumps({"status": r["status"], "totals": r["totals"], "recovery": r["recovery"]}))
