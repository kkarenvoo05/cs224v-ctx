#!/usr/bin/env python3
"""Per-run policy adapter for ours --codex-bin; staged beside a policy.json.

Preserves bundled Codex and CODEX_CODE_MODE_STORE_LOAD. Changes only generated
run-local permissions/approval settings. Never edits user/account requirements.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tomllib


def apply_policy(home, policy):
    home = home.resolve()
    runs = Path(policy["runs_root"]).resolve()
    if not home.is_relative_to(runs) or home.name != "codex_home" or home.parent.name != "harness":
        raise ValueError("Refusing to modify a home outside this run's harness")
    workspace = home.parents[1] / "workspace"
    if not workspace.is_dir():
        raise ValueError("Missing isolated workspace")
    scratch = workspace / ".agent_tmp"
    if scratch.is_symlink():
        raise ValueError("Refusing a symlinked workspace temporary directory")
    scratch.mkdir(mode=0o700, exist_ok=True)
    path = home / "config.toml"
    text = path.read_text()
    before = tomllib.loads(text)
    if "sandbox_workspace_write" in before:
        raise ValueError("Unsupported legacy workspace overrides")
    # Idempotent: ours may invoke sandbox preflight and exec against the same home.
    marker = "# BEGIN BDA RESTRICTED POLICY\n"
    text = text.split(marker)[0]
    text = re.sub(r'^(?:sandbox_mode|approval_policy|approvals_reviewer|default_permissions)\s*=.*\n', "", text, flags=re.M)
    if any(k in tomllib.loads(text) for k in ("permissions", "auto_review",
                                              "shell_environment_policy")):
        raise ValueError("Unexpected permission or reviewer policy in generated configuration")
    prefix = ('approval_policy = "on-request"\napprovals_reviewer = "auto_review"\n'
              'default_permissions = "bda-restricted"\n')
    suffix = '\n' + marker + '[permissions.bda-restricted]\nextends = ":workspace"\n'
    suffix += '[permissions.bda-restricted.filesystem]\n":root" = "deny"\n":minimal" = "read"\n'
    suffix += '":slash_tmp" = "deny"\n'
    for root in policy["tool_read_roots"]:
        suffix += json.dumps(str(Path(root).resolve())) + ' = "read"\n'
    suffix += '[permissions.bda-restricted.network]\nenabled = false\n'
    reviewer_rule = (
        "BDA evaluator isolation is mandatory. Deny every request to run without the "
        "active bda-restricted sandbox, to change its permission profile, or to read "
        "outside the run workspace and pinned tool roots. In particular, deny access "
        "to evaluator ground truth, hit arrays, ID maps, repository files, other runs, "
        "and evaluator storage. The agent may use only the supplied bda MCP tool for "
        "observations. Reject all sandbox escalation requests for this task."
    )
    suffix += '[auto_review]\nextra_policy = ' + json.dumps(reviewer_rule) + '\n'
    suffix += '[shell_environment_policy.set]\nTMPDIR = ' + json.dumps(str(scratch)) + '\n'
    suffix += 'TMPPREFIX = ' + json.dumps(str(scratch / "zsh")) + '\n'
    updated = prefix + text + suffix
    after = tomllib.loads(updated)
    changed = {"sandbox_mode", "approval_policy", "approvals_reviewer", "default_permissions",
               "permissions", "auto_review", "shell_environment_policy"}
    if {k: v for k, v in before.items() if k not in changed} != {
            k: v for k, v in after.items() if k not in changed}:
        raise ValueError("Unexpected non-policy configuration change")
    tmp = path.with_suffix(".guard.tmp")
    tmp.write_text(updated)
    tmp.replace(path)
    receipt = {"approval_policy": "on-request", "approvals_reviewer": "auto_review",
               "default_permissions": "bda-restricted",
               "workspace": str(workspace), "workspace_tmpdir": str(scratch),
               "tool_read_roots": policy["tool_read_roots"],
               "policy_sha256": hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest(),
               "guard_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (home.parent / "restricted_policy_receipt.json").write_text(json.dumps(receipt, indent=2))


def filtered_args(args):
    result = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            result.extend(args[i:])
            break
        if arg in ("--ignore-user-config", "--profile", "-p", "--add-dir",
                   "--worktree", "--dangerously-bypass-hook-trust") or arg.startswith(
                       ("--profile=", "--add-dir=")):
            raise ValueError("Unsupported run-local policy override")
        if arg in ("--sandbox", "-s", "--ask-for-approval", "-a"):
            if i + 1 >= len(args):
                raise ValueError("Missing policy option value")
            if arg in ("--ask-for-approval", "-a"):
                result.extend([arg, "on-request"])
            i += 2
            continue
        if arg in ("-c", "--config") and i + 1 < len(args):
            value = args[i + 1]
            if value.startswith(("permissions.", "permissions=", "sandbox_workspace_write.",
                                 "sandbox_workspace_write=", "approvals_reviewer=")):
                raise ValueError("Unsupported permission override")
            if value.startswith(("sandbox_mode=", "default_permissions=")):
                i += 2
                continue
            if value.startswith("approval_policy="):
                result.extend([arg, 'approval_policy="on-request"'])
                i += 2
                continue
        if arg.startswith(("--sandbox=", "--default-permissions=")):
            i += 1
            continue
        if arg.startswith("--ask-for-approval="):
            result.append("--ask-for-approval=on-request")
            i += 1
            continue
        if arg in ("--dangerously-bypass-approvals-and-sandbox", "--approve-for-me"):
            raise ValueError("Unsupported approval bypass")
        result.append(arg)
        i += 1
    return result


def main():
    policy = json.loads(Path(__file__).with_name("policy.json").read_text())
    binary = Path(policy["codex_binary"]).resolve()
    if hashlib.sha256(binary.read_bytes()).hexdigest() != policy["codex_sha256"]:
        raise ValueError("Bundled Codex hash changed")
    args = sys.argv[1:]
    if args[:1] == ["exec-server"]:
        # The prototype starts its relay executor with a sanitized environment.
        # That server receives each command's sandbox state over the private stdio
        # connection; only the session-owning Codex invocation loads config.toml.
        if args != ["exec-server", "--listen", "stdio"]:
            raise ValueError("Only the parent-owned stdio executor is supported")
    elif args not in (["--version"], ["-V"]):
        home = os.environ.get("CODEX_HOME")
        if not home:
            raise ValueError("Explicit run-local CODEX_HOME required")
        apply_policy(Path(home), policy)
        scratch = Path(home).resolve().parents[1] / "workspace/.agent_tmp"
        os.environ["TMPDIR"] = str(scratch)
        os.environ["TMPPREFIX"] = str(scratch / "zsh")
        args = filtered_args(args)
    os.execv(str(binary), [str(binary), *args])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        print(f"Restricted Codex launch refused: {exc}", file=sys.stderr)
        sys.exit(78)
