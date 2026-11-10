import json

from audit import label_uses, probe_decay, schedule_probes, summarize

TOY = [
    {"type": "observe", "step": 1, "key": "geneA.score", "value": 0.9, "item_id": "r1"},
    {"type": "observe", "step": 2, "key": "geneB.score", "value": 0.1, "item_id": "r2"},
    {"type": "observe", "step": 3, "key": "SWE-agent.verified", "value": 12.5, "item_id": "r3"},
    {"type": "alias", "step": 3, "alias": "SWEAgent", "key": "SWE-agent.verified"},
    {"type": "update", "step": 5, "key": "geneA.score", "value": 0.4},
    {"type": "retract", "step": 6, "key": "geneB.score"},
    {"type": "read", "step": 7, "item_id": "r1"},
    # stale: uses pre-update value
    {"type": "use", "step": 8, "key": "geneA.score", "value": 0.9},
    # missed invalidation: geneB was retracted at step 6
    {"type": "use", "step": 8, "key": "geneB.score", "value": 0.1},
    # misattributed: right value, filed under an alias that maps elsewhere
    {"type": "use", "step": 9, "key": "OpenHands.verified", "value": 12.5, "entity": "SWEAgent"},
    # never read: correct key, wrong value, nothing read for it
    {"type": "use", "step": 9, "key": "SWE-agent.verified", "value": 30.0},
    {"type": "use", "step": 10, "key": "geneA.score", "value": 0.4},
    {"type": "probe", "step": 12, "key": "geneA.score", "answer": 0.4},
    {"type": "probe", "step": 2000, "key": "SWE-agent.verified", "answer": 99},
]


def test_labels(tmp_path):
    labels = [l["label"] for l in label_uses(TOY)]
    assert labels == ["stale_value", "missed_invalidation", "misattributed", "never_read", "correct"]


def test_wrong_item_when_key_was_read():
    events = [
        {"type": "observe", "step": 1, "key": "a", "value": 1, "item_id": "r1"},
        {"type": "read", "step": 2, "item_id": "r1"},
        {"type": "use", "step": 3, "key": "a", "value": 2},
    ]
    assert [l["label"] for l in label_uses(events)] == ["wrong_item"]


def test_ignored_known_vs_stale():
    events = [
        {"type": "observe", "step": 0, "key": "g.tested", "value": False, "item_id": "pool"},
        {"type": "update", "step": 1, "key": "g.tested", "value": True},
        {"type": "use", "step": 2, "key": "g.tested", "value": False, "belief": True},
        {"type": "use", "step": 3, "key": "g.tested", "value": False, "belief": False},
        {"type": "use", "step": 4, "key": "g.tested", "value": False},
    ]
    assert [l["label"] for l in label_uses(events)] == ["ignored_known", "stale_value", "stale_value"]


def test_probe_decay_and_summary(tmp_path):
    p = tmp_path / "trace.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in TOY))
    s = summarize(p)
    assert s["uses"] == 5 and abs(s["accuracy"] - 0.2) < 1e-9
    assert probe_decay(TOY, [10, 100, 1000, 10000]) == {"<=100": 1.0, "<=10000": 0.0}


def test_schedule_probes_in_horizon():
    probes = schedule_probes([(1, "a"), (50, "b")], horizon=10_000, n=50)
    assert all(step <= 10_000 and delay >= 1 for step, _, delay in probes)
