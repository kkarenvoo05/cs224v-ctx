"""Harness-agnostic trace audit for long-horizon agents.

A run is a JSONL trace of events. The audit diffs what the agent *read* and
*used* against a ground-truth state log and labels each error with one of the
root-cause classes from the proposal:

    never_read        a required fact was stored but never read back before use
    wrong_item        the agent read a different item than the one it needed
    stale_value       the agent used a value that had since been updated
    misattributed     the value is right but attached to the wrong entity (alias)
    missed_invalidation  the agent used a fact that was retracted earlier
    ignored_known     the agent, asked under the same context, reports the current
                      value (it "knew"), yet acted on a different one: an action
                      failure, not a memory failure (needs `belief` on the use)
    correct

Event types (one JSON object per line, all with integer "step"):
    {"type": "observe", "step", "key", "value", "item_id"}      tool result stored
    {"type": "update", "step", "key", "value"}                  ground-truth change
    {"type": "retract", "step", "key"}                          ground-truth retraction
    {"type": "alias", "step", "alias", "key"}                   two names, one entity
    {"type": "read", "step", "item_id"}                         agent read item by ref
    {"type": "use", "step", "key", "value", "entity", "belief"?}  agent relied on a fact;
                                                                optional belief = what the
                                                                agent says the value is
    {"type": "probe", "step", "key", "answer"}                  recall probe answer

Adapters for a specific harness (LOCA-bench, leaderboard testbed, host harness)
only need to emit these events; the labeler and metrics below stay the same.
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TruthState:
    """Ground-truth key -> (value, step) history, plus retractions and aliases."""

    history: dict[str, list[tuple[int, object]]] = field(default_factory=lambda: defaultdict(list))
    retracted: dict[str, int] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    item_key: dict[str, str] = field(default_factory=dict)

    def canonical(self, name: str) -> str:
        return self.aliases.get(name, name)

    def value_at(self, key: str, step: int):
        vals = [v for s, v in self.history.get(key, []) if s <= step]
        return vals[-1] if vals else None

    def ever_had(self, key: str, value, step: int) -> bool:
        return any(v == value for s, v in self.history.get(key, []) if s <= step)


def load(path: str | Path) -> list[dict]:
    with open(path) as f:
        return sorted((json.loads(line) for line in f if line.strip()), key=lambda e: e["step"])


def label_uses(events: list[dict]) -> list[dict]:
    """Replay events in order and label every `use` event."""
    truth = TruthState()
    reads: list[tuple[int, str]] = []
    labels = []
    for e in events:
        t = e["type"]
        if t in ("observe", "update"):
            truth.history[e["key"]].append((e["step"], e["value"]))
            truth.retracted.pop(e["key"], None)
            if t == "observe":
                truth.item_key[e["item_id"]] = e["key"]
        elif t == "retract":
            truth.retracted[e["key"]] = e["step"]
        elif t == "alias":
            truth.aliases[e["alias"]] = e["key"]
        elif t == "read":
            reads.append((e["step"], e["item_id"]))
        elif t == "use":
            labels.append({"step": e["step"], "key": e["key"], "label": _label(e, truth, reads)})
    return labels


def _label(use: dict, truth: TruthState, reads: list[tuple[int, str]]) -> str:
    key, step = use["key"], use["step"]
    entity = truth.canonical(use.get("entity", key))
    if key in truth.retracted and truth.retracted[key] <= step:
        return "missed_invalidation"
    if entity != key:
        return "misattributed"
    current = truth.value_at(key, step)
    if use["value"] == current:
        return "correct"
    if "belief" in use and use["belief"] == current:
        return "ignored_known"
    if truth.ever_had(key, use["value"], step):
        return "stale_value"
    read_keys = {truth.item_key.get(i) for s, i in reads if s <= step}
    if key not in read_keys:
        return "never_read"
    return "wrong_item"


def schedule_probes(observe_steps: list[tuple[int, str]], horizon: int, n: int, seed: int = 0):
    """Pick (probe_step, key) pairs spread across observation->probe delays.

    Delays are sampled log-uniformly so the decay curve has points at short and
    very long gaps, which is what the scaling question needs.
    """
    rng = random.Random(seed)
    probes = []
    for _ in range(n):
        obs_step, key = rng.choice(observe_steps)
        max_delay = horizon - obs_step
        if max_delay < 1:
            continue
        delay = int(round(max_delay ** rng.random()))
        probes.append((obs_step + max(delay, 1), key, max(delay, 1)))
    return sorted(probes)


def probe_decay(events: list[dict], bins: list[int]) -> dict[str, float]:
    """Recall-probe accuracy bucketed by delay since the key was first observed."""
    first_seen: dict[str, int] = {}
    truth = TruthState()
    hits: dict[str, list[int]] = defaultdict(list)
    for e in events:
        if e["type"] in ("observe", "update"):
            truth.history[e["key"]].append((e["step"], e["value"]))
            first_seen.setdefault(e["key"], e["step"])
        elif e["type"] == "probe" and e["key"] in first_seen:
            delay = e["step"] - first_seen[e["key"]]
            b = next((f"<={b}" for b in bins if delay <= b), f">{bins[-1]}")
            hits[b].append(int(e["answer"] == truth.value_at(e["key"], e["step"])))
    return {b: sum(v) / len(v) for b, v in hits.items()}


def summarize(path: str | Path, bins=(10, 100, 1000, 10000)) -> dict:
    events = load(path)
    labels = label_uses(events)
    counts = Counter(l["label"] for l in labels)
    total = sum(counts.values()) or 1
    return {
        "uses": sum(counts.values()),
        "accuracy": counts["correct"] / total,
        "error_mix": {k: v / total for k, v in counts.items() if k != "correct"},
        "probe_decay": probe_decay(events, list(bins)),
    }


if __name__ == "__main__":
    import sys

    print(json.dumps(summarize(sys.argv[1]), indent=2))
