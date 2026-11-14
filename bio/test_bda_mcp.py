"""The MCP wrapper speaks JSON-RPC over stdio and exposes the evaluator without leaking scores early."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def test_mcp_round_trip(tmp_path):
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "propose", "arguments": {"ids": ["G00001", "G00002", "NOPE"]}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "end_round", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "propose", "arguments": {"ids": ["G00001"]}}},
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "bogus", "arguments": {}}},
    ]
    r = subprocess.run([sys.executable, "-I", str(HERE / "bda_mcp.py"), "--rounds", "2", "--batch", "2",
                        "--anonymize", "--out", str(tmp_path / "ev")], input="\n".join(map(json.dumps, msgs)) + "\n",
                       capture_output=True, text=True, timeout=300, cwd=tmp_path)
    out = {m["id"]: m for m in map(json.loads, r.stdout.splitlines())}
    assert set(out) == {1, 2, 3, 4, 5, 6}  # no reply to the notification
    assert out[1]["result"]["capabilities"] == {"tools": {}}
    assert [t["name"] for t in out[2]["result"]["tools"]] == ["status", "propose", "end_round", "lookup", "history"]
    p = json.loads(out[3]["result"]["content"][0]["text"])
    assert p["accepted"] == ["G00001", "G00002"] and p["rejected"]["invalid"] == ["NOPE"] and "score" not in str(p)
    e = json.loads(out[4]["result"]["content"][0]["text"])
    assert [x["id"] for x in e["results"]] == ["G00001", "G00002"] and all("score" in x for x in e["results"])
    assert json.loads(out[5]["result"]["content"][0]["text"])["rejected"]["already_tested"] == ["G00001"]
    assert out[6]["error"]["code"] == -32602
    assert len((tmp_path / "ev" / "requests.jsonl").read_text().splitlines()) == 3


def test_secret_seed_committed_then_revealed(tmp_path):
    import hashlib
    msgs = [{"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": n, "arguments": a}}
            for i, (n, a) in enumerate([("propose", {"ids": ["G00001"]}), ("end_round", {})], 1)]
    r = subprocess.run([sys.executable, "-I", str(HERE / "bda_mcp.py"), "--rounds", "1", "--batch", "1",
                        "--anonymize", "--secret-seed", "--out", str(tmp_path / "ev")],
                       input="\n".join(map(json.dumps, msgs)) + "\n", capture_output=True, text=True, timeout=300)
    ev = tmp_path / "ev"
    seed = (ev / "seed_revealed.txt").read_text().strip()
    assert hashlib.sha256(seed.encode()).hexdigest() == (ev / "seed_sha256.txt").read_text().strip()
    assert '"seed": 0' in (ev / "config.json").read_text() and seed not in (ev / "config.json").read_text()
