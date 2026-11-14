import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import BioEnv
from evaluator_service import Evaluator
from test_env import toy_screen


def make(tmp_path, **kw):
    env = BioEnv(toy_screen(), rounds=2, batch=2, anonymize=True, features=False)
    return Evaluator(env, tmp_path / "episode", **kw)


def call(e, n, action, **args):
    return e.request({"request_id": str(n), "action": action, "args": args})


def test_observations_only_and_idempotency(tmp_path):
    e = make(tmp_path)
    a, b = e.env.ids[:2]
    assert call(e, 0, "history")[1]["observations"] == []
    status, result = call(e, 1, "propose", ids=[a, b])
    assert status == 200 and {x["id"] for x in result["observations"]} == {a, b}
    assert call(e, 1, "propose", ids=[a, b]) == (status, result)
    assert e.proposals == 1
    assert call(e, 1, "propose", ids=[b])[0] == 409
    assert call(e, 2, "end_round")[0] == 200
    assert call(e, 2, "end_round")[0] == 200
    assert e.env.round == 1
    assert call(e, 3, "propose", ids=[a])[1]["repeats"] == [a]
    call(e, 4, "end_round")
    assert call(e, 5, "propose", ids=[b])[0] == 400
    assert call(e, 6, "end_round")[0] == 400
    assert e.env.hit_ratio_by_analyze() == e.env.totals()["hit_ratio"]
    snapshot = json.loads((e.out / "run.json").read_text())
    assert snapshot["status"] == "complete"
    assert snapshot["totals"]["rounds"] == 2
    for line in (e.out / "requests.jsonl").read_text().splitlines():
        response = json.dumps(json.loads(line)["response"])
        assert all(x not in response for x in ("hit_ratio", "n_hits_total", "symbol", "_score"))
    e.trace.close()


def test_catalog_is_bounded_and_pageable(tmp_path):
    e = make(tmp_path)
    first = call(e, 0, "catalog", limit=2)[1]
    second = call(e, 1, "catalog", offset=2, limit=2)[1]
    assert first["ids"] + second["ids"] == sorted(e.env.ids)[:4]
    assert first["total_ids"] == len(e.env.ids)
    assert first["next_offset"] == 2
    assert first["id_format"] == "G%05d"
    assert call(e, 2, "catalog", limit=257)[0] == 400
    e.trace.close()


def test_limits_and_validation(tmp_path):
    e = make(tmp_path, max_proposals=1, max_requests=8)
    g = e.env.ids[0]
    assert call(e, 0, "lookup", id=g, k=0)[0] == 400
    assert call(e, 1, "propose", ids=[g] * 3)[0] == 400
    assert call(e, 2, "propose", ids=[g])[0] == 200
    assert call(e, 3, "propose", ids=[g])[0] == 400
    assert call(e, 4, "scores")[0] == 400
    assert call(e, 5, "history", path="/etc/passwd")[0] == 400
    assert call(e, 6, "end_round")[0] == 200
    assert call(e, 7, "propose", ids=[g])[0] == 200
    assert call(e, 8, "history")[0] == 429
    e.trace.close()


def test_lookup_quota_and_no_overwrite(tmp_path):
    e = make(tmp_path, max_lookups=1)
    e.env.lookup = lambda g, k: [(e.env.ids[1], 0.5)]
    g = e.env.ids[0]
    assert call(e, 0, "lookup", id=g, k=1)[1]["neighbors"][0]["distance"] == 0.5
    assert call(e, 1, "lookup", id=g, k=1)[0] == 400
    with pytest.raises(FileExistsError):
        Evaluator(e.env, e.out)
    e.trace.close()


