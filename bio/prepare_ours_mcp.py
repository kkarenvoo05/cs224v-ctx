"""Write ours' documented stdio-server registry from evaluator connection details."""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--connection", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    connection = json.loads(a.connection.read_text())
    url = urlsplit(connection["url"])
    if url.scheme != "http" or url.hostname != "127.0.0.1" or url.path != "/v1" or not url.port:
        p.error("Expected a loopback evaluator /v1 endpoint")
    if not isinstance(connection["token"], str) or not connection["token"]:
        p.error("Missing evaluator bearer token")
    registry = {"bda": {"command": sys.executable,
                        "args": ["-I", str(Path(__file__).with_name("evaluator_mcp.py").resolve())],
                        "env": {"BDA_EVALUATOR_URL": connection["url"],
                                "BDA_EVALUATOR_TOKEN": connection["token"]}}}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(registry, f, indent=2)
    print(f"Wrote private MCP registry: {a.out}")


if __name__ == "__main__":
    main()
