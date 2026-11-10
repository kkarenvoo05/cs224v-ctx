import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import BioEnv, FeatureTool, Screen  # noqa: E402
from to_audit import summarize_run, to_events  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "audit"))
import audit  # noqa: E402


def toy_screen():
    genes = [f"S{i}" for i in range(40)]
    scores = pd.Series(np.linspace(-1, 1, 40), index=genes)
    hits = frozenset(scores.abs().sort_values(ascending=False).index[:4])  # S0,S39,S1,S38
    return Screen("toy", scores, hits)


def make(anonymize=False, **kw):
    return BioEnv(toy_screen(), rounds=kw.pop("rounds", 3), batch=kw.pop("batch", 4), anonymize=anonymize,
                  features=False, **kw)


def test_reveal_only_proposed_and_hit_ratio():
    env = make()
    log = env.propose(["S0", "S5", "S39", "S10"])
    assert set(log.revealed) == {"S0", "S5", "S39", "S10"}
    assert log.revealed["S0"] == pytest.approx(-1.0)
    env.end_round()
    assert env.log[0].cum_hits == 2 and env.hit_ratio_at(1) == pytest.approx(0.5)
    assert env.hit_ratio_by_analyze() == pytest.approx(0.5)


def test_rejections_counted():
    env = make()
    env.propose(["S0", "S1", "S2", "S3"])
    env.end_round()
    log = env.propose(["S0", "NOPE", "S4", "S4", "S5", "S6", "S7", "S8"])
    assert log.repeats == ["S0"] and log.invalid == ["NOPE"] and log.dup_in_batch == ["S4"]
    assert log.accepted == ["S4", "S5", "S6", "S7"] and log.overflow == ["S8"]
    env.end_round()
    t = env.totals()
    assert (t["repeats"], t["invalid"], t["dup_in_batch"], t["overflow"]) == (1, 1, 1, 1)
    assert t["tested"] == 8


def test_topup_within_round_and_short_batch():
    env = make()
    env.propose(["S0"])
    assert env.remaining_in_batch() == 3
    env.propose(["S1", "S0"])  # S0 is an in-batch dup, not a repeat (not yet tested)
    assert env._cur.dup_in_batch == ["S0"] and env._cur.repeats == []
    env.end_round()
    assert env.totals()["short_batches"] == 1


def test_anonymized_is_seeded_permutation_and_metric_invariant():
    a, b, c = make(True, seed=1), make(True, seed=1), make(True, seed=2)
    assert a.ids == b.ids and a.ids != c.ids
    assert sorted(a.ids) == [f"G{i:05d}" for i in range(40)]
    assert "S0" not in a.index
    hit_ids = [a.ids[i] for i, s in enumerate(a.screen.genes) if s in a.screen.hits]
    a.propose(hit_ids)
    a.end_round()
    assert a.hit_ratio_at(1) == 1.0 == a.hit_ratio_by_analyze()


def test_done_after_rounds():
    env = make(rounds=2)
    for _ in range(2):
        env.propose([])
        env.end_round()
    assert env.done
    with pytest.raises(AssertionError):
        env.propose(["S0"])


def test_feature_tool_excludes_target(tmp_path):
    for name, vals in {"A": [1, 2, 3, 4], "B": [4, 3, 2, 1], "C": [1, 1, 2, 9]}.items():
        pd.DataFrame({"Gene": list("wxyz"), "Score": vals}).to_csv(tmp_path / f"ground_truth_{name}.csv", index=False)
        np.save(tmp_path / f"topmovers_{name}.npy", np.array(["w"]))
    import env as envmod
    old = envmod.SINGLE_GENE_SCREENS
    envmod.SINGLE_GENE_SCREENS = ["A", "B", "C"]
    try:
        ft = FeatureTool("A", list("wxyz") + ["q"], data_dir=tmp_path)
    finally:
        envmod.SINGLE_GENE_SCREENS = old
    assert ft.screens == ["B", "C"] and ft.X.shape == (5, 2)
    assert np.all(ft.X[4] == 0)  # missing gene -> 0
    assert ft.neighbors(0, k=1)[0][0] == 1  # w nearest x


def test_real_ifng_loads_and_features_exclude_ifng():
    env = BioEnv("IFNG", rounds=1, batch=32, anonymize=True, seed=0)
    assert len(env.ids) == 18418 and env.n_hits_total == 920
    assert "IFNG" not in env.features.screens and len(env.features.screens) == 5
    assert all(g.startswith("G") for g, _ in env.lookup(env.ids[0]))