def test_baseline_reward_does_not_depend_on_hidden_scores(monkeypatch):
    import baselines

    captured = []
    original = baselines._knn_scores
    monkeypatch.setattr(baselines, "_knn_scores", lambda X, ti, y, ui, **kw: (
        captured.append(y.copy()) or original(X, ti, y, ui, **kw)))

    def factory(*args, **kwargs):
        env = BioEnv(toy_screen(), rounds=2, batch=4, anonymize=True, features=False)
        from types import SimpleNamespace
        env.features = SimpleNamespace(X=np.arange(40, dtype=np.float32)[:, None])
        if captured:
            # Seed 0 selects the same first batch. Perturb only unobserved scores.
            first = np.random.default_rng(1000).choice(np.arange(40), size=4, replace=False)
            hidden = np.ones(40, dtype=bool)
            hidden[first] = False
            env._score = env._score.copy()
            env._score[hidden] *= 1000
        return env

    monkeypatch.setattr(baselines, "BioEnv", factory)
    for _ in range(2):
        baselines.run_policy("knn", "toy", 2, 4, 0, True)
    np.testing.assert_array_equal(captured[0], captured[1])


def test_summary_set_preserves_membership_without_restoring_scores():
    from llm_agent import memory_view
    env = BioEnv(toy_screen(), rounds=2, batch=2, anonymize=True, features=False)
    env.propose(env.ids[5:7])
    env.end_round()
    calls = []

    def llm(*args):
        calls.append(args)
        return "lossy summary"

    plain = memory_view(env, "summary", 0, llm, "task", [0])
    control = memory_view(env, "summary_set", 0, llm, "task", [0])
    assert control.startswith(plain)
    assert control.endswith(", ".join(sorted(env.tested)) + "\n")
    assert all(g not in plain for g in env.tested)
    assert len(calls) == 4  # Same two summary calls per policy.


def test_depmap_cache_invalidates_when_input_changes(tmp_path):
    import pandas as pd
    from env import DepMapFeatureTool
    p = tmp_path / "features.csv"
    df = pd.DataFrame({"DepMap_ID": ["ACH-0", "ACH-1", "ACH-2"],
                       "A (1)": [0., 1., 2.], "B (2)": [2., 1., 0.]})
    df.to_csv(p, index=False)
    a = DepMapFeatureTool(["A", "B"], p, dim=1)
    df["A (1)"] *= 100
    df.to_csv(p, index=False)
    b = DepMapFeatureTool(["A", "B"], p, dim=1)
    assert np.linalg.norm(b.X[0]) > 50 * np.linalg.norm(a.X[0])


def test_http_transport_auth_and_hidden_actions(tmp_path):
    from http.server import HTTPServer
    from threading import Thread
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    from evaluator_service import handler
    e = make(tmp_path)
    server = HTTPServer(("127.0.0.1", 0), handler(e, "smoke-token"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/v1"

    def post(body, token="smoke-token"):
        req = Request(url, data=json.dumps(body).encode(), method="POST",
                      headers={"Authorization": "Bearer " + token})
        try:
            with urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    try:
        body = {"request_id": "1", "action": "history", "args": {}}
        assert post(body, "wrong")[0] == 401
        assert post(body)[1]["observations"] == []
        assert post({"request_id": "2", "action": "read_file",
                     "args": {"path": str(e.out / "run.json")}})[0] == 400
        assert post({"request_id": "3", "action": "lookup",
                     "args": {"id": e.env.ids[0], "k": float("nan")}})[0] == 400
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
        e.trace.close()


def test_round_gate_requires_each_rounds_token(tmp_path):
    import hashlib
    from env import BioEnv
    from evaluator_service import Evaluator
    from test_env import toy_screen
    env = BioEnv(toy_screen(), rounds=2, batch=1, anonymize=True, features=False)
    e = Evaluator(env, tmp_path / "ev", round_token_hashes=[hashlib.sha256(t.encode()).hexdigest() for t in ("a1", "b2")])
    g = env.ids

    def call(rid, action, args):
        return e.request({"request_id": rid, "action": action, "args": args})

    assert call("1", "propose", {"ids": [g[0]]})[0] == 400
    assert call("2", "propose", {"ids": [g[0]], "round_token": "b2"})[0] == 400
    status, r = call("3", "propose", {"ids": [g[0]], "round_token": "a1"})
    assert status == 200 and r["accepted"] == [g[0]]
    status, r = call("4", "end_round", {})
    assert status == 200 and "next" in r
    assert call("5", "propose", {"ids": [g[1]], "round_token": "a1"})[0] == 400
    assert call("6", "propose", {"ids": [g[1]], "round_token": "b2"})[0] == 200
    status, r = call("7", "end_round", {})
    assert r["done"] and "next" not in r
