"""Export a credential-free comparison of two completed BDA pilot arms."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tomllib


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def main_session(home):
    sessions = []
    for path in home.glob("sessions/**/*.jsonl"):
        with path.open() as f:
            first = json.loads(next(f))
        if first.get("type") != "session_meta":
            continue
        meta = first["payload"]
        if meta.get("source") == "exec" and "parent_thread_id" not in meta:
            sessions.append(path)
    if len(sessions) != 1:
        raise ValueError("Expected one main agent session")
    context = None
    model_requests = compactions = 0
    with sessions[0].open() as f:
        for line in f:
            record = json.loads(line)
            kind = record.get("type", "")
            if kind == "turn_context":
                context = record["payload"]
            if kind == "token_usage_record":
                model_requests += 1
            event = record.get("payload", {}).get("type", "")
            if "compact" in kind or "compact" in event:
                compactions += 1
    if context is None:
        raise ValueError("Missing effective turn context")
    return context, model_requests, compactions


def read_arm(root, arm):
    evaluator_root = root / f"{arm}_evaluator"
    agent_root = root / f"{arm}_agent"
    paths = list((agent_root / "runs").glob("*/run.json"))
    if len(paths) != 1:
        raise ValueError(f"Expected one {arm} agent run")
    run = json.loads(paths[0].read_text())
    evaluator = json.loads((evaluator_root / "run.json").read_text())
    source = json.loads((evaluator_root / "config.json").read_text())
    cfg = tomllib.loads((paths[0].parent / "harness/codex_home/config.toml").read_text())
    receipt = json.loads((paths[0].parent / "harness/restricted_policy_receipt.json").read_text())
    context, model_requests, compactions = main_session(paths[0].parent / "harness/codex_home")
    events = [json.loads(line) for line in (evaluator_root / "requests.jsonl").read_text().splitlines()]
    tool_events = [json.loads(line).get("item", {}) for line in
                   (paths[0].parent / "harness/exec.jsonl").read_text().splitlines()]
    commands = [x for x in tool_events if x.get("type") == "command_execution"]
    failed_commands = [x for x in commands if x.get("status") == "failed"]
    actions = Counter(x["request"].get("action") for x in events)
    statuses = Counter(str(x["status"]) for x in events)
    errors = Counter(x["response"].get("error", "") for x in events if x["status"] != 200)
    rounds = evaluator["rounds"]
    accepted = [g for row in rounds for g in row["accepted"]]
    args = {k: v for k, v in source["args"].items() if k not in ("out", "port")}
    invocation = json.loads((agent_root / "invocation.json").read_text())
    prompt = invocation[invocation.index("--prompt") + 1]
    usage = run.get("usage", {})
    started, ended = (datetime.fromisoformat(run[key].replace("Z", "+00:00"))
                      for key in ("started", "ended"))
    return {
        "harness": run["harness"]["name"], "agent_exit_reason": run["exit_reason"],
        "evaluator_status": evaluator["status"],
        "model": run["model"], "lane": run["lane"],
        "context_window": run["settings"]["context_window"],
        "reasoning_effort": run["settings"]["reasoning_effort"],
        "wall_limit_s": run["settings"]["wall_clock_s"],
        "elapsed_s": round((ended - started).total_seconds(), 2),
        "release_commit": run["code"]["commit"],
        "codex_version": run["harness"]["version"],
        "policy_guard_sha256": receipt["guard_sha256"],
        "effective_approval_policy": context["approval_policy"],
        "effective_approvals_reviewer": context["approvals_reviewer"],
        "configured_read_profile": cfg.get("default_permissions"),
        "configured_auto_review_policy_sha256": sha_bytes(json.dumps(
            cfg.get("auto_review", {}), sort_keys=True).encode()),
        "prompt_sha256": sha_bytes(prompt.encode()),
        "evaluator_args": args,
        "features_sha256": source["features_sha256"],
        "ground_truth_sha256": source["ground_truth_sha256"],
        "hits_sha256": source["hits_sha256"],
        "evaluator_code_sha256": source["code_sha256"],
        "rounds_completed": len(rounds),
        "accepted_experiments": len(accepted),
        "accepted_ids_unique": len(set(accepted)) == len(accepted),
        "all_batches_full": all(len(row["accepted"]) == args["batch"] for row in rounds),
        "hits": evaluator["totals"]["cum_hits"],
        "hit_ratio": evaluator["totals"]["hit_ratio"],
        "independent_scorer_agrees": evaluator["totals"]["hit_ratio"] == evaluator["independent_hit_ratio"],
        "repeats": evaluator["totals"]["repeats"],
        "invalid": evaluator["totals"]["invalid"],
        "short_batches": evaluator["totals"]["short_batches"],
        "cumulative_hits_by_round": [row["cum_hits"] for row in rounds],
        "http_requests": len(events), "http_actions": dict(actions),
        "http_statuses": dict(statuses), "http_errors": dict(errors),
        "trace_matches_snapshot": len(events) == evaluator["requests"],
        "agent_command_failures": len(failed_commands),
        "heredoc_temp_failures": sum("can't create temp file for here document" in
                                     x.get("aggregated_output", "") for x in failed_commands),
        "model_requests": model_requests, "compaction_events": compactions,
        "usage_input_tokens": usage.get("input_tokens"),
        "usage_output_tokens": usage.get("output_tokens"),
        "usage_total_tokens": usage.get("total_tokens", (usage.get("input_tokens") or 0) +
                                         (usage.get("output_tokens") or 0)),
        "raw_model_requests_packed": run["pack"]["requests_packed"],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    prototype, baseline = (read_arm(a.root, arm) for arm in ("prototype", "baseline"))
    shared = ("model", "lane", "context_window", "reasoning_effort", "wall_limit_s",
              "release_commit", "codex_version", "policy_guard_sha256",
              "effective_approval_policy", "effective_approvals_reviewer",
              "configured_read_profile", "configured_auto_review_policy_sha256",
              "prompt_sha256", "evaluator_args", "features_sha256", "ground_truth_sha256",
              "hits_sha256", "evaluator_code_sha256")
    matching = {key: prototype[key] == baseline[key] for key in shared}
    rounds, batch = prototype["evaluator_args"]["rounds"], prototype["evaluator_args"]["batch"]
    complete = all(x["agent_exit_reason"] == "completed" and x["evaluator_status"] == "complete"
                   and x["rounds_completed"] == rounds and x["accepted_experiments"] == rounds * batch
                   and x["accepted_ids_unique"] and x["all_batches_full"]
                   and x["independent_scorer_agrees"] and x["trace_matches_snapshot"]
                   and x["repeats"] == x["invalid"] == x["short_batches"] == 0
                   and x["http_actions"].get("propose", 0) >= rounds
                   and x["http_actions"].get("end_round") == rounds
                   and x["effective_approval_policy"] == "on-request"
                   and x["effective_approvals_reviewer"] == "auto_review"
                   for x in (prototype, baseline))
    result = {"prototype": prototype, "baseline": baseline,
              "matching_controls": matching, "paired_pilot_complete": complete and all(matching.values()),
              "comparison_clean_of_tool_failures": complete and all(matching.values()) and
                                                  all(x["agent_command_failures"] == 0 for x in
                                                      (prototype, baseline)),
              "hit_difference_prototype_minus_baseline": prototype["hits"] - baseline["hits"],
              "scope": f"One {prototype['evaluator_args']['screen']} {rounds}x{batch} "
                       f"seed-{prototype['evaluator_args']['seed']} pair; aggregate outcome only, "
                       "not an across-seed effect estimate. "
                       f"Agent command failures: prototype {prototype['agent_command_failures']}, "
                       f"baseline {baseline['agent_command_failures']} (heredoc temp-file failures: "
                       f"{prototype['heredoc_temp_failures']}, {baseline['heredoc_temp_failures']}). "
                       "Expected harness feature differences limit causal interpretation."}
    with a.out.open("x") as f:
        json.dump(result, f, indent=2)
    print(json.dumps({"paired_pilot_complete": result["paired_pilot_complete"],
                      "matching_controls": matching,
                      "prototype_hits": prototype["hits"], "baseline_hits": baseline["hits"]}, indent=2))


if __name__ == "__main__":
    main()
