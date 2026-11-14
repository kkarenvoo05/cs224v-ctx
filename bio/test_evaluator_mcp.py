import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from http.server import HTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluator_mcp import Bridge
from evaluator_service import handler
from test_evaluator_service import make


def test_bridge_stdio_and_evaluator_retries(tmp_path):
    evaluator = make(tmp_path)
    server = HTTPServer(("127.0.0.1", 0), handler(evaluator, "smoke-token"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = dict(os.environ, BDA_EVALUATOR_URL=f"http://127.0.0.1:{server.server_port}/v1",
               BDA_EVALUATOR_TOKEN="smoke-token")
    g = evaluator.env.ids[0]
    messages = [
        {"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
        {"method": "notifications/initialized"},
        {"id": 2, "method": "tools/list"},
        {"id": 3, "method": "tools/call", "params": {
            "name": "bda", "arguments": {"action": "propose", "args": {"ids": [g]}}}},
        {"id": 3, "method": "tools/call", "params": {
            "name": "bda", "arguments": {"action": "propose", "args": {"ids": [g]}}}},
        {"id": 4, "method": "tools/call", "params": {
            "name": "bda", "arguments": {"action": "history", "args": {}}}},
        {"id": 5, "method": "tools/call", "params": {
            "name": "bda", "arguments": {"action": "read_file", "args": {}}}},
    ]
    try:
        proc = subprocess.run([sys.executable, "-I", str(Path(__file__).with_name("evaluator_mcp.py"))],
                              env=env, input="".join(json.dumps(dict(jsonrpc="2.0", **m)) + "\n"
                                                    for m in messages),
                              capture_output=True, text=True, timeout=15, check=True)
        results = [json.loads(line) for line in proc.stdout.splitlines()]
        assert results[0]["result"]["protocolVersion"] == "2025-03-26"
        assert results[1]["result"]["tools"][0]["name"] == "bda"
        assert results[2] == results[3]
        assert not results[2]["result"]["isError"]
        observations = json.loads(results[4]["result"]["content"][0]["text"])["observations"]
        assert [x["id"] for x in observations] == [g]
        assert results[5]["error"]["code"] == -32602
        assert evaluator.proposals == 1
        assert len((evaluator.out / "requests.jsonl").read_text().splitlines()) == 3
        assert "smoke-token" not in proc.stdout + proc.stderr
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
        evaluator.trace.close()


def test_bridge_blocks_preinitialization_and_unknown_methods():
    bridge = Bridge("http://127.0.0.1:1/v1", "not-used")
    assert bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["error"]
    assert bridge.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    bridge.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}})
    assert bridge.handle({"jsonrpc": "2.0", "id": 3, "method": "read_file"})["error"]["code"] == -32601
