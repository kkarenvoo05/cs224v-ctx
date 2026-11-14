"""Offline OS-level regression: no model requests, actual bundled macOS sandbox."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_policy import stage_guard
from runtime_codex_guard import apply_policy, filtered_args
from smoke_ours_runtime import PROBE


def fixture(tmp_path):
    runs = tmp_path / "runs"
    home = runs / "case/harness/codex_home"
    workspace = runs / "case/workspace"
    home.mkdir(parents=True)
    workspace.mkdir(parents=True)
    (home / "config.toml").write_text('model="gpt-6.1-terra"\nsandbox_mode="workspace-write"\napproval_policy="never"\n')
    return runs, home, workspace


def test_guard_rejects_user_home_and_keeps_other_settings(tmp_path):
    runs, home, workspace = fixture(tmp_path)
    policy = {"runs_root": str(runs), "tool_read_roots": []}
    apply_policy(home, policy)
    import tomllib
    cfg = tomllib.loads((home / "config.toml").read_text())
    assert "sandbox_mode" not in cfg and cfg["model"] == "gpt-6.1-terra"
    assert cfg["approval_policy"] == "on-request"
    assert cfg["approvals_reviewer"] == "auto_review"
    assert "Reject all sandbox escalation" in cfg["auto_review"]["extra_policy"]
    assert cfg["permissions"]["bda-restricted"]["filesystem"][":root"] == "deny"
    assert ":tmpdir" not in cfg["permissions"]["bda-restricted"]["filesystem"]
    assert cfg["shell_environment_policy"]["set"]["TMPDIR"] == str(workspace / ".agent_tmp")
    assert cfg["shell_environment_policy"]["set"]["TMPPREFIX"] == str(workspace / ".agent_tmp/zsh")
    apply_policy(home, policy)  # A second invocation must not duplicate policy sections.
    with pytest.raises(ValueError):
        apply_policy(tmp_path, policy)
    assert filtered_args(["exec", "-s", "workspace-write", "-c", 'approval_policy="never"']) == [
        "exec", "-c", 'approval_policy="on-request"']
    with pytest.raises(ValueError):
        filtered_args(["exec", "--dangerously-bypass-approvals-and-sandbox"])
    for override in (["exec", "--ignore-user-config"], ["exec", "-p", "other"],
                     ["exec", "--add-dir", str(tmp_path)],
                     ["exec", "-c", 'approvals_reviewer="user"'],
                     ["exec", "-c", 'permissions.bda-restricted.filesystem.":root"="read"']):
        with pytest.raises(ValueError):
            filtered_args(override)


@pytest.mark.skipif(sys.platform != "darwin", reason="Actual bundled macOS sandbox")
def test_actual_restricted_read_policy(tmp_path):
    runs, home, workspace = fixture(tmp_path)
    guard = stage_guard(tmp_path / "guard_bin", runs)
    hidden = tmp_path / "evaluator_only.txt"
    hidden.write_text("NOT_FOR_THE_AGENT")
    (workspace / "allowed.txt").write_text("PUBLIC")
    targets = [{"name": "allowed", "path": "allowed.txt"},
               {"name": "hidden", "path": str(hidden)}]
    (workspace / "targets.json").write_text(json.dumps(targets))
    (workspace / "probe.py").write_text(PROBE)
    python = Path(sys.base_prefix) / "bin/python3"
    result = subprocess.run([str(guard), "sandbox", "--", str(python), "probe.py"],
                            cwd=workspace, env=dict(os.environ, CODEX_HOME=str(home)),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr[-3000:]
    rows = json.loads((workspace / "probe_results.json").read_text())
    assert all(v["read"] for v in rows[0]["methods"].values())
    assert all(not v["read"] for v in rows[1]["methods"].values())
    command = "cat > progress.json <<'BDA_RECORD'\n{\"completed_rounds\": 3}\nBDA_RECORD\n"
    note = subprocess.run([str(guard), "sandbox", "--", "/bin/zsh", "-lc", command],
                          cwd=workspace, env=dict(os.environ, CODEX_HOME=str(home)),
                          capture_output=True, text=True, timeout=30)
    assert note.returncode == 0, note.stderr[-3000:]
    assert json.loads((workspace / "progress.json").read_text()) == {"completed_rounds": 3}


