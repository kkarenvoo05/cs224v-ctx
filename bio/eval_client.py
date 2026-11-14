"""Agent-side client for evaluator.py. Needs only the Python standard library, so it can be
copied alone into the agent's working folder. The server URL comes from EVAL_URL
(default http://127.0.0.1:8765).

    python3 eval_client.py status
    python3 eval_client.py propose G00012,G00345,...
    python3 eval_client.py end_round
    python3 eval_client.py lookup G00012,G00345
    python3 eval_client.py history
    python3 eval_client.py help
"""
import json
import os
import sys
import urllib.request

URL = os.environ.get("EVAL_URL", "http://127.0.0.1:8765")


def call(path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(URL + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("status", "propose", "end_round", "lookup", "history", "help"):
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    ids = [g.strip() for g in ",".join(rest).replace(" ", ",").split(",") if g.strip()]
    if cmd in ("propose", "lookup"):
        out = call("/" + cmd, {"ids": ids})
    elif cmd == "end_round":
        out = call("/end_round", {})
    else:
        out = call("/" + cmd)
    print(out.get("help") if cmd == "help" else json.dumps(out, indent=1))
    return 1 if "error" in out else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
