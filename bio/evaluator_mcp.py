"""Standalone stdio MCP bridge to an evaluator-owned BDA HTTP service.

No evaluator imports, filesystem operations or access to hidden state. Supply
BDA_EVALUATOR_URL and BDA_EVALUATOR_TOKEN through the MCP server environment.
The agent's actual OS boundary still needs independent verification.
"""
import hashlib
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
import uuid

ACTIONS = ("catalog", "history", "propose", "lookup", "end_round")
TOOL = {"name": "bda", "description": (
    "Run a bounded BDA screen. catalog returns up to 256 opaque IDs, total_ids, "
    "id_min/id_max, numeric ID format and paging limits; propose accepts IDs and "
    "reveals their measured scores/hit flags; lookup returns feature neighbors; history "
    "reads observed results; end_round commits the round, even when short. Never retest IDs."),
    "inputSchema": {"type": "object", "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "args": {"type": "object", "description": (
            "catalog: {offset:0,limit:256} (both optional); history/end_round: {}; "
            "propose: {ids:[...]}; lookup: {id:...,k:8}")}},
        "required": ["action", "args"], "additionalProperties": False}}


class Bridge:
    def __init__(self, url, token):
        self.url, self.token = url, token
        self.session = uuid.uuid4().hex
        self.initialized = False
        # Never forward bearer tokens to an environment-configured HTTP proxy.
        self.opener = build_opener(ProxyHandler({}))

    def forward(self, rid, action, args):
        key = hashlib.sha256(json.dumps(rid, sort_keys=True).encode()).hexdigest()
        body = json.dumps({"request_id": self.session + key, "action": action,
                           "args": args}, allow_nan=False).encode()
        req = Request(self.url, method="POST", data=body, headers={
            "Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=10) as response:
                return False, json.load(response)
        except HTTPError as exc:
            return True, json.load(exc)
        except (URLError, OSError, ValueError):
            return True, {"error": "Evaluator unavailable; outcome may be unknown. Retry with the same request ID."}

    def handle(self, message):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32600, "message": "Invalid request"}}
        if "id" not in message:
            return None
        rid, method = message["id"], message.get("method")
        response = {"jsonrpc": "2.0", "id": rid}
        params = message.get("params", {})
        if not isinstance(params, dict):
            response["error"] = {"code": -32602, "message": "Invalid params"}
            return response
        if method == "initialize":
            version = params.get("protocolVersion")
            supported = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
            self.initialized = True
            response["result"] = {"protocolVersion": version if version in supported else supported[0],
                                  "capabilities": {"tools": {}},
                                  "serverInfo": {"name": "bda-evaluator", "version": "1.0.0"}}
        elif method == "ping":
            response["result"] = {}
        elif not self.initialized:
            response["error"] = {"code": -32000, "message": "Initialize first"}
        elif method == "tools/list":
            response["result"] = {"tools": [TOOL]}
        elif method == "tools/call":
            args = params.get("arguments", {})
            if (params.get("name") != "bda" or not isinstance(args, dict)
                    or set(args) != {"action", "args"}
                    or args.get("action") not in ACTIONS or not isinstance(args.get("args"), dict)):
                response["error"] = {"code": -32602, "message": "Invalid tool or arguments"}
            else:
                failed, data = self.forward(rid, args["action"], args["args"])
                response["result"] = {"content": [{"type": "text", "text": json.dumps(data)}],
                                      "isError": failed}
        else:
            response["error"] = {"code": -32601, "message": "Method not found"}
        return response


def main():
    bridge = Bridge(os.environ["BDA_EVALUATOR_URL"], os.environ["BDA_EVALUATOR_TOKEN"])
    while True:
        line = sys.stdin.buffer.readline(65537)
        if not line:
            break
        if len(line) > 65536:
            return  # Reject oversized messages without forwarding anything.
        try:
            def reject_constant(value):
                raise ValueError("Nonfinite JSON")
            response = bridge.handle(json.loads(line, parse_constant=reject_constant))
        except (ValueError, TypeError):
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "Invalid JSON message"}}
        if response is not None:
            print(json.dumps(response, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
