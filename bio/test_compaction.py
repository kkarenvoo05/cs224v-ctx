"""Token-threshold compaction, its trace, and the summary_set control, with no model calls."""
import json
from types import SimpleNamespace
import llm_agent
from env import BioEnv
from test_env import toy_screen


class StubLLM:
    def __init__(self, *a, **kw):
        self.n = 0
        self.prompts = []
    def __call__(self, prompt, kind, round_):
        self.n += 1
        self.prompts.append((kind, prompt))
        if kind.startswith("sum_"):
            return "short summary"
        ids = [f"G{i:05d}" for i in range(round_ * 2, round_ * 2 + 2)]
        return "Lookup:\nSolution: " + ", ".join(ids)


def run(tmp_path, monkeypatch, policy, **kw):
    monkeypatch.setattr(llm_agent, "BioEnv", lambda *a, **k: BioEnv(
        toy_screen(), rounds=4, batch=2, anonymize=True, features=False))
    stub = StubLLM()
    monkeypatch.setattr(llm_agent, "LLM", lambda *a, **k: stub)
    a = SimpleNamespace(out=str(tmp_path / policy), seed=0, backend="claude", model="stub", screen="IFNG",
                        rounds=4, batch=2, anonymize=True, features="screens", menu=0, policy=policy,
                        retries=0, diagnose=0, probes=0, threshold=10_000, threshold_tokens=0)
    for k, v in kw.items():
        setattr(a, k, v)
    llm_agent.run(a)
    return json.loads((tmp_path / policy / "run.json").read_text()), stub


def test_token_threshold_triggers_and_is_traced(tmp_path, monkeypatch):
    # Find the full-prompt size after round 1, then set the threshold just under round 2's size.
    r0, _ = run(tmp_path, monkeypatch, "summary")  # gene threshold 10,000 -> never compacts
    sizes = [c["full_prompt_tokens_est"] for c in r0["context"]]
    assert r0["compactions"] == [] and sizes == sorted(sizes) and len(sizes) == 3
    (tmp_path / "summary").rename(tmp_path / "summary_nocompact")
    r, stub = run(tmp_path, monkeypatch, "summary", threshold_tokens=sizes[1] - 1)
    assert [c["compacted"] for c in r["context"]] == [False, True, True]
    assert len(r["compactions"]) == 2 and all("view_tokens_est" in c for c in r["compactions"])
    assert sum(k.startswith("sum_") for k, _ in stub.prompts) == 4  # two summaries per compacted round


def test_summary_set_lists_exact_tested_ids_without_scores(tmp_path, monkeypatch):
    r, stub = run(tmp_path, monkeypatch, "summary_set", threshold=0)
    last = [p for k, p in stub.prompts if k == "propose"][-1]
    tested = sorted(r["tested"])
    listed = last.split("do not propose these again):\n")[1].split("\n")[0].split(", ")
    assert sorted(listed) == [g for g in tested if r["tested"][g] < 3]
    assert "short summary" in last and "measured score:\n" not in last
