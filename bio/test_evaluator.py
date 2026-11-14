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
