"""Evaluator service: limits, no hidden-state leaks, logging, and agreement with BioEnv scoring."""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from env import BioEnv
from evaluator import Evaluator, make_server
from test_env import toy_screen

HERE = Path(__file__).resolve().parent


@pytest.fixture
def served(tmp_path):
    env = BioEnv(toy_screen(), rounds=2, batch=2, anonymize=True, features=False)
    ev = Evaluator(env, tmp_path / "ev", proposals_per_round=2, lookups_per_round=1)
    srv = make_server(ev, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"

    def client(*args):
        # Run the client from an empty folder with only the URL: what an agent sandbox would have.
        r = subprocess.run([sys.executable, "-I", str(HERE / "eval_client.py"), *args], capture_output=True,
                           text=True, cwd=tmp_path, env={**os.environ, "EVAL_URL": url})
        return json.loads(r.stdout) if args[0] != "help" else r.stdout

    yield ev, env, client
    srv.shutdown()


def test_round_flow_limits_and_no_early_scores(served):
    ev, env, client = served
    first = env.ids[:3]
    r = client("propose", ",".join([first[0], "BOGUS", first[0]]))
    assert r["accepted"] == [first[0]] and r["rejected"]["invalid"] == ["BOGUS"]
    assert r["rejected"]["duplicate"] == [first[0]]
    assert "score" not in json.dumps(r)  # scores only after end_round
    assert client("history")["results"] == []
    r = client("propose", first[1])
    assert r["remaining_in_batch"] == 0 and r["proposals_left"] == 0
    assert "limit" in client("propose", first[2])["error"]
    end = client("end_round")
    assert [x["id"] for x in end["results"]] == first[:2] and end["rounds_left"] == 1
    assert client("propose", first[0])["rejected"]["already_tested"] == [first[0]]
    client("end_round")
    assert "finished" in client("propose", first[2])["error"]


def test_history_only_reveals_tested_and_matches_env(served):
    ev, env, client = served
    client("propose", ",".join(env.ids[:2]))
    client("end_round")
    hist = client("history")["results"]
    assert {h["id"] for h in hist} == set(env.tested)
    for h in hist:
        assert h["score"] == round(env.log[0].revealed[h["id"]], 4) and h["hit"] == env.is_hit(h["id"])
    run = json.loads((ev.out / "run.json").read_text())
    assert run["totals"] == env.totals() and run["hit_ratio_recount"] == env.hit_ratio_by_analyze()
    logged = [json.loads(l) for l in (ev.out / "requests.jsonl").read_text().splitlines()]
    assert [l["path"] for l in logged] == ["/propose", "/end_round", "/history"]


def test_unknown_endpoints_and_overwrite_guard(served, tmp_path):
    ev, env, client = served
    assert "help" not in client("status")
    assert "propose" in client("help")
    with pytest.raises(FileExistsError):
        Evaluator(env, ev.out)


def test_gate_and_relay_across_restarts(tmp_path):
    """Multi-turn runs: the MCP relay is restarted every turn; state and the gate live in the evaluator."""
    import hashlib
    from evaluator import RoundGate
    env = BioEnv(toy_screen(), rounds=2, batch=1, anonymize=True, features=False)
    gate = RoundGate([hashlib.sha256(t.encode()).hexdigest() for t in ("tok1", "tok2")])
    ev = Evaluator(env, tmp_path / "ev", gate=gate)
    srv = make_server(ev, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"

    def turn(calls):  # a fresh relay process per turn, like Codex after each follow-up
        msgs = [{"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": n, "arguments": a}}
                for i, (n, a) in enumerate(calls, 1)]
        r = subprocess.run([sys.executable, "-I", str(HERE / "bda_mcp.py"), "--url", url],
                           input="\n".join(map(json.dumps, msgs)) + "\n", capture_output=True, text=True, timeout=60)
        return [json.loads(json.loads(l)["result"]["content"][0]["text"]) for l in r.stdout.splitlines()]

    g = env.ids
    t1 = turn([("propose", {"ids": [g[0]]}), ("propose", {"ids": [g[0]], "round_token": "tok1"}), ("end_round", {}),
               ("propose", {"ids": [g[1]], "round_token": "tok1"})])
    assert "not open" in t1[0]["error"] and t1[1]["accepted"] == [g[0]] and "next" in t1[2]
    assert "not open" in t1[3]["error"]
    t2 = turn([("propose", {"ids": [g[1]], "round_token": "tok2"}), ("end_round", {})])
    assert t2[0]["accepted"] == [g[1]] and t2[1]["rounds_left"] == 0 and "next" not in t2[1]
    srv.shutdown()


@pytest.mark.parametrize("mode", ["full", "last", "none"])
def test_history_modes(tmp_path, mode):
    """full: every result; last: only the last closed round; none: disabled (results are seen once)."""
    env = BioEnv(toy_screen(), rounds=3, batch=1, anonymize=True, features=False)
    ev = Evaluator(env, tmp_path / "ev", history_mode=mode)
    for g in env.ids[:2]:
        assert ev.propose([g])["accepted"] == [g]
        ev.end_round()
    h = ev.history()
    if mode == "none":
        assert "disabled" in h["error"]
    else:
        assert [x["id"] for x in h["results"]] == (env.ids[:2] if mode == "full" else env.ids[1:2])
    assert ev.status()["history"] == mode
    with pytest.raises(ValueError):
        Evaluator(env, tmp_path / "ev2", history_mode="bogus")


def test_report_probe_scores_score_memory(tmp_path):
    """Every K rounds and at the end: name the top-|score| tested genes; propose is blocked until then."""
    env = BioEnv(toy_screen(), rounds=3, batch=2, anonymize=True, features=False)
    ev = Evaluator(env, tmp_path / "ev", report_every=2, report_n=2)
    g = env.ids
    ev.propose(g[0:2]); assert "report_due" not in ev.end_round()
    ev.propose(g[2:4]); assert "report_due" in ev.end_round()
    assert "report due" in ev.propose([g[4]])["error"]
    scores = {x: abs(v) for l in env.log for x, v in l.revealed.items()}
    top = sorted(scores, key=scores.get, reverse=True)
    r = ev.report([top[0], "NOT_TESTED", top[0]])
    assert r["recorded"] and "correct" not in r  # the score is not revealed
    assert ev.reports[-1]["correct"] == 1 and ev.reports[-1]["untested"] == 1
    assert "error" in ev.report(top[:2])  # none due
    ev.propose(g[4:6]); assert "report_due" in ev.end_round()  # last round
    scores = {x: abs(v) for l in env.log for x, v in l.revealed.items()}
    ev.report(sorted(scores, key=scores.get, reverse=True)[:2])
    run = json.loads((ev.out / "run.json").read_text())
    assert len(run["reports"]) == 2 and run["reports"][1]["correct"] == 2 and run["report_score"] == 0.75


def test_gate_refuses_to_close_unopened_round(tmp_path):
    """Regression (Nov 14): end_round on a never-opened round desynced the evaluator from the messages."""
    import hashlib
    from evaluator import RoundGate
    env = BioEnv(toy_screen(), rounds=3, batch=1, anonymize=True, features=False)
    ev = Evaluator(env, tmp_path / "ev", gate=RoundGate([hashlib.sha256(t.encode()).hexdigest() for t in "abc"]))
    assert ev.propose([env.ids[0]], "a")["accepted"] and "results" in ev.end_round()
    assert "not open" in ev.propose([env.ids[1]], "a")["error"]  # old token
    assert "not open" in ev.end_round()["error"] and env.round == 1  # round 2 stays open for its token
    assert ev.propose([env.ids[1]], "b")["accepted"] and "results" in ev.end_round()


@pytest.mark.parametrize("cost", [False, True])
def test_repeat_cost_uses_a_slot(tmp_path, cost):
    """--repeat-cost: re-testing a gene wastes its batch slot; default keeps the old re-fill behaviour."""
    env = BioEnv(toy_screen(), rounds=2, batch=3, anonymize=True, features=False)
    env.repeat_cost = cost
    ev = Evaluator(env, tmp_path / "ev")
    g = env.ids
    ev.propose(g[0:3]); ev.end_round()
    r = ev.propose([g[0], g[1], g[3], g[4], g[5]])
    assert r["rejected"]["already_tested"] == [g[0], g[1]]
    if cost:
        assert r["accepted"] == [g[3]] and r["remaining_in_batch"] == 0 and r["wasted_slots_this_round"] == 2
        assert r["rejected"]["over_batch"] == [g[4], g[5]]
        assert ev.propose([g[2]])["rejected"]["over_batch"] == [g[2]] and env._cur.wasted == 2  # full: no more waste
    else:
        assert r["accepted"] == g[3:6] and r["remaining_in_batch"] == 0 and "wasted_slots_this_round" not in r
    end = ev.end_round()
    assert end["short_by"] == (2 if cost else 0)


def test_batch_constraint_moving_top_set(tmp_path):
    """--constraint-top/-min: from round 2 on, >= 2 accepted genes must be untested neighbours of the top-1 gene."""
    env = BioEnv(toy_screen(), rounds=4, batch=3, anonymize=False, features=False)
    env.constraint_top, env.constraint_min, env.constraint_from = 1, 2, 2
    nbrs = {"S0": ["S2", "S3", "S4"], "S39": ["S37", "S36"], "S20": ["S21"]}  # toy neighbour lists
    env.lookup = lambda g, k=8: [(h, 0.1) for h in nbrs.get(g, [])][:k]
    ev = Evaluator(env, tmp_path / "ev")
    ev.propose(["S20", "S0", "S10"]); r1 = ev.end_round()
    assert "constraint" not in r1  # round 1 is before constraint_from
    assert "constraint" in ev.status()
    ev.propose(["S2", "S3", "S39"]); r2 = ev.end_round()  # top-1 is S0 (|-1|): S2, S3 count
    assert r2["constraint"] == {"required": 2, "met": 2, "ok": True}
    # S39 (|score| 1) now ties S0; tie broken by ID, so S0 stays top-1 with only S4 untested: required drops to 1
    ev.propose(["S37", "S36", "S11"]); r3 = ev.end_round()
    assert r3["constraint"] == {"required": 1, "met": 0, "ok": False}
    hits_r3 = len(env.log[2].hits)
    assert r3["cum_valid_hits"] == r3["cum_hits"] - hits_r3
    t = env.totals()
    assert t["violations"] == 1 and t["constrained_rounds"] == 2 and t["valid_hits"] == r3["cum_valid_hits"]
    run = json.loads((ev.out / "run.json").read_text())
    assert run["rounds"][2]["cons_ok"] is False and run["totals"]["violations"] == 1


def test_constraint_off_by_default(tmp_path):
    env = BioEnv(toy_screen(), rounds=2, batch=2, anonymize=False, features=False)
    ev = Evaluator(env, tmp_path / "ev")
    ev.propose(["S0", "S1"]); r = ev.end_round()
    assert "constraint" not in r and "valid_hits" not in env.totals() and "constraint" not in ev.status()


def test_hypothesis_graded_on_untested_neighbours(tmp_path):
    """--hypothesis-every: modules of tested genes + sign, graded privately on their untested neighbours."""
    from evaluator import grade_module
    env = BioEnv(toy_screen(), rounds=2, batch=4, anonymize=False, features=False)
    # toy scores: linspace(-1, 1, 40); hits S0, S1 (negative) and S38, S39 (positive)
    nbrs = {"S2": ["S0", "S1", "S20"], "S3": ["S0", "S1", "S21"], "S4": ["S0", "S22"], "S5": ["S39"]}
    env.lookup = lambda g, k=8: [(h, 0.1) for h in nbrs.get(g, [])][:k]
    ev = Evaluator(env, tmp_path / "ev", hypothesis_every=1, hypothesis_heldout=4)
    ev.propose(["S2", "S3", "S4", "S5"]); r = ev.end_round()
    assert "hypothesis_due" in r and "hypothesis due" in ev.propose(["S6"])["error"]
    good = {"genes": ["S2", "S3", "S4"], "sign": "-"}
    wrong_sign = {"genes": ["S2", "S3", "S4"], "sign": "+"}
    too_small = {"genes": ["S5", "S99"], "sign": "+"}  # S99 invalid, so 1 tested member < 3
    resp = ev.hypothesis([good, wrong_sign, too_small])
    assert resp["recorded"] and "score" not in json.dumps(resp)  # grade not revealed
    m = ev.hypotheses[-1]["modules"]
    # held-out: S0 (3 members), S1 (2), then S20, S21, S22 (1 each) -> top 4 = S0, S1, S20, S21; hits with "-": S0, S1
    assert m[0]["heldout"] == ["S0", "S1", "S20", "S21"] and m[0]["score"] == 0.5
    assert m[1]["score"] == 0.0 and m[2]["score"] == 0.0 and m[2]["n_members"] == 1
    assert ev.hypotheses[-1]["score"] == 0.5 / 5  # 5 module slots, missing ones count 0
    assert "no hypothesis" in ev.hypothesis([good])["error"]
    assert grade_module(env, ["S2", "S3", "S4"], "x")["score"] == 0.0  # bad sign
    run = json.loads((ev.out / "run.json").read_text())
    assert run["hypothesis_score"] == 0.1


def test_mcp_lists_hypothesis_only_when_on():
    from bda_mcp import tool_list
    assert "hypothesis" not in [t["name"] for t in tool_list("none", True)]
    assert "hypothesis" in [t["name"] for t in tool_list("none", True, True)]


def test_reserve_held_out_and_used_for_grading(tmp_path):
    from evaluator import grade_module
    env = BioEnv(toy_screen(), rounds=2, batch=3, anonymize=False, features=False)
    env.reserved = frozenset({"S0", "S1"})
    nbrs = {"S2": ["S0", "S1", "S20"], "S3": ["S0", "S21"], "S4": ["S0", "S1"]}
    env.lookup = lambda g, k=8: [(h, 0.1) for h in nbrs.get(g, [])][:k]
    ev = Evaluator(env, tmp_path / "ev")
    r = ev.propose(["S0", "S2", "S3", "S4"])
    assert r["rejected"]["held_out"] == ["S0"] and r["accepted"] == ["S2", "S3", "S4"]
    ev.end_round()
    m = grade_module(env, ["S2", "S3", "S4"], "-", n_heldout=2)
    assert m["heldout"] == ["S0", "S1"] and m["score"] == 1.0  # only reserved genes are graded, S20/S21 ignored
    env2 = BioEnv(toy_screen(), rounds=1, batch=1, anonymize=False, features=False)
    env2.set_reserve(0.25, 7)
    env3 = BioEnv(toy_screen(), rounds=1, batch=1, anonymize=False, features=False)
    env3.set_reserve(0.25, 7)
    assert len(env2.reserved) == 10 and env2.reserved == env3.reserved  # same seed, same held-out set
