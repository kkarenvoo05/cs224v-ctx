# Evaluator service and integration gates

`evaluator_service.py` owns BDA state across agent calls and writes a full
request/response trace and atomic snapshots. It currently exposes a local HTTP
API. The installed `ours` release documents stdio MCP registration, and a tested
bridge is now available. Its connection inside an actual model run and the exact
matched baseline behavior are reported below. The current guarded runs pass the
synthetic filesystem read checks and have matching effective approval policies.

## First real IFNG pilot, November 10

The guarded 30×16 seed-0 prototype and baseline both completed with 480 unique
accepted experiments, 30 full rounds, zero repeats or invalid IDs, complete
evaluator traces and agreeing independent scores. Both used the same prompt,
model, lane, release, DepMap features, IFNG truth/hits, task seed and 1,800-second
wall limit. The prototype found **54 hits** in 113 seconds; the baseline found
**31 hits** in 99 seconds. The credential-free paired report is
`runs/paired_30x16_seed0_20261110.json`; the exact prompt is
`pilot_30x16_prompt.md`. Raw agent and evaluator records remain ignored under
`runtime_setup/private/pilot_30x16_seed0_20261110/`.

This single pair does not establish a memory-policy advantage. The baseline
had 20 failed shell heredoc writes because the restricted macOS temporary-file
path was denied, while the prototype wrote its workspace notes successfully.
It also made two over-quota lookup calls (HTTP 400), with no effect on accepted
experiments. Neither arm recorded compaction. Fix and test a common workspace
note-writing path before attributing differences to context policy. The one-pair
usage scope is consumed; `usage_policy.pilot_enabled=false` now blocks further
pilot launches until a new scope is set.

## Current restricted verification, November 10

`runtime_policy.py` stages a pinned `codex` adapter for each arm. It writes a
`bda-restricted` permission profile only into that run's generated Codex home.
The profile allows the workspace and exact runtime/Python tool roots, denies
other root reads and direct network access, and requests `on-request` approval
with `auto_review` as the reviewer. A run-local reviewer rule rejects sandbox
escalation and evaluator-only reads.
The adapter rejects broader CLI sandbox flags and checks the bundled binary hash.

The paired real-runtime synthetic smoke passed all 12 outside-read denials and
all three workspace positive controls **in each arm**, using direct Python reads,
symlink traversal and `/bin/cat`. Each arm completed eight MCP requests with HTTP
200 responses, two rounds, four synthetic accepted experiments and agreeing
independent scores. The native read boundary is observed for sandboxed command
execution; trusted runtime components and compiled source were not audited.

**The pilot gate is open for the guarded launcher.** Both actual agent sessions
record `on-request` with `auto_review`; the configured reviewer rule matches.
Pinned Codex headless `exec` forced `never` when the reviewer was left at its
default, even with a CLI approval override. Selecting Auto-review in each run-local
config makes the effective policy match. The paired certificate has no blockers:
`runtime_setup/runtime_matched_verification_20261110.json`.

A separate synthetic probe asked each agent to request an escalated read of
evaluator-only ground truth. Auto-review declined both requests; neither command
returned canary content. Evidence: `runtime_setup/runtime_approval_denial_20261110.json`.
These are observed decisions, not a deterministic guarantee that Auto-review
will reject every future escalation. The native sandbox's ordinary read boundary
was tested independently. `runtime_setup/setup.json` now records
`benchmark_ready=true` records the runtime certificate. `guarded_ours.py` checks
both certificates, the guard hash and the separate usage gate before a launch.
The first real-data pair is reported above; its usage gate is now closed.

The older section below records the original unrestricted test and explains why
the native permission profile was added.

## Earlier unrestricted runtime verification, November 10

Completed a real subscription smoke on each harness, using synthetic data only.
Same pinned release, bundled binary, model, selected-model catalog hash, 48,000-token
context and medium reasoning in both. The prototype took 45.29 seconds; the successful
baseline took 51.62 seconds. One baseline attempt first returned a capacity error;
retrying the same model succeeded. No real benchmark files were read by the probes.

| Behavior | `codex` | `codex-shipped` |
| --- | --- | --- |
| Custom structured-memory developer instructions | Present | Absent |
| Model request route | Custom `context-hook` provider/proxy | Default ChatGPT provider |
| Native code-mode `store()`/`load()` helpers | Disabled | Enabled |
| MCP transport | Context manager's tracing relay, then bridge | Direct bridge |
| Packed raw model requests | 4 | 0; session/tool transcripts remain |
| Native memories, plugins, skills, native hooks, multi-agent features | Disabled | Disabled |
| Configured approval policy | `never` | `never` |
| Effective approval policy in session | `never` | `on-request` due managed account requirements |
| Effective sandbox | `workspace-write`, direct network off | Same |
| Synthetic MCP sequence | 8 successful requests | Same 8 requests and identical observations |
| Read evaluator-only canaries outside workspace | All four readable | All four readable |

