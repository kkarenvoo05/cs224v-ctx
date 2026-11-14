"""Stage the shared, version-checked Codex policy adapter for a run batch."""
import hashlib
import json
from pathlib import Path
import shutil
import sys


def stage_guard(directory, runs_root):
    directory, runs_root = Path(directory).resolve(), Path(runs_root).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    bio = Path(__file__).resolve().parent
    settings = json.loads((bio / "runtime_setup/setup.json").read_text())
    version = Path.home() / ".ours/versions" / settings["release"]
    binary = version / "codex/bin/codex"
    if hashlib.sha256(binary.read_bytes()).hexdigest() != settings["bundled_codex_sha256"]:
        raise ValueError("Pinned Codex binary does not match the setup manifest")
    roots = [version, directory, Path(sys.base_prefix), Path("/Library/Frameworks/Python.framework")]
    roots = sorted({str(path.resolve()) for path in roots if path.exists()})
    policy = {"codex_binary": str(binary), "codex_sha256": settings["bundled_codex_sha256"],
              "runs_root": str(runs_root), "tool_read_roots": roots}
    (directory / "policy.json").write_text(json.dumps(policy, indent=2))
    guard = directory / "codex"
    shutil.copyfile(bio / "runtime_codex_guard.py", guard)
    guard.chmod(0o700)
    (directory / "codex-code-mode-host").symlink_to(version / "codex/bin/codex-code-mode-host")
    return guard
