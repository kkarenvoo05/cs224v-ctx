"""Run one guarded prototype/baseline pair on fresh, identical evaluators.

Each arm gets its own evaluator service (same screen/size/seed), a private MCP
registry and the certified launcher; the service is stopped after its arm.
Arm order alternates by seed. Then writes the credential-free paired report.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

BIO = Path(__file__).resolve().parent
REPO = BIO.parent
PYTHON = BIO / ".venv/bin/python"
ARMS = {"prototype": "codex", "baseline": "codex-shipped"}


def run_arm(root, arm, a):
    evaluator_out = root / f"{arm}_evaluator"
    service = subprocess.Popen(
        [str(PYTHON), "-B", str(BIO / "evaluator_service.py"), "--out", str(evaluator_out),
         "--screen", a.screen, "--rounds", str(a.rounds), "--batch", str(a.batch),
         "--seed", str(a.seed), "--max-proposals", "3", "--max-lookups", "8",
         "--max-requests", "10000"],
        cwd=REPO, stdout=(root / f"{arm}_evaluator.log").open("w"), stderr=subprocess.STDOUT)
    try:
        connection = evaluator_out / "connection.json"
        for _ in range(600):
            if connection.exists() or service.poll() is not None:
                break
            time.sleep(0.5)
        if not connection.exists():
            raise RuntimeError(f"{arm} evaluator did not start")
        registry = root / f"{arm}_mcp.json"
        subprocess.run([str(PYTHON), str(BIO / "prepare_ours_mcp.py"), "--connection",
                        str(connection), "--out", str(registry)], check=True)
        rc = subprocess.run(
            [str(PYTHON), str(BIO / "guarded_ours.py"), "--harness", ARMS[arm],
             "--out", str(root / f"{arm}_agent"), "--seed", str(root / "public_seed"),
             "--prompt-file", str(a.prompt_file), "--mcp-servers", str(registry),
             "--task", f"{a.screen.lower()}-{a.rounds}x{a.batch}-seed{a.seed}",
             "--wall-clock-s", str(a.wall_clock_s)] + ([] if a.prepare_only else ["--execute"])).returncode
        print(f"{arm} arm exited {rc}", flush=True)
        if rc != 0:
            raise SystemExit(f"{arm} arm failed (exit {rc}); pair aborted, no report written. "
                             f"See {root / f'{arm}_agent/runner.log'}")
    finally:
        service.terminate()
        service.wait(timeout=30)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--screen", default="IFNG")
    p.add_argument("--rounds", type=int, default=100)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--prompt-file", type=Path, default=BIO / "pilot_100x32_prompt.md")
    p.add_argument("--wall-clock-s", type=int, default=3600)
    p.add_argument("--tag", required=True, help="Run date tag, e.g. 20261110")
    p.add_argument("--prepare-only", action="store_true", help="Check every gate; no model calls")
    a = p.parse_args()
    name = f"pilot_{a.rounds}x{a.batch}_seed{a.seed}_{a.tag}"
    root = BIO / "runtime_setup/private" / name
    report = BIO / "runs" / f"paired_{a.rounds}x{a.batch}_seed{a.seed}_{a.tag}.json"
    if report.exists():
        p.error(f"Report already exists: {report}")
    root.mkdir(parents=True, exist_ok=False)
    (root / "public_seed").mkdir()
    (root / "public_seed/README.txt").write_text(
        f"Public agent workspace for paired {a.screen} {a.rounds}x{a.batch} pilot. No evaluator state.\n")
    order = ["prototype", "baseline"] if a.seed % 2 == 0 else ["baseline", "prototype"]
    (root / "arm_order.json").write_text(json.dumps(order))
    for arm in order:
        run_arm(root, arm, a)
    if a.prepare_only:
        return
    subprocess.run([str(PYTHON), str(BIO / "analyze_paired_pilot.py"), "--root", str(root),
                    "--out", str(report)], check=True)


if __name__ == "__main__":
    main()