def test_to_audit_repeat_is_stale_value(tmp_path):
    env = make()
    env.propose(["S0", "S1", "S2", "S3"]); env.end_round()
    env.propose(["S0", "S4", "S5", "S6", "S7"]); env.end_round()
    from dataclasses import asdict
    run = {"args": {"policy": "full"}, "rounds": [asdict(l) for l in env.log],
           "probes": [{"step": 2, "gene": "S1", "obs_round": 0, "delay": 2, "parsed": True, "said_tested": True,
                       "said_score": env.log[0].revealed["S1"] + 1e-4, "truth_score": env.log[0].revealed["S1"]},
                      {"step": 2, "gene": "S2", "obs_round": 0, "delay": 2, "parsed": True, "said_tested": False,
                       "said_score": None, "truth_score": env.log[0].revealed["S2"]},
                      {"step": 2, "gene": "S9", "obs_round": None, "delay": None, "parsed": True,
                       "said_tested": True, "said_score": 0.1, "truth_score": None}]}
    labels = [l["label"] for l in audit.label_uses(sorted(to_events(run), key=lambda e: e["step"]))]
    assert labels.count("stale_value") == 1 and labels.count("correct") == 8
    p = tmp_path / "run.json"
    import json
    p.write_text(json.dumps(run))
    s = summarize_run(p)
    assert s["uses"] == 9 and s["error_mix"] == {"stale_value": pytest.approx(1 / 9)}
    assert s["probe_decay"] == {"<=2": 0.5} and s["decoys"]["decoy_false_yes"] == 1


def test_to_audit_diagnosed_repeat_splits_knew_vs_forgot():
    env = make()
    env.propose(["S0", "S1", "S2", "S3"]); env.end_round()
    env.propose(["S0", "S1", "S4", "S5", "S6", "S7"]); env.end_round()
    from dataclasses import asdict
    run = {"args": {"policy": "full"}, "rounds": [asdict(l) for l in env.log], "probes": [],
           "diagnoses": [{"round": 1, "gene": "S0", "tested_round": 0, "age": 1, "said": "yes",
                          "label": "knew_but_repeated"},
                         {"round": 1, "gene": "S1", "tested_round": 0, "age": 1, "said": "no", "label": "forgot"}]}
    labels = [l["label"] for l in audit.label_uses(sorted(to_events(run), key=lambda e: e["step"]))]
    assert labels.count("ignored_known") == 1 and labels.count("stale_value") == 1
    from to_audit import diagnosis_stats
    assert diagnosis_stats(run)["labels"] == {"knew_but_repeated": 1, "forgot": 1}


def test_depmap_feature_tool_on_synthetic_csv(tmp_path):
    from env import DepMapFeatureTool
    rng = np.random.default_rng(0)
    base = rng.normal(size=40)
    cols = {"DepMap_ID": [f"ACH-{i}" for i in range(40)],
            "A (1)": base, "B (2)": base + 0.01 * rng.normal(size=40),
            "C (3)": rng.normal(size=40), "D (4)": rng.normal(size=40)}
    p = tmp_path / "achilles.csv"
    pd.DataFrame(cols).to_csv(p, index=False)
    ft = DepMapFeatureTool(["A", "B", "C", "D", "MISSING"], p, dim=3)
    assert ft.X.shape == (5, 3) and not ft.present[4] and (ft.X[4] == 0).all()
    assert ft.neighbors(0, k=1)[0][0] == 1  # B is A's co-essential partner
    assert ft.neighbors(4, k=1) == []
    assert all(j != 4 for j, _ in ft.neighbors(2, k=3))
    assert (tmp_path / "achilles.pca3.npz").exists()
    ft2 = DepMapFeatureTool(["A", "B"], p, dim=3)  # cache path
    assert ft2.neighbors(0, k=1)[0][0] == 1


def test_claude_backend_is_isolated_and_logs_usage(tmp_path, monkeypatch):
    """No real call: a stub binary checks the flags, stdin prompt and empty cwd."""
    import json
    import os
    import llm_agent
    stub = tmp_path / "claude"
    stub.write_text("""#!/bin/sh
case " $* " in *" --strict-mcp-config "*) ;; *) echo notstrict; exit 1;; esac
case " $* " in *" --no-session-persistence "*) ;; *) echo persist; exit 1;; esac
[ -z "$(ls -A .)" ] || { echo notempty; exit 1; }
p=$(cat)
[ "$p" = "PROMPT" ] || { echo badprompt; exit 1; }
echo '{"result":"hi","total_cost_usd":0.01,"usage":{"input_tokens":2,"cache_creation_input_tokens":3,"cache_read_input_tokens":5,"output_tokens":4},"modelUsage":{"m":{}}}'
""")
    os.chmod(stub, 0o755)
    monkeypatch.setattr(llm_agent, "CLAUDE_BIN", str(stub))
    log = tmp_path / "calls.jsonl"
    llm = llm_agent.LLM(log, backend="claude", model="m")
    assert llm("PROMPT", "propose", 0) == "hi"
    rec = json.loads(log.read_text())
    assert rec["prompt_tokens"] == 10 and rec["completion_tokens"] == 4 and rec["cost_usd"] == 0.01
    assert rec["model"] == "m" and rec["failed"] is False
    # Retry delays are production behavior; avoid sleeping in this stub-only test.
    monkeypatch.setattr(llm_agent.time, "sleep", lambda _: None)
    monkeypatch.setattr(llm_agent, "CLAUDE_BIN", "/usr/bin/false")
    assert llm("PROMPT", "propose", 1) == ""
    assert json.loads(log.read_text().splitlines()[-1])["failed"] is True
