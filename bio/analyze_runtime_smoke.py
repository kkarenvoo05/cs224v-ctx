"""Export a credential-free comparison from private real-runtime smoke artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_arm(root):
    paths = list(root.glob("*/run.json"))
    if len(paths) != 1:
        raise ValueError("Expected one runtime run in each supplied runs root")
    path = paths[0]
    run = json.loads(path.read_text())
    if run["exit_reason"] != "completed":
        raise ValueError("Only compare completed smoke runs")
    cfg = tomllib.loads((path.parent / "harness/codex_home/config.toml").read_text())
    catalog = json.loads((path.parent / "harness/codex_home/model_catalog.json").read_text())
    name = run["harness"]["name"]
    arm = path.parents[2]
    original = next(x for x in json.loads((arm.parent / "report.json").read_text())
                    if x["harness"] == name)
    probes = original["filesystem_probes"]
    outside = [x for x in probes if x["name"] != "allowed" and x["hash_verified"]]
    histories = [json.loads(line) for line in
                 (arm / "evaluator_private/episode/requests.jsonl").read_text().splitlines()]
    sessions = list((path.parent / "harness/codex_home").glob("sessions/**/*.jsonl"))
    records = []
    for session in sessions:
        candidate = [json.loads(line) for line in session.read_text().splitlines()]
        meta = next((x["payload"] for x in candidate if x.get("type") == "session_meta"), {})
        if meta.get("source") == "exec" and "parent_thread_id" not in meta:
            records.extend(candidate)
    contexts = [x["payload"] for x in records if x["type"] == "turn_context"]
    errors = [json.loads(line).get("item", {}) for line in
              (path.parent / "harness/exec.jsonl").read_text().splitlines()
              if json.loads(line).get("item", {}).get("type") == "error"]
    final_observations = histories[-1]["response"]["observations"]
    usage = run.get("usage", {})
    receipt_file = path.parent / "harness/restricted_policy_receipt.json"
    receipt = json.loads(receipt_file.read_text()) if receipt_file.exists() else None
    guard = Path(run["harness"]["settings"]["codex_bin"])
    guard_policy = json.loads(guard.with_name("policy.json").read_text()) if receipt else None

    def normalize(value):
        if isinstance(value, dict):
            return {normalize(k): normalize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [normalize(x) for x in value]
        if isinstance(value, str):
            for old, new in ((str(path.parent / "workspace"), ":workspace"),
                             (str(path.parent), ":run"), (str(guard.parent), ":guard_tools"),
                             (str(arm), ":arm")):
                value = value.replace(old, new)
        return value
    sandbox = normalize(contexts[-1]["sandbox_policy"])
    outside_probes = [x for x in probes if x["name"] != "allowed"]
    positive_probes = [x for x in probes if x["name"] == "allowed"]
    isolation = "failed" if outside else "passed" if (
        len(outside_probes) == 12 and all(not x["read"] for x in outside_probes)
        and len(positive_probes) == 3 and all(x["hash_verified"] for x in positive_probes)) else "inconclusive"
    return {
        "run_id": run["run_id"], "source_run": str(path), "exit_reason": run["exit_reason"],
        "model": run["model"], "lane": run["lane"],
        "context_window": run["settings"]["context_window"],
        "reasoning_effort": run["settings"]["reasoning_effort"],
        "release_commit": run["code"]["commit"],
        "codex_version": run["harness"]["version"],
        "codex_binary": guard_policy["codex_binary"] if receipt else str(guard),
        "policy_guard_sha256": receipt["guard_sha256"] if receipt else None,
        "tool_read_roots": normalize(receipt["tool_read_roots"]) if receipt else None,
        "restricted_profile_selected": cfg.get("default_permissions") == "bda-restricted" and "sandbox_mode" not in cfg,
        "configured_read_policy": normalize(cfg.get("permissions", {})),
        "configured_auto_review_policy_sha256": digest(cfg.get("auto_review", {})),
        "model_catalog_sha256": digest(catalog),
        "custom_developer_instructions_present": bool(cfg.get("developer_instructions")),
        "custom_developer_instructions_sha256": digest(cfg.get("developer_instructions", "")),
        "provider_route": "context-hook proxy" if cfg.get("model_provider") == "context-hook"
                          else "default ChatGPT provider",
        "store_load_helpers_enabled": run["harness"]["settings"]["store_load"],
        "mcp_relay_enabled": "agent_context_manager.adapters.mcp_relay" in
                             cfg["mcp_servers"]["bda"]["args"],
        "native_features": cfg["features"],
        "native_memories": cfg["memories"],
        "configured_approval_policy": cfg["approval_policy"],
        "configured_approvals_reviewer": cfg.get("approvals_reviewer", "user"),
        "effective_approval_policy": contexts[-1]["approval_policy"],
        "effective_approvals_reviewer": contexts[-1]["approvals_reviewer"],
        "effective_sandbox_policy": sandbox,
        "managed_requirement_approval_override_observed": any(
            "approval_policy" in e.get("message", "") and "disallowed" in e.get("message", "")
            for e in errors),
        "probe_script_unchanged": original["probe_script_unchanged"],
        "note_script_unchanged": original.get("note_script_unchanged", False),
        "workspace_note_write_passed": original.get("workspace_note_write_passed", False),
        "probe_attempts": len(probes),
        "outside_canary_files_read": len({x["name"] for x in outside}),
        "outside_read_attempts_succeeded": len(outside),
        "filesystem_isolation": isolation,
        "filesystem_probes": probes,
        "mcp_http_requests": len(histories),
        "mcp_actions": [x["request"]["action"] for x in histories],
        "mcp_http_statuses": [x["status"] for x in histories],
        "final_observations": final_observations,
        "synthetic_totals": original["synthetic_totals"],
        "scorers_agree": original["scorers_agree"],
        "successful_model_requests": sum(x["type"] == "token_usage_record" for x in records),
        "usage": {k: usage.get(k) for k in ("input_tokens", "output_tokens")},
        "raw_requests_packed": run["pack"]["requests_packed"],
        "compaction_exercised": any("compact" in x.get("type", "") or
                                    "compact" in x.get("payload", {}).get("type", "") for x in records)
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prototype", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    prototype, baseline = read_arm(a.prototype), read_arm(a.baseline)
    common = ("model", "lane", "context_window", "reasoning_effort", "release_commit", "codex_version",
              "codex_binary", "model_catalog_sha256", "native_features", "native_memories",
              "effective_sandbox_policy", "configured_auto_review_policy_sha256",
              "mcp_actions", "final_observations")
    matching = {k: prototype[k] == baseline[k] for k in common}
    policy_match = (prototype["effective_approval_policy"] == baseline["effective_approval_policy"] == "on-request"
                    and prototype["effective_approvals_reviewer"] == baseline["effective_approvals_reviewer"] == "auto_review")
    guard_match = bool(prototype["policy_guard_sha256"]) and prototype["policy_guard_sha256"] == baseline["policy_guard_sha256"]
    read_policy_match = prototype["configured_read_policy"] == baseline["configured_read_policy"]
    safe = all(x["filesystem_isolation"] == "passed" and x["restricted_profile_selected"]
               and x["probe_script_unchanged"] and x["note_script_unchanged"]
               and x["workspace_note_write_passed"] and x["mcp_http_statuses"] == [200] * 8
               and x["synthetic_totals"]["rounds"] == 2 and x["synthetic_totals"]["tested"] == 4
               and x["scorers_agree"] for x in (prototype, baseline))
    ready = all(matching.values()) and policy_match and guard_match and read_policy_match and safe
    blockers = []
    if not safe:
        blockers.append("Restricted-read/positive-control/MCP/scoring verification is incomplete or failed")
    if not policy_match:
        blockers.append("Effective approval policies/reviewers are not both on-request with auto_review")
    if not (all(matching.values()) and guard_match and read_policy_match):
        blockers.append("Runtime comparison controls or enforced guard policies differ")
    report = {"prototype": prototype, "baseline": baseline,
              "matching_fields": matching,
              "effective_approval_policies_match": policy_match,
              "matching_enforced_guards": guard_match and read_policy_match,
              "benchmark_ready": ready,
              "blockers": blockers,
              "scope": "Observed startup/runtime configuration and synthetic smoke, not full source audit or compaction experiment"}
    with a.out.open("x") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({"matching_fields": report["matching_fields"], "blockers": report["blockers"]}, indent=2))


if __name__ == "__main__":
    main()