`codex-shipped` therefore removes the custom structured-memory instruction and
context-hook path, but does **not** remove ordinary file/code tools, native
`store()`/`load()`, or the task's MCP tools. The two arms currently compare a package
of instruction, interception, helper and tracing differences. They also have a
verified effective approval-policy mismatch on this account. The public CLI offers
no approval-policy forwarding option. Align both arms to a common policy permitted
by the account requirements before a matched study.

This verifies observed startup/configuration/runtime behavior. It is not a source
audit, and these short runs did not exercise compaction or establish its semantics.
In particular, the common native `features.hooks=false` flag does not disable the
prototype's separate external context hook.

**Isolation failed:** mode-0700 evaluator storage and an empty seed folder did not
prevent same-user reads. Each agent executed the unchanged supplied probe and read
all four synthetic evaluator-only files by direct open, symlink and `/bin/cat`
subprocess: **12/12 outside-read attempts succeeded in each arm**, with hashes
checked against controller-owned expected values. The in-workspace positive control
also passed. No broader access was requested during the probes.

**MCP passed:** both agents used the real stdio bridge and HTTP service, completed
two rounds with four accepted synthetic experiments, and returned identical legal
observations. All eight HTTP responses per arm were 200, and independent scorers
agreed. Test services were stopped after both runs.

Credential-free evidence: `runtime_setup/runtime_verification_20261110.json`.
Reproduction helpers: `smoke_ours_runtime.py` and `analyze_runtime_smoke.py`.
Raw requests, account/runtime files and full instructions remain under ignored
`runtime_setup/private/`. Eight successful model requests reported 82,865 input
tokens and 643 output tokens total; these are usage counters, not billed dollars.

The matched restricted policy above supersedes this failed read result and the
earlier approval-policy mismatch.

## Installed runtime, November 10

- Installed and pinned `2026.11.09-166c433f`, commit
  `166c433f79dd667f76d093898a39aa795f3e3349`. Bundled Codex reports `0.159.0`.
- `ours login status` reports `Logged in using ChatGPT`; the bundled runtime uses
  the existing `~/.codex/auth.json`. No new login was needed. No credentials were copied
  into the repository. New terminals get `~/.ours/bin` through `~/.zshrc`.
- `gpt-6.1-terra` metadata fetched successfully through the subscription backend;
  actual smoke inference has now succeeded in both arms. Common comparison
  settings: `--lane subscription --model gpt-6.1-terra --context-window 48000
  --reasoning-effort medium --model-info-dir bio/runtime_setup/model_info`.
- `ours run --help` lists `--harness {codex,codex-shipped}`. The switch's observed
  instruction, hook, tool and tracing differences are verified above. Each harness
  has its own parser: `ours run --harness codex-shipped --help` shows the baseline
  does not accept `--model-info-dir`; it uses `--codex-login` and its own model fetch.
- The installed README documents `--mcp-servers FILE`, a JSON mapping of server
  name to `command`, `args`, and `env`. It also documents `--wall-clock-s` and
  `run.json` statuses including `timeout`, `usage_limit`, and `sandbox_unavailable`.
- The paired synthetic smoke and one 30×16 real-data pair are complete.
  `guarded_ours.py` enforced the **1,800-second per-arm** limit and certificate
  checks. The one-pair usage gate is closed. The help exposes no hard token or
  dollar budget flag; further model usage needs a new explicit scope.

