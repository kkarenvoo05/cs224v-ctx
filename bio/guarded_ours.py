"""Prepare or execute one certificate-gated BDA runtime arm, with enforced caps.

Start a fresh evaluator separately and provide its private MCP registry. Defaults
to preparation only; --execute starts the model run. Never uses the API lane.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_policy import stage_guard


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--harness", choices=["codex", "codex-shipped"], required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", type=Path, required=True, help="Public seed only")
    p.add_argument("--prompt-file", type=Path, required=True)
    p.add_argument("--mcp-servers", type=Path, required=True)
    p.add_argument("--task", default="bda-pilot")
    p.add_argument("--wall-clock-s", type=int, default=1800)
    p.add_argument("--follow-ups-file", type=Path,
                   help="JSON list of later user messages (one per gated round), passed as --follow-up")
    p.add_argument("--execute", action="store_true")
    a = p.parse_args()
    bio = Path(__file__).resolve().parent
    setup = json.loads((bio / "runtime_setup/setup.json").read_text())
    if not setup["benchmark_ready"] or not setup["usage_policy"]["pilot_enabled"]:
        p.error("Pilot readiness/usage gate is closed")
    certificate = json.loads((bio.parent / setup["verification_report"]).read_text())
    guard_hash = hashlib.sha256((bio / "runtime_codex_guard.py").read_bytes()).hexdigest()
    if not certificate["benchmark_ready"] or any(
            certificate[arm]["policy_guard_sha256"] != guard_hash for arm in ("prototype", "baseline")):
        p.error("Guard changed or the two-arm restricted-read certificate is invalid; recertify")
    review = json.loads((bio.parent / setup["approval_denial_report"]).read_text())
    if not review["passed"] or any(
            review[arm]["policy_guard_sha256"] != guard_hash for arm in ("prototype", "baseline")):
        p.error("Escalated evaluator-read denial is not certified in both arms; recertify")
    pinned = (Path.home() / ".ours/pinned").read_text().strip()
    if pinned != setup["release"]:
        p.error("Runtime release is no longer pinned to the certified version")
    maximum = setup["usage_policy"]["pilot_proposed_wall_clock_s_per_arm"]
    if not 1 <= a.wall_clock_s <= maximum:
        p.error(f"--wall-clock-s must be 1..{maximum}")
    out = a.out.resolve()
    if not out.is_relative_to(bio / "runtime_setup/private"):
        p.error("Raw runtime outputs must be under bio/runtime_setup/private")
    seed = a.seed.resolve()
    if not seed.is_dir() or any(x.is_symlink() for x in seed.rglob("*")):
        p.error("Seed must be a public directory without symlinks")
    registry = json.loads(a.mcp_servers.read_text())
    if set(registry) != {"bda"}:
        p.error("Only the certified bda MCP bridge is allowed")
    supplied = registry["bda"]
    args = supplied.get("args", [])
    if len(args) != 2 or args[0] != "-I" or Path(args[1]).resolve() != bio / "evaluator_mcp.py":
        p.error("Generate a registry with bio/prepare_ours_mcp.py")
    env = supplied.get("env", {})
    if set(env) != {"BDA_EVALUATOR_URL", "BDA_EVALUATOR_TOKEN"}:
        p.error("Unexpected MCP environment")
    os.umask(0o077)
    out.mkdir(parents=True, exist_ok=False)
    guard = stage_guard(out / "guard_bin", out / "runs")
    policy = json.loads(guard.with_name("policy.json").read_text())
    roots = sorted(str(x).replace(str(guard.parent), ":guard_tools") for x in policy["tool_read_roots"])
    if roots != sorted(certificate["prototype"]["tool_read_roots"]):
        p.error("Tool read roots differ from the certified policy; recertify")
    bridge = guard.parent / "evaluator_mcp.py"
    shutil.copyfile(bio / "evaluator_mcp.py", bridge)
    private_registry = out / "mcp.json"
    private_registry.write_text(json.dumps({"bda": {
        "command": str(Path(sys.base_prefix) / "bin/python3"),
        "args": ["-I", str(bridge)], "env": env}}, indent=2))
    command = [str(Path.home() / ".ours/bin/ours"), "run", "--harness", a.harness,
               "--model", setup["model"], "--context-window", str(setup["context_window"]),
               "--reasoning-effort", setup["reasoning_effort"], "--lane", "subscription",
               "--prompt", a.prompt_file.read_text(), "--task", a.task, "--seed", str(seed),
               "--mcp-servers", str(private_registry), "--wall-clock-s", str(a.wall_clock_s),
               "--runs-root", str(out / "runs"), "--codex-bin", str(guard)]
    if a.follow_ups_file:
        follow = json.loads(a.follow_ups_file.read_text())
        if not isinstance(follow, list) or not all(isinstance(x, str) for x in follow):
            p.error("--follow-ups-file must be a JSON list of strings")
        for msg in follow:
            command.extend(["--follow-up", msg])
    if a.harness == "codex":
        info = out / "model_info"
        shutil.copytree(bio / "runtime_setup/model_info", info)
        command.extend(["--model-info-dir", str(info)])
    (out / "invocation.json").write_text(json.dumps(command, indent=2))
    print(f"Prepared certified {a.harness} arm at {out}; wall cap={a.wall_clock_s}s", flush=True)
    if not a.execute:
        print("Preparation only. No model calls made.")
        return
    with (out / "runner.log").open("w") as log:
        process = subprocess.Popen(command, cwd=out, stdout=log, stderr=log, start_new_session=True)
        try:
            rc = process.wait(timeout=a.wall_clock_s + 30)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
