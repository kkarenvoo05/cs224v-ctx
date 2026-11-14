"""Audit one `ours run` folder: tool use, context size per request, compaction, and reads outside the workspace.

    python3 -I ours/audit_trace.py ours/runs/<run>            # prints a summary, writes <run>/audit.json

- Tool calls: counted by tool (MCP calls to the bda server vs. shell commands).
- Context: input tokens of every model request and every compaction, from the Codex session log
  (harness/codex_home/sessions), which both harnesses (codex, codex-shipped) write.
- Isolation: every shell command and code-mode (JS) snippet is flagged if it mentions a path outside the workspace or names
  project files (screen data, evaluator code, eval logs). macOS's sandbox lets the agent read the
  whole disk, so this is detection, not prevention; check every flag by hand.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

SUSPECT = re.compile(r"cs224v-ctx(?!/ours/runs/[^/\s]+/workspace)|feasibility|biodiscoveryagent|achilles|depmap|"
                     r"env\.py|evaluator|bda_mcp|/evals/|seed_|\.ours|\.\./|~/|\$HOME|/Users/(?!\S*/workspace)", re.I)


def main(run: Path) -> dict:
    ws = str(run / "workspace")
    tools, flags = Counter(), []
    for a in sorted(run.glob("trace/*/call_*/action.json")):
        act = json.loads(a.read_text())
        name = act.get("tool") or "?"
        if name == "exec_command":
            cmd = act.get("arguments", {}).get("cmd")
            text = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            tools["shell"] += 1
            if SUSPECT.search(text.replace(ws, "<workspace>")):
                flags.append({"call": str(a.parent.relative_to(run)), "cmd": text[:400]})
        elif name == "exec":  # code mode: JS that calls tools (and could use fs/child_process)
            text = str(act.get("arguments", {}).get("input", ""))
            tools["js"] += 1
            if SUSPECT.search(text.replace(ws, "<workspace>")) or re.search(r"\brequire\(|\bimport\(|readFile|child_process", text):
                flags.append({"call": str(a.parent.relative_to(run)), "js": text[:400]})
        else:
            tools[name] += 1

    # Context per model request and compaction events, from the Codex session log (both harnesses).
    tokens, compactions, window = [], [], None
    for f in sorted(run.glob("harness/codex_home/sessions/**/*.jsonl")):
        for line in f.read_text().splitlines():
            x = json.loads(line)
            p = x.get("payload") if isinstance(x.get("payload"), dict) else {}
            if x.get("type") == "compacted":
                compactions.append({"after_request": len(tokens), "tokens_before": tokens[-1] if tokens else None})
            elif p.get("type") == "token_count" and p.get("info"):
                info = p["info"]
                window = info.get("model_context_window", window)
                last = (info.get("last_token_usage") or {}).get("input_tokens")
                if last is not None and (not tokens or info.get("total_token_usage") != getattr(main, "_prev", None)):
                    tokens.append(last)
                main._prev = info.get("total_token_usage")
    for c in compactions:
        i = c["after_request"]
        c["tokens_after"] = tokens[i] if i < len(tokens) else None
    out = {"run": run.name, "status": json.loads((run / "run.json").read_text()).get("exit_reason"),
           "harness": json.loads((run / "run.json").read_text()).get("harness", {}).get("name"),
           "tool_calls": dict(tools), "requests": len(tokens), "effective_context_window": window,
           "input_tokens_per_request": tokens, "max_input_tokens": max(tokens or [0]),
           "compactions": compactions, "isolation_flags": flags}
    (run / "audit.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    o = main(Path(sys.argv[1]).resolve())
    print(json.dumps({k: v for k, v in o.items() if k != "input_tokens_per_request"}, indent=1))
    print("input tokens:", o["input_tokens_per_request"])
