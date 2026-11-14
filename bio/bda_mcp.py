"""The BDA evaluator as a stdio MCP server, for agents that take MCP tools (e.g. `ours run --mcp-servers`).

The server process holds the screen, scores, hit labels and ID mapping; the agent sees only tool
results. Tools: status, propose, end_round, lookup, history (same semantics and limits as
evaluator.py). Requests, run.json and config go to --out, which must be outside the agent's workspace.
Standard library only (newline-delimited JSON-RPC 2.0, MCP tools subset).

Example mcp.json for ours:
    {"bda": {"command": "/ABS/bio/.venv/bin/python",
             "args": ["-I", "/ABS/bio/bda_mcp.py", "--rounds", "30", "--batch", "16", "--anonymize",
                      "--out", "/ABS/bio/runs/ours_NAME_eval"]}}
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import BioEnv  # noqa: E402
from evaluator import Evaluator, RoundGate  # noqa: E402

IDS = {"type": "object", "properties": {"ids": {"type": "array", "items": {"type": "string"}}}, "required": ["ids"]}
NONE = {"type": "object", "properties": {}}
TOOLS = [
    ("status", "Current round, batch size, genes left to propose this round, proposal/lookup budget left, "
               "genes tested and cumulative hits.", NONE, "GET", "/status"),
    ("propose", "Submit gene IDs for the current round (pass round_token if the round's message gave one). Returns which were accepted and which were rejected "
                "(invalid, already tested, duplicate, over the batch). Scores are not shown until end_round. "
                "Limited calls per round.", IDS, "POST", "/propose"),
    ("end_round", "Close the current round and get the measured score and hit flag of every accepted gene.",
     NONE, "POST", "/end_round"),
    ("lookup", "Similar genes (8 nearest) for each given ID; limited IDs per round.", IDS, "POST", "/lookup"),
    ("history", "Every result you have observed so far: round, id, score, hit.", NONE, "GET", "/history"),
]
ROUTES = {name: (method, path) for name, _, _, method, path in TOOLS}
TOOLS[1] = (TOOLS[1][0], TOOLS[1][1], {"type": "object", "properties": {
    "ids": {"type": "array", "items": {"type": "string"}}, "round_token": {"type": "string"}}, "required": ["ids"]},
    TOOLS[1][3], TOOLS[1][4])


class Relay:
    """Forwards tool calls to a running evaluator.py, which keeps state across agent turns
    (Codex restarts MCP servers on every follow-up message)."""

    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def handle(self, verb: str, path: str, body) -> tuple[int, dict]:
        import urllib.error
        import urllib.request
        req = urllib.request.Request(self.url + path, method=verb, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body or {}).encode() if verb == "POST" else None)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())


def handle(ev, msg: dict):
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:  # notification (e.g. notifications/initialized)
        return None
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "bda-evaluator", "version": "1"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s, _, _ in TOOLS]}
    elif method == "tools/call":
        name = params.get("name")
        if name not in ROUTES:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
        verb, path = ROUTES[name]
        args = params.get("arguments") or {}
        code, resp = ev.handle(verb, path, args if verb == "POST" else None)
        result = {"content": [{"type": "text", "text": json.dumps(resp)}], "isError": code != 200}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(ev, after=lambda: None) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            out = handle(ev, msg)
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()
        after()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--screen", default="IFNG")
    ap.add_argument("--rounds", type=int, default=30)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--anonymize", action="store_true")
    ap.add_argument("--features", choices=["screens", "depmap"], default="screens")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--secret-seed", action="store_true",
                    help="draw the ID-anonymization seed at random and keep it in memory; only its sha256 is written "
                         "until the episode ends (the agent's sandbox can read the repo, so a fixed seed is guessable)")
    ap.add_argument("--proposals-per-round", type=int, default=3)
    ap.add_argument("--lookups", type=int, default=4)
    ap.add_argument("--round-token-hashes", default="",
                    help="comma-separated sha256 hashes, one per round: gate each round on its token")
    ap.add_argument("--url", help="relay to a running evaluator.py instead of holding state here "
                                  "(needed for multi-turn runs: Codex restarts MCP servers every turn)")
    ap.add_argument("--out", help="required without --url")
    a = ap.parse_args()
    if a.url:
        serve(Relay(a.url))
        return
    gate = RoundGate([h for h in a.round_token_hashes.split(",") if h]) if a.round_token_hashes else None
    seed = int.from_bytes(os.urandom(4), "big") if a.secret_seed else a.seed
    env = BioEnv(a.screen, rounds=a.rounds, batch=a.batch, anonymize=a.anonymize, seed=seed, features=a.features)
    ev = Evaluator(env, a.out, a.proposals_per_round, a.lookups, gate)
    out_dir = Path(a.out)
    (out_dir / "config.json").write_text(json.dumps(vars(a)))
    if a.secret_seed:
        (out_dir / "seed_sha256.txt").write_text(hashlib.sha256(str(seed).encode()).hexdigest() + "\n")
    revealed = [not a.secret_seed]
    serve(ev, lambda: None if revealed[0] or not env.done else (
        (out_dir / "seed_revealed.txt").write_text(f"{seed}\n"), revealed.__setitem__(0, True)))


if __name__ == "__main__":
    main()
