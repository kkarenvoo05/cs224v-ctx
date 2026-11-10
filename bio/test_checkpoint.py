"""Verify interrupted runs retain a valid checkpoint without calling a model."""
import json
from types import SimpleNamespace
import pytest
import llm_agent
from env import BioEnv
from test_env import toy_screen


def test_interruption_and_overwrite_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_agent, 'BioEnv', lambda *a, **kw: BioEnv(
        toy_screen(), rounds=2, batch=1, anonymize=True, features=False))

    class InterruptedLLM:
        def __init__(self, *a, **kw):
            self.n = 0
        def __call__(self, prompt, kind, round_):
            if self.n:
                raise RuntimeError('interrupted')
            self.n += 1
            return 'Solution: G00000'

    monkeypatch.setattr(llm_agent, 'LLM', InterruptedLLM)
    a = SimpleNamespace(out=str(tmp_path), seed=0, backend='claude', model='stub', screen='IFNG',
                        rounds=2, batch=1, anonymize=True, features='screens', menu=0,
                        policy='full', retries=0, diagnose=0, probes=1, threshold=32)
    with pytest.raises(RuntimeError, match='interrupted'):
        llm_agent.run(a)
    r = json.loads((tmp_path / 'run.json').read_text())
    assert r['status'] == 'partial'
    assert r['totals']['rounds'] == 1 and r['totals']['tested'] == 1
    with pytest.raises(FileExistsError):
        llm_agent.run(a)
