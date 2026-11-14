"""Evaluator-owned BDA service for code-capable agents (e.g. the prototype harness).

The agent never gets the screen files, hit labels or the ID-to-symbol mapping: those stay
in this process. It talks to the service over HTTP on 127.0.0.1 (or with eval_client.py)
and can only:

    POST /propose   {"ids": [...]}  submit genes for the current round (limited calls/round)
    POST /end_round {}              close the round; returns scores + hit flags of accepted genes
    POST /lookup    {"ids": [...]}  similar genes (up to --lookups IDs per round)
    GET  /history                   every result the agent has already observed
    GET  /status                    round, batch, remaining budget
    GET  /help                      the text above, for the agent's instructions

Scores are revealed only at /end_round, as in llm_agent.py (the agent learns them next round).
Every request and response is appended to OUT/requests.jsonl; OUT/run.json is rewritten
atomically after each round with the same totals/curve fields as llm_agent.py, plus an
independent analyze.py-style recount.

Isolation: this only keeps hidden state out of the API. Run the agent in a folder that does
not contain this repo or the data (and check it can't read them) before trusting results.

Usage:
    bio/.venv/bin/python -I bio/evaluator.py --screen IFNG --rounds 30 --batch 16 --anonymize \
        --features depmap --seed 0 --port 8765 --out bio/runs/eval_NAME
"""
import argparse
import json
import sys
import threading
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import BioEnv  # noqa: E402

HELP = __doc__.split("Scores are revealed")[0].strip()


class Evaluator:
    def __init__(self, env: BioEnv, out: Path, proposals_per_round: int = 3, lookups_per_round: int = 4):
        self.env, self.out = env, Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        if (self.out / "requests.jsonl").exists() or (self.out / "run.json").exists():
            raise FileExistsError(f"Evaluator output already exists: {self.out}; choose a new --out")
        self.max_props, self.max_lookups = proposals_per_round, lookups_per_round
        self.props_used = self.lookups_used = 0
        self.lock = threading.Lock()
        self.n_requests = 0
        self.t0 = time.time()
        self._save()

    # ---- API ----------------------------------------------------------------
    def status(self) -> dict:
        e = self.env
        return {"round": e.round + 1 if not e.done else None, "rounds_total": e.rounds, "done": e.done,
                "batch": e.batch, "remaining_in_batch": None if e.done else e.remaining_in_batch(),
                "proposals_left": self.max_props - self.props_used,
                "lookups_left": self.max_lookups - self.lookups_used, "n_genes": len(e.ids),
                "tested": len(e.tested), "cum_hits": e.log[-1].cum_hits if e.log else 0}

    def propose(self, ids) -> dict:
        e = self.env
        if e.done:
            return {"error": "episode finished"}
        if self.props_used >= self.max_props:
            return {"error": f"proposal limit ({self.max_props}) reached for this round; call /end_round"}
        if not isinstance(ids, list) or len(ids) > 4 * e.batch:
            return {"error": f"ids must be a list of at most {4 * e.batch} IDs"}
        self.props_used += 1
        cur = e._cur
        before = {k: len(getattr(cur, k)) for k in ("accepted", "invalid", "repeats", "dup_in_batch", "overflow")}
        e.propose([str(g) for g in ids])
        new = {k: getattr(cur, k)[before[k]:] for k in before}
        return {"round": e.round + 1, "accepted": new["accepted"],
                "rejected": {"invalid": new["invalid"], "already_tested": new["repeats"],
                             "duplicate": new["dup_in_batch"], "over_batch": new["overflow"]},
                "remaining_in_batch": e.remaining_in_batch(), "proposals_left": self.max_props - self.props_used}

    def end_round(self) -> dict:
        e = self.env
        if e.done:
            return {"error": "episode finished"}
        log = e.end_round()
        self.props_used = self.lookups_used = 0
        self._save()
        return {"round": log.round + 1, "results": [{"id": g, "score": round(log.revealed[g], 4),
                                                     "hit": g in log.hits} for g in log.accepted],
                "short_by": e.batch - len(log.accepted), "cum_hits": log.cum_hits, "rounds_left": e.rounds - e.round}

    def lookup(self, ids) -> dict:
        if not isinstance(ids, list):
            return {"error": "ids must be a list"}
        left = self.max_lookups - self.lookups_used
        ids = [str(g) for g in ids][:left]
        self.lookups_used += len(ids)
        return {"neighbors": {g: [h for h, _ in self.env.lookup(g)] for g in ids},
                "lookups_left": self.max_lookups - self.lookups_used}

    def history(self) -> dict:
        e = self.env
        return {"results": [{"round": l.round + 1, "id": g, "score": round(l.revealed[g], 4), "hit": g in l.hits}
                            for l in e.log for g in l.accepted]}

    # ---- bookkeeping --------------------------------------------------------
    def record(self, method: str, path: str, body, resp: dict) -> None:
        self.n_requests += 1
        with open(self.out / "requests.jsonl", "a") as f:
            f.write(json.dumps({"i": self.n_requests, "t": round(time.time() - self.t0, 2), "round": self.env.round,
                                "method": method, "path": path, "body": body, "response": resp}) + "\n")

    def _save(self) -> None:
        e = self.env
        res = {"status": "complete" if e.done else "partial", "n_requests": self.n_requests,
               "wall_s": round(time.time() - self.t0, 1), "totals": e.totals(),
               "hit_ratio_recount": e.hit_ratio_by_analyze() if e.log else 0.0,
               "curve": [l.hit_ratio for l in e.log], "rounds": [asdict(l) for l in e.log], "tested": e.tested}
        tmp = self.out / "run.json.tmp"
        tmp.write_text(json.dumps(res))
        tmp.replace(self.out / "run.json")

    def handle(self, method: str, path: str, body) -> tuple[int, dict]:
        with self.lock:
            routes = {("GET", "/status"): lambda: self.status(), ("GET", "/history"): lambda: self.history(),
                      ("GET", "/help"): lambda: {"help": HELP},
                      ("POST", "/propose"): lambda: self.propose((body or {}).get("ids")),
                      ("POST", "/end_round"): lambda: self.end_round(),
                      ("POST", "/lookup"): lambda: self.lookup((body or {}).get("ids"))}
            fn = routes.get((method, path))
            resp = fn() if fn else {"error": f"unknown endpoint {method} {path}"}
            code = 404 if not fn else 400 if "error" in resp else 200
            self.record(method, path, body, resp)
            return code, resp


def make_server(ev: Evaluator, port: int = 0) -> HTTPServer:
    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send(*ev.handle("GET", self.path, None))

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                return self._send(413, {"error": "request too large"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "body must be JSON"})
            self._send(*ev.handle("POST", self.path, body))

        def log_message(self, *a):
            pass

    return HTTPServer(("127.0.0.1", port), H)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--screen", default="IFNG")
    ap.add_argument("--rounds", type=int, default=30)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--anonymize", action="store_true")
    ap.add_argument("--features", choices=["screens", "depmap"], default="screens")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--proposals-per-round", type=int, default=3, help="first proposal + retries")
    ap.add_argument("--lookups", type=int, default=4, help="lookup IDs per round")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    env = BioEnv(a.screen, rounds=a.rounds, batch=a.batch, anonymize=a.anonymize, seed=a.seed, features=a.features)
    ev = Evaluator(env, a.out, a.proposals_per_round, a.lookups)
    (Path(a.out) / "config.json").write_text(json.dumps(vars(a)))
    srv = make_server(ev, a.port)
    print(f"evaluator on http://127.0.0.1:{srv.server_address[1]}  ({len(env.ids)} genes, {a.rounds}x{a.batch})",
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