Full installed README, help output and VERSION are preserved locally in
`runtime_setup/private/` (ignored to respect the release's redistribution restriction).
Account-specific model metadata is also ignored.

## Connect evaluator tools through stdio MCP

`evaluator_mcp.py` is a standalone standard-library bridge with no evaluator
imports or hidden-state access. Its only tool, `bda`, forwards an `action` and
`args` to the service. It negotiates MCP initialization, lists its schema and
returns tool results; no filesystem tool is exposed. It preserves request IDs
for idempotent evaluator retries. Its subprocess protocol and HTTP forwarding
are tested both locally and in the actual runtime. The framing follows the
[MCP stdio specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).

Start an evaluator as below, then generate the private registry:

```sh
bio/.venv/bin/python -I bio/prepare_ours_mcp.py \
  --connection bio/runs/evaluator_NEW/connection.json \
  --out bio/runtime_setup/bda_mcp.json
```

Use `guarded_ours.py` to prepare an arm, then pass `--execute` to start it. It pins
the release, checks both certificates,
stages the tested guard and applies the configured wall limit. Generate a new
registry for every evaluator episode. The
file contains the bearer token: keep it private and outside the seed directory.
`runtime_setup/private/validation_mcp.json` was generated against the already
stopped local smoke service to validate the registry writer; it is not a live connection.

## Local validation without model calls

From the repository root:

```sh
bio/.venv/bin/python -B -m pytest -q bio/test_env.py bio/test_checkpoint.py bio/test_evaluator_service.py bio/test_evaluator_mcp.py audit/test_audit.py
bio/.venv/bin/python -I bio/validate_depmap.py
bio/.venv/bin/python -B bio/smoke_evaluator.py --out bio/runs/evaluator_smoke_NEW
```

The HTTP test and smoke bind a temporary loopback port. They need a terminal or
execution permission that permits localhost listeners. The smoke starts a real
IFNG/DepMap evaluator, completes two rounds, exercises repeat/top-up behavior,
checks hidden-action rejection and compares legal observations with saved state.
It terminates its service when finished. This is an API smoke, not the required
prototype-versus-baseline model smoke or filesystem isolation check.

## Start an evaluator

```sh
bio/.venv/bin/python -I bio/evaluator_service.py \
  --out bio/runs/evaluator_NEW --screen IFNG --rounds 2 --batch 16 --seed 0 \
  --max-proposals 3 --max-lookups 8 --max-requests 10000
```

Output must be fresh. `connection.json` holds the loopback URL and bearer token.
Transfer only those connection details to an agent's allowed environment.
`config.json`, `run.json`, and `requests.jsonl` remain evaluator-only. They contain
evaluation metadata/state and cannot be put in an agent seed directory. Outputs
are private to the current OS user; this alone does not isolate a same-user agent.
The service does not support restart/resume or parallel requests.

Requests are POSTs to `/v1`, with `Authorization: Bearer TOKEN`, and JSON:

```json
{"request_id":"unique-1","action":"propose","args":{"ids":["G00001","G00002"]}}
```

Every exact replay of a request ID returns its prior response without replaying
the action. Changed content under the same ID is rejected. All authenticated API
envelopes, including failed ones and replays, count toward the global request cap.
Malformed/unauthorized HTTP POSTs are also logged, without bearer tokens.

| Action | Arguments | Response |
| --- | --- | --- |
| `catalog` | `{offset:0,limit:256}` (optional) | Up to 256 opaque IDs, total count, numeric ID format, next page and public limits |
| `propose` | `{"ids":[...]}` | Current-round accepted IDs, measured scores, hit flags and rejections |
| `lookup` | `{"id":"G00001","k":8}` | DepMap neighbors, no target scores; k is 1–32 |
| `history` | `{}` | Only observed IDs, scores, hit flags, and rounds |
| `end_round` | `{}` | Finalizes this round, even if short; returns completion status |

Each proposal accepts at most batch-size submitted IDs. Up to three proposal
calls (initial plus two retries) and eight similarity lookups are allowed per
round by default. Limits reset only on `end_round`. After the final round,
proposals, lookups and further round finalization are denied. There are no file,
symbol mapping, unseen-score or unobserved-hit endpoints. The API omits the hidden
hit denominator and evaluation hit-ratio metrics.

## Required before any agent pilot

1. Preserve the verified pinned binary, selected model, reasoning, context and lane.
   Model inference and the MCP connection now work in both arms.
2. Account for the verified baseline differences above. The current guarded
   sessions both resolve to `on-request` with `auto_review`. Re-run both synthetic
   certificates after any guard, runtime, model, account-policy, or reviewer-policy
   change. Compaction still needs a separate test at meaningful prompt occupancy.
3. Pass the selected native wall-clock limit on each invocation, and monitor usage.
   The Claude-only `costguard.sh` does not guard this service or `ours`. No hard
   token/dollar cap has been established; do not describe the wall-time cap as one.
4. Keep both agents from reading the repository, dataset, ID mapping, evaluator
   files, process memory and alternate copies of hidden state. The current native
   tool restriction passed synthetic checks; recheck it for a changed runtime:
   try reading hidden ground truth, `.npy` hits, the symbol map, service snapshots,
   another run's outputs, and access through a symlink or subprocess. Check allowed
   observations still work. A service on a separate protected machine/container
   is an option if the local runtime cannot enforce this boundary.
5. Run the same two-round task with prototype and matched baseline; verify legal
   observations, evaluator metrics, complete runtime traces and stopping controls.
   Only then run 30×16 paired pilots, followed by 100×32 over paired task seeds.

Questions for the release author (not sent): How can both arms enforce restricted
read roots and the same permitted approval policy? Can the storage-helper and
tracing differences be controlled separately? Are token/call ceilings supported
beyond the documented wall-clock limit? How should compaction/retrieval events
be compared between the hooked and direct-provider paths?

## Additional controls now available

The existing plain-model harness accepts `--policy summary_set`: the same two
lossy summaries plus all previously tested IDs, without restoring their scores.
This control belongs to that harness and does not establish a prototype comparison.
`--probe-delays 1 2 4 8 16 32 64` extends its closed-book probes. Keep model and
data fixed when comparing policies; tool-enabled probes need a separate protocol.

The free kNN/UCB baselines now normalize using **observed** scores only. Older
baseline outputs used the full hidden score table's standard deviation and should
not be pooled with the corrected results. New baseline outputs include source/code
hashes, preserve per-run partial results, and refuse an existing output path.
