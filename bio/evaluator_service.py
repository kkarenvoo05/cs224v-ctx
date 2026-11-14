"""Evaluator-owned HTTP API. This is not an adapter for the undocumented ours interface.

Run in a process/filesystem inaccessible to the agent. Loopback and a bearer token
authenticate requests; they do NOT isolate files from another process of the same user.
No resume: each invocation requires a fresh output directory.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import BioEnv


class Evaluator:
    def __init__(self, env, out, *, max_proposals=3, max_lookups=8, max_requests=10000, round_token_hashes=None):
        if not env.anonymize:
            raise ValueError("Service requires opaque IDs")
        if min(max_proposals, max_lookups, max_requests) < 1:
            raise ValueError("Budgets must be positive")
        self.env = env
        self.out = Path(out)
        self.out.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.max_proposals, self.max_lookups = max_proposals, max_lookups
        self.max_requests = max_requests
        self.proposals = self.lookups = self.requests = 0
        self.cache = {}
        # Optional gate: round k opens only with the token sent in that round's user message
        # (sha256 hashes only), so a script from an earlier agent turn cannot run later rounds.
        self.round_token_hashes, self.opened = list(round_token_hashes or []), set()
        self.trace = (self.out / "requests.jsonl").open("x")
        self.snapshot()

    def snapshot(self):
        env = self.env
        obj = {"status": "complete" if env.done else "partial",
               "totals": env.totals(), "rounds": [asdict(x) for x in env.log],
               "curve": [x.hit_ratio for x in env.log],
               "independent_hit_ratio": env.hit_ratio_by_analyze(),
               "current": asdict(env._cur), "tested": env.tested,
               "budgets": {"max_proposals_per_round": self.max_proposals,
                           "max_lookups_per_round": self.max_lookups,
                           "max_requests": self.max_requests},
               "requests": self.requests}
        tmp = self.out / "run.json.tmp"
        with tmp.open("w") as f:
            json.dump(obj, f, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(self.out / "run.json")

    def observations(self):
        env = self.env
        logs = [*env.log, env._cur]
        return [{"id": g, "round": log.round + 1, "score": log.revealed[g],
                 "hit": g in log.hits} for log in logs for g in log.accepted]

    def dispatch(self, action, args):
        env = self.env
        fields = {"catalog": {"offset", "limit"}, "history": set(), "propose": {"ids", "round_token"},
                  "lookup": {"id", "k"}, "end_round": set()}
        if action not in fields or set(args) - fields[action]:
            raise ValueError("Unknown action or arguments")
        if action == "catalog":
            offset, limit = args.get("offset", 0), args.get("limit", 256)
            if type(offset) is not int or offset < 0 or offset >= len(env.ids):
                raise ValueError("Catalog offset out of range")
            if type(limit) is not int or not 1 <= limit <= 256:
                raise ValueError("Catalog limit must be 1..256")
            ids = sorted(env.ids)
            page = ids[offset:offset + limit]
            next_offset = offset + len(page)
            return {"ids": page, "total_ids": len(ids),
                    "next_offset": next_offset if next_offset < len(ids) else None,
                    "id_format": "G%05d", "id_min": ids[0], "id_max": ids[-1],
                    "rounds": env.rounds, "batch": env.batch,
                    "proposal_calls_per_round": self.max_proposals,
                    "lookup_calls_per_round": self.max_lookups}
        if action == "history":
            return {"observations": self.observations(), "round": env.round + 1,
                    "done": env.done, "remaining": 0 if env.done else env.remaining_in_batch()}
        if env.done:
            raise ValueError("Episode finished")
        if action == "lookup":
            g, k = args.get("id"), args.get("k", 8)
            if not isinstance(g, str) or g not in env.index:
                raise ValueError("Unknown opaque ID")
            if type(k) is not int or not 1 <= k <= min(32, len(env.ids) - 1):
                raise ValueError("k out of range")
            if self.lookups >= self.max_lookups:
                raise ValueError("Lookup budget exhausted")
            self.lookups += 1
            return {"neighbors": [{"id": g, "distance": float(d)} for g, d in env.lookup(g, k)]}
        if action == "propose":
            ids = args.get("ids")
            if not isinstance(ids, list) or not 1 <= len(ids) <= env.batch or any(
                    not isinstance(g, str) or len(g) > 64 for g in ids):
                raise ValueError("ids must contain 1..batch short strings")
            if self.proposals >= self.max_proposals:
                raise ValueError("Proposal/retry budget exhausted; end the round")
            k = env.round + 1
            if self.round_token_hashes and k not in self.opened:
                token = args.get("round_token")
                want = self.round_token_hashes[k - 1] if k <= len(self.round_token_hashes) else None
                if not isinstance(token, str) or want is None or not hmac.compare_digest(
                        hashlib.sha256(token.encode()).hexdigest(), want):
                    raise ValueError(f"Round {k} is not open: pass the round_token from the user message for "
                                     f"round {k}. If you have not received it yet, stop and wait for the next message.")
                self.opened.add(k)
            self.proposals += 1
            cur = env.propose(ids)
            return {"accepted": list(cur.accepted), "observations": [
                        x for x in self.observations() if x["round"] == env.round + 1],
                    "invalid": list(cur.invalid), "repeats": list(cur.repeats),
                    "duplicates": list(cur.dup_in_batch), "overflow": list(cur.overflow),
                    "remaining": env.remaining_in_batch()}
        env.end_round()
        self.proposals = self.lookups = 0
        out = {"completed_round": env.round, "done": env.done}
        if self.round_token_hashes and not env.done:
            out["next"] = "Round closed. Stop and end your turn; the next user message gives the next round's token."
        return out

    def request(self, body):
        # Request IDs make exact transport retries idempotent. Failed requests also
        # count against the global budget. Responses never contain evaluation totals.
        self.requests += 1
        if self.requests > self.max_requests:
            status, response = 429, {"error": "Request budget exhausted"}
        else:
            status, response = 400, {"error": "Invalid request envelope"}
            if isinstance(body, dict) and set(body) == {"request_id", "action", "args"}:
                rid, action, args = body["request_id"], body["action"], body["args"]
                if isinstance(rid, str) and 1 <= len(rid) <= 128 and isinstance(action, str) and isinstance(args, dict):
                    canonical = json.dumps(body, sort_keys=True)
                    if rid in self.cache:
                        old, status, response = self.cache[rid]
                        if canonical != old:
                            status, response = 409, {"error": "Request ID reused with different content"}
                    else:
                        try:
                            response = self.dispatch(action, args)
                            status = 200
                        except ValueError as exc:
                            response = {"error": str(exc)}
                        self.cache[rid] = (canonical, status, response)
        self.record(body, status, response)
        return status, response

    def record(self, body, status, response):
        json.dump({"time": time.time(), "request": body, "status": status,
                   "response": response}, self.trace, allow_nan=False)
        self.trace.write("\n")
        self.trace.flush()
        os.fsync(self.trace.fileno())
        self.snapshot()


def handler(evaluator, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # No bearer headers in logs.

        def do_POST(self):
            self.connection.settimeout(10)
            response, status = {"error": "Unauthorized"}, 401
            if hmac.compare_digest(self.headers.get("Authorization", "").encode(), ("Bearer " + token).encode()):
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if self.path != "/v1" or not 0 < size <= 65536:
                        raise ValueError("Invalid path or body length")
                    def reject_constant(value):
                        raise ValueError("Nonfinite JSON value")
                    body = json.loads(self.rfile.read(size), parse_constant=reject_constant)
                except (ValueError, OSError):
                    status, response = 400, {"error": "Invalid JSON request"}
                    evaluator.record({"transport_error": True}, status, response)
                else:
                    status, response = evaluator.request(body)
            else:
                evaluator.record({"unauthorized": True}, status, response)
            data = json.dumps(response, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True, help="Evaluator-only fresh output directory")
    p.add_argument("--screen", default="IFNG")
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--max-proposals", type=int, default=3)
    p.add_argument("--max-lookups", type=int, default=8)
    p.add_argument("--max-requests", type=int, default=10000)
    p.add_argument("--round-token-hashes", default="",
                   help="comma-separated sha256 per round: one agent turn per round (see run_paired_pilot --gate)")
    a = p.parse_args()
    if a.rounds < 1 or a.batch < 1:
        p.error("rounds and batch must be positive")
    os.umask(0o077)
    env = BioEnv(a.screen, rounds=a.rounds, batch=a.batch, anonymize=True,
                 seed=a.seed, features="depmap")
    e = Evaluator(env, a.out, max_proposals=a.max_proposals,
                  max_lookups=a.max_lookups, max_requests=a.max_requests,
                  round_token_hashes=[h for h in a.round_token_hashes.split(",") if h])
    import platform
    from env import DATA_DIR, DEPMAP_CSV
    from validate_depmap import sha256
    config = {"args": vars(a), "platform": platform.platform(),
              "python": platform.python_version(), "features_sha256": sha256(DEPMAP_CSV),
              "ground_truth_sha256": sha256(DATA_DIR / f"ground_truth_{a.screen}.csv"),
              "hits_sha256": sha256(DATA_DIR / f"topmovers_{a.screen}.npy"),
              "code_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                              (Path(__file__), Path(__file__).with_name("env.py"))}}
    (e.out / "config.json").write_text(json.dumps(config, indent=2))
    token = secrets.token_urlsafe(32)
    server = HTTPServer(("127.0.0.1", a.port), handler(e, token))
    (e.out / "connection.json").write_text(json.dumps({
        "url": f"http://127.0.0.1:{server.server_port}/v1", "token": token}))
    print(f"Ready; connection details in {e.out / 'connection.json'}", flush=True)
    try:
        server.serve_forever()
    finally:
        e.trace.close()
        server.server_close()


if __name__ == "__main__":
    main()
