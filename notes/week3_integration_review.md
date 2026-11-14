# Week-3 direction: local review, November 9, 2026

## Step 5 completed: IFNG 100×32, paired seeds 0–2, November 13

The prepared three-pair scope ran on the pinned release with alternating arm
order and a 3,600-second wall limit per arm. The first launch was denied a local
loopback socket by the shell sandbox; the first host-permitted retry stopped at
prototype round 46 when the host disk filled. Neither attempt produced a paired
report. Clearing the regenerable pip download cache recovered 3.2 GB, and all
three pairs then completed under the certified guard.

| Seed | Prototype hits | Baseline hits | Prototype − baseline |
| --- | ---: | ---: | ---: |
| 0 | 292 | 313 | −21 |
| 1 | 287 | 314 | −27 |
| 2 | 217 | 254 | −37 |
| Mean | 265.3 | 293.7 | −28.3 |

Reports: [seed 0](../bio/runs/paired_100x32_seed0_20261113_retry2.json),
[seed 1](../bio/runs/paired_100x32_seed1_20261113_retry2.json), and
[seed 2](../bio/runs/paired_100x32_seed2_20261113_retry2.json).
All six arms completed 100 rounds and 3,200 unique accepted experiments with
full batches, zero repeats or invalid IDs, matching traces and snapshots, and
independent scorer agreement. All 18 recorded controls matched within each pair.
The prototype had one command failure in each seed; seeds 0 and 1 also had one
non-200 lookup each (`k out of range`). Thus the reports mark the comparisons as
not clean of tool failures. No arm recorded a compaction event.

The baseline outscored the prototype on these three seeds. This is a paired
package comparison, not an isolated context-policy effect or a context-pressure
test. The three-pair scope is consumed and the launch gate is closed in
`bio/runtime_setup/setup.json`. Further model runs require a new usage scope.

## Step 5 (100×32, paired seeds 0–2), November 10: blocked on account credits (superseded)

Authorized scope: three IFNG 100×32 pairs (seeds 0, 1, 2), 3,600-second wall
limit per arm, arm order alternating by seed. Added
[pilot_100x32_prompt.md](../bio/pilot_100x32_prompt.md), which is the 30×16 prompt
with only the size numbers changed. Added `bio/run_paired_pilot.py`, which runs a
fresh evaluator per arm, then the certified launcher and the paired analysis. Also
generalized `bio/analyze_paired_pilot.py` beyond 30 rounds; it reproduces the
corrected 30×16 report exactly. A prepare-only dry run passed every launcher gate.

**All six launches failed before the first model turn.** The runtime reported
"Your workspace is out of credits. Ask your workspace owner to refill in order
to continue." The prototype's exit status was `usage_limit` and the baseline's
was `failed`. Zero evaluator requests and zero rounds were recorded, so there
is no step-5 data. Raw records are kept as
`bio/runtime_setup/private/pilot_100x32_seed{0,1,2}_20261110_no_credits/`.
The driver now aborts on the first failed arm without writing a report.

Next: refill subscription credits, then rerun the three seeds. The scope in
`bio/runtime_setup/setup.json` is unchanged and unconsumed.

## Corrected IFNG 30×16 paired pilot, November 10 (current)

**Fix:** the run-local guard now points `TMPDIR` and `TMPPREFIX` at a per-run
`workspace/.agent_tmp` (mode 0700, symlink refused). It does this both in the
generated `shell_environment_policy` and in the guarded Codex process
environment, so shell heredocs create their temporary files inside the
workspace while `:slash_tmp` and `:root` stay denied. The offline test
`test_actual_restricted_read_policy` exercises a `zsh` heredoc note write and
outside-read denial under the actual bundled macOS sandbox. Both arms were then
recertified with real subscription smokes under the new guard
(`e973f87f…`): workspace note write passed, no outside read succeeded in 15 probe attempts, MCP
and scorers passed, and an escalated evaluator read was declined in each arm:
[runtime_workspace_note_verification_20261110.json](../bio/runtime_setup/runtime_workspace_note_verification_20261110.json),
[runtime_workspace_note_approval_denial_final_20261110.json](../bio/runtime_setup/runtime_workspace_note_approval_denial_final_20261110.json).
(The first denial run is kept as a failed record: the baseline agent did not
attempt the targeted escalation, so nothing was reviewed. The final rerun did.)

The corrected pair then ran under a new one-pair usage scope. The settings were
the same as the first pair. All 18 matching controls agreed: model, lane,
context, reasoning, wall limit, release, guard, approval/reviewer, read profile,
prompt, evaluator args, and data/code hashes. Both arms completed 30 rounds with
**480 unique accepted experiments**, full batches, zero repeats/invalid IDs,
all-200 evaluator HTTP, traces matching snapshots and independent scorer
agreement. Report:
[paired_30x16_seed0_corrected_20261110.json](../bio/runs/paired_30x16_seed0_corrected_20261110.json).

| Arm | Hits | Agent time | Input/output tokens | Evaluator HTTP | Command failures |
| --- | ---: | ---: | ---: | --- | ---: |
| Prototype `codex` | 83 | 162 s | 210,424 / 4,433 | 305 successful | 1 |
| Baseline `codex-shipped` | 53 | 98 s | 158,624 / 3,642 | 329 successful | 0 |

**The note-writing path now works in both arms.** The baseline made four
heredoc progress writes and all four succeeded. It kept a 27 KB `progress.json`.
There were zero heredoc temp-file failures in either arm. The prototype's single
failed command was its second command: it called `python3` and got the macOS
`/usr/bin/python3` stub, which requires Xcode tools. It switched to
`/opt/miniconda3/bin/python` on the next command and finished normally. Neither
run recorded a compaction event, and both made 12 model requests. Peak prompt
occupancy was not measured.

The arms differ in style. The prototype ran 184 commands and kept structured
`data_structures/` tables. The baseline ran 4 shell commands and wrote one JSON
note. This is the expected package difference, not a tool failure.

The **30-hit gap (83 vs 53) is one seed's result, not an effect estimate.**
Hits also moved by run-to-run variance: on the same seed the prototype went
54 → 83 and the baseline 31 → 53 between pairs. That spread is as large as the
gap itself, so multiple paired seeds are required. With no compaction, this
pilot also does not test memory under context pressure. The one-pair scope is
consumed and the launch gate is closed (`bio/runtime_setup/setup.json`).
**Step 4 is complete; step 5 (100×32 and multiple paired task seeds) needs a new
usage scope.**

## First IFNG 30×16 paired pilot, November 10 (superseded by the corrected pair)

The first real-data pair completed under the guarded launcher. Both agents used
the same public seed, prompt, pinned release, model, subscription lane, 48,000-token
context, medium reasoning, DepMap feature file, IFNG truth/hit files, task seed 0,
30 rounds, batch 16 and 1,800-second wall limit. Both evaluator snapshots and
agent runs completed; each accepted **480 unique experiments**, filled every
batch, and recorded zero repeats or invalid IDs. Independent scoring agreed.
Credential-free report: [paired_30x16_seed0_20261110.json](../bio/runs/paired_30x16_seed0_20261110.json).
The shared task text is [pilot_30x16_prompt.md](../bio/pilot_30x16_prompt.md).

| Arm | Hits | Agent time | Input/output tokens | Evaluator HTTP |
| --- | ---: | ---: | ---: | --- |
| Prototype `codex` | 54 | 113 s | 191,542 / 3,229 | 300 successful |
| Baseline `codex-shipped` | 31 | 99 s | 163,909 / 2,346 | 302 successful, 2 lookup-quota errors |

The **23-hit difference is one seed's observed result, not a context-policy
effect estimate**. The baseline also had 20 failed attempts to save workspace
progress with shell heredocs: macOS denied creation of their temporary files.
The prototype's workspace writes succeeded. Neither run recorded a compaction
event. These execution differences confound an interpretation as memory-policy
benefit. The one-pair usage scope has been consumed and the pilot launch gate is
closed. Before a further paired run, make workspace note writes work for both
arms and test that path under the same restricted-read profile; then set a new
usage scope and rerun matched arms or proceed to planned paired seeds.

## Matched restricted runtime verification, November 10 (current)

The macOS native permission profile now confines both agents' command tools to
their run workspace plus pinned runtime/Python tool roots. In a new paired real
subscription smoke, **all 12 evaluator-only read attempts per arm were denied**
across direct open, symlink traversal and `/bin/cat`; all three in-workspace
positive controls per arm passed. Each arm also completed eight MCP/HTTP requests,
two synthetic rounds and four accepted tests, with HTTP 200 responses and matching
independent scores. The tests used synthetic canaries, not actual benchmark data.
Credential-free evidence:
[runtime_matched_verification_20261110.json](../bio/runtime_setup/runtime_matched_verification_20261110.json).

**The approval policies now match in the actual sessions:** `on-request` with
`auto_review` in both arms. Setting `approvals_reviewer="auto_review"` in the
run-local config makes pinned Codex's headless `exec` honor the configured
`on-request` policy; a CLI approval override alone did not. The same run-local
reviewer rule rejects sandbox escalation and evaluator-only reads. A separate
synthetic negative probe requested an escalated read in each arm; both reviews
declined, and no canary content appeared in command output. Evidence:
[runtime_approval_denial_20261110.json](../bio/runtime_setup/runtime_approval_denial_20261110.json).

The guarded launcher was enabled for one 30×16 paired pilot at a 1,800-second
wall limit per arm and both harnesses passed preparation checks. That pair is
reported above. Auto-review is
a model-mediated approval check, so a denial in these probes is not a deterministic
guarantee for every future request. The native command sandbox provides the
tested normal-read boundary; trusted runtime components and compiled source were
not audited. [bio/EVALUATOR.md](../bio/EVALUATOR.md) has reproduction details.

## Earlier unrestricted runtime verification, November 10 (superseded read policy)

Completed one successful real subscription smoke for each harness, using only a
synthetic evaluator and canary files. **MCP passes in both arms; filesystem isolation
fails in both. Real benchmark pilots remain disabled.** Credential-free evidence:
[runtime_verification_20261110.json](../bio/runtime_setup/runtime_verification_20261110.json).

The same pinned release, bundled Codex binary, selected-model catalog hash,
`gpt-6.1-terra`, 48,000-token context and medium reasoning were verified in both arms.
Each agent completed eight MCP/HTTP requests, two rounds and four synthetic accepted
experiments. Responses were all HTTP 200; final legal observations were identical,
and independent scorers agreed. Both local services were stopped after the smoke.

Verified differences from generated configuration, run metadata and session records:

| Behavior | Prototype `codex` | Baseline `codex-shipped` |
| --- | --- | --- |
| Custom structured-memory developer instructions | Present | Absent |
| Model route | `context-hook` proxy | Default ChatGPT provider |
| Native code-mode `store()`/`load()` setting | Disabled | Enabled |
| MCP path | Context-manager tracing relay plus our bridge | Our bridge directly |
| Packed raw model requests | 4 | 0; session/tool transcripts still recorded |
| Native memories, hooks, plugins, skills and multi-agent features | Disabled | Disabled |
| Effective approval policy | `never` | `on-request`, enforced by managed account requirements |
| Effective sandbox | `workspace-write`, direct network off | Same |

Thus `codex-shipped` removes the custom instruction and context-hook path, but
retains ordinary code/file tools, native storage helpers and task MCP tools.
This is a package comparison with helper/tracing differences, and the account's
effective approval-policy mismatch is an additional confound. The common native
`features.hooks=false` flag does not describe the prototype's external context hook.
Full compiled-source behavior was not audited; compaction was not exercised.

**Read boundary:** each arm read all four evaluator-only synthetic canaries outside
its workspace using direct open, symlink traversal and `/bin/cat` subprocesses.
All **12/12 outside-read attempts per arm** matched the controller's expected hashes.
The public seed positive control passed, and the supplied probe script was unchanged.
Mode-0700 evaluator files, a separate service and an empty seed do not isolate a
same-user code-capable agent under this configuration. The probes did not access
actual benchmark files or request broader permissions.

The prototype completed in 45.29 seconds; the successful baseline in 51.62 seconds.
A baseline attempt first hit a transient model-capacity error; a same-model retry
succeeded. The baseline parser also differs: it rejects `--model-info-dir` and
instead exposes `--codex-login`; its generated selected-model catalog nevertheless
matched the prototype's exactly. Eight successful model requests reported a total
of 82,865 input tokens and 643 output tokens. These are usage counters, not billing.

Next: establish restricted read access common to both arms, or isolate the evaluator
under a protected user/host boundary; align both effective approval policies with
account requirements; then repeat the canary smoke before real data or a pilot.
The release currently exposes no read-root or approval-policy flags in `ours run`.
Questions for its author are saved in [bio/EVALUATOR.md](../bio/EVALUATOR.md); none
were sent. Reproduction helpers are `bio/smoke_ours_runtime.py` and
`bio/analyze_runtime_smoke.py`; raw artifacts remain in ignored private storage.

The following sections preserve the earlier setup snapshots.

## Runtime installed and authenticated, November 10 follow-up

GitHub access now works. Installed the current Apple-silicon release through the
inspected release installer, which verifies the archive checksum. The release is
**2026.11.09-166c433f**, commit `166c433f79dd667f76d093898a39aa795f3e3349`, and is
pinned with `ours use`. It is newer than the initially inspected `29fa581c` build.
Bundled Codex reports **0.159.0**; both bundled executable hashes match `VERSION`.
Added `~/.ours/bin` to `~/.zshrc` for new terminals.

`ours login status` reports **Logged in using ChatGPT** using the existing local
Codex credentials. No additional login was necessary, and no credentials were
copied into the repository. `ours fetch-model gpt-6.1-terra` succeeded after the
network sandbox was lifted for that metadata request. Model metadata is available;
an inference turn has not yet verified this account's access to the selected model.

Installed documentation and actual help now establish:

- `--lane subscription`, with explicit model `gpt-6.1-terra`, context window
  `48000`, and reasoning effort `medium` as the selected comparison configuration.
- `--mcp-servers FILE` accepts a JSON map of stdio servers with `command`, `args`,
  and `env`. Added `bio/evaluator_mcp.py`, a standalone stdio-to-HTTP bridge with
  no evaluator imports, and `bio/prepare_ours_mcp.py`, which writes a private
  registry from an evaluator connection file. Protocol, forwarding, observed-only
  results and idempotent retries are tested. Actual `ours` tool connection remains
  untested until a bounded model smoke is run.
- `--harness {codex,codex-shipped}` exists. These are candidate prototype/baseline
  arms; the installed README does not explain exactly what the shipped variant
  disables or what else changes. Do not claim a matched context-policy effect until
  instruction/hook/tool differences are verified from the runtime or by its author.
- `--wall-clock-s` is supported, with `timeout` and `usage_limit` statuses in
  `run.json`. No hard token or dollar cap is documented in help. Default setup scope
  is smoke only, maximum two arms at **300 seconds each**. Pilots are disabled;
  proposed next scope is one 30×16 pair at **1,800 seconds per arm**. These are wall-time
  limits, not token/dollar guarantees; the configuration file itself is not a launcher.

Settings are recorded in `bio/runtime_setup/setup.json`. Installed README, help and
VERSION are kept in ignored `bio/runtime_setup/private/` because the release is not
for redistribution. Account-specific model metadata is also ignored. Updated guide:
[bio/EVALUATOR.md](../bio/EVALUATOR.md).

Validation: **26 tests passed**. No new inference calls or benchmark model runs.
Remaining gates: verify exact baseline semantics, enforce/test the agent's filesystem
boundary, verify actual runtime MCP connection and model entitlement in the bounded
smoke, and then select/enable a pilot scope. Installation and login are no longer blockers.

## Mac setup and execution update, November 10

This section records the earlier pre-installation state; the follow-up above supersedes
its runtime/login blockers.

Host verified as macOS 26.2, Apple silicon (`Darwin arm64`). The recreated
`bio/.venv` uses Python 3.13.11 with the pinned requirements. The release README
checkout is inside this repository at `context-management-codex-integration-release/`,
commit `ad1ac610d65f86e0e5b28c9c53e8648dd7080ff4`. It contains no runtime implementation.
`ours` is absent from PATH and `~/.ours` does not exist. Hardware compatibility is
resolved; runtime installation, login, baseline controls and tool registration are pending.
GitHub CLI 2.103.3 is now installed through Homebrew, but `gh auth status` reports
no logged-in account. The pinned release API request returns HTTP 404 anonymously;
authenticated release access is needed before installation can proceed.

Completed without model calls:

- Downloaded BDA's supplied Achilles CSV via the Figshare API. Verified its 296,572,547
  bytes and MD5 against the published version-2 metadata, DOI
  `10.6084/m9.figshare.27246231.v2`, published October 17, 2024, CC BY 4.0.
  SHA-256: `71f32e3515dfa24d3bff559ea99fd5a0fa102c264064a6377e13d8eecd54298f`.
  This identifies BDA's distributed feature artifact; its upstream DepMap release/date
  remain unknown. Metadata and validation are in `data/depmap/figshare_metadata.json`
  and `data/depmap/manifest.json`.
- Validated 808 cell lines, 18,119 gene columns, no duplicate symbols, 28,922 missing
  cells. Existing complete-case preprocessing drops 30 cell lines and retains 778.
  IFNG coverage is 17,009/18,418 genes (92.35%); 1,409 missing genes receive zero
  features and no neighbors. The `IFNG` and `IL2` column names are gene symbols,
  not the target assay outcome tables. This replaces explicit sibling-screen features;
  it does not establish contamination-free model training data.
- Built the 50-PC cache. Cache reuse now verifies the source SHA-256; malformed CSV
  records and nonfinite inputs fail instead of silently skipping bad records.
- Corrected kNN/UCB reward normalization to use observed scores only. Previously it
  used the hidden table's standard deviation. Do not pool old baseline outputs with
  these corrected runs. New outputs preserve per-run checkpoints and code/data hashes.
- Completed IFNG free baselines at both sizes, four policies × seeds 0–4 at each size.
  All accepted the full allowed number of experiments and had zero repeats.

| Policy | Mean hits, 30×16 | Mean hits, 100×32 |
| --- | ---: | ---: |
| random | 23.2 | 153.2 |
| prior | 54.0 | 351.0 |
| kNN | 91.6 | 285.8 |
| UCB | 98.2 | 338.6 |

Outputs: `bio/runs/mac_depmap_30x16_20261110.json` and
`bio/runs/mac_depmap_100x32_20261110.json` (complete, 20 episodes each).

- Implemented `bio/evaluator_service.py`: evaluator-owned state, opaque ID catalog,
  proposals, similarity lookup and observed-history API, enforced round/batch/retry
  limits, idempotent request IDs, full request/response traces and atomic snapshots.
  Its HTTP API is transport-specific local infrastructure, not a verified `ours` adapter.
- Real-data API smoke passed: two rounds, 32 accepted tests, deliberate repeat and
  top-up behavior, hidden-action rejection, legal observations matching evaluator state,
  independent scorer agreement. Results: `bio/runs/mac_evaluator_smoke_20261110/smoke.json`.
  The service was stopped afterward. No prototype/baseline model smoke or actual agent
  filesystem isolation test has been run. Same-user processes can still read files
  unless the actual runtime boundary prevents it.
- Added `--policy summary_set` to the existing plain-model harness: same two summaries
  plus exact tested IDs, without restoring scores. Added configurable `--probe-delays`
  so future runs can use `1 2 4 8 16 32 64`. These controls are implemented and tested;
  no new inference experiments have been run.
- Final regression suite: **24 passed**, including a real loopback HTTP transport test.

Next gate: install/pin/login to the actual runtime; obtain its installed README and
`ours run --help`; establish same-scaffold baseline and evaluator connection controls;
set an account lane and explicit model-usage cap; verify filesystem isolation; then
run the matched two-round smoke and 30×16 paired pilot. Detailed API and gate checklist:
[bio/EVALUATOR.md](../bio/EVALUATOR.md). Steps 5–8 remain conditional on that pilot;
no context-length failure or prototype benefit can be claimed from this local setup work.

The November 9 review below records the earlier Linux environment and its evidence.

The outline is broadly sound, but prioritize the mentor's matched baseline-versus-prototype
experiment ahead of a Sonnet/Haiku sweep. Existing evidence establishes harmful information
removal by a summary; it has not established a failure caused by context length.

## What is verified locally

- Existing full run: 266 hits at round 100, 258 at round 98, no repeats; 385/385 recall probes.
- Summary recovered offline by exact replay of all 582 recorded calls: 191 hits at round 98,
  4/381 recall probes correct, 1,000/1,001 sampled diagnoses answered not tested.
- At round 98, the hit gap is 26.0%, accepted-test gap only 1.7%. Do not claim rejected repeats
  alone caused the hit gap. Scores lost from summaries may affect selection quality.
- Python environment installed locally using Python 3.13 (the available interpreter), with
  the project's pinned requirements. This satisfies README's 3.10+ instruction, but is not
  an exact reproduction of Katherine's interpreter.
- Run snapshots are now written atomically during execution; existing output paths are protected.
- `leaderboard/` is absent from this shared run kit; its reported tests and matcher changes
  cannot be reviewed here.

## Prototype release: current integration boundary

The sibling directory `context-management-codex-integration-release` contains a README and
Git metadata, with no implementation, installer, or executable locally. Its README says:

- builds exist for macOS Apple silicon;
- `ours` bundles Codex 0.159, rather than integrating with installed Codex 0.164;
- a run keeps files under `data_structures/`, with checks after calls and a full trace;
- `ours run` accepts a prompt, seed directory, model, context window and runs root;
- model metadata and subscription login are required; automatic updates must be pinned
  with `ours use TAG` for comparable runs;
- builds are not for redistribution.

The GitHub release asset list was also checked: tag `2026.11.09-29fa581c` offers
`install.sh`, `ours-29fa581c-darwin-arm64.tar.gz`, and its checksum; no Linux asset.
The local README checkout is commit `ad1ac61`.

This host is Linux x86_64, and `ours` is not installed. The documented runtime is therefore
not runnable here as supplied. Obtain a Linux build or use an Apple-silicon machine. Do not
substitute the installed Codex for the bundled runtime and call it the same treatment.
The README does not document selectable policies or how to disable structured-memory behavior
for a matched baseline. Request that interface and the full installed run/trace documentation.
The asset list was read using existing GitHub CLI credentials. No messages were sent and no
account login, model call, or release installation was attempted.

## Revised order of work

1. Resolve runtime support and baseline controls. Record release tag/commit, bundled Codex,
   exact model, reasoning settings, context limit, tool surface and account lane. Confirm
   supported model IDs with the actual runtime; the week outline's names are not proof
   of account availability. Set a usage cap appropriate to that lane; the existing Claude
   watcher reads Claude `cost_usd` records and cannot be assumed to guard `ours`.
2. Obtain DepMap, record file hash/version, validate feature coverage and missing values,
   then rerun free baselines. DepMap removes the specific sibling-screen feature source;
   it is not evidence that all benchmark or training contamination is absent.
3. Expose BDA through a persistent evaluator-owned service, outside the agent's filesystem.
   Agent interface: public opaque IDs, propose, similarity lookup, and observed-history read.
   Enforce round/batch/retry limits and log every request/response. Keep score tables,
   hit labels, ID-to-symbol mapping, data files and evaluator code outside the agent sandbox.
   Merely excluding them from the seed folder does not prove isolation: verify read boundaries
   with an adversarial smoke check. An empty folder does not isolate a code-capable agent.
4. Run a 2-round smoke test with the prototype and baseline. Confirm hidden-score access is
   denied, legal observations match evaluator state, traces are complete, and scorers agree.
   Only then run 30x16 matched pilots. Keep model, features, task seed and budget fixed.
   Ask for the release's actual tool connection interface before implementing an adapter;
   the available README gives no MCP or IPC registration schema.
5. Extend to 100x32 and multiple paired task seeds once the pilot works. Pin release updates.
   Distinguish fresh-per-round plain-model experiments from persistent code-capable agents;
   changing both scaffold and context policy cannot identify a policy effect. Code-assisted
   filtering is a legitimate scaffold capability, but report its effect on repeats.
6. Add a summary-plus-exact-tested-ID-set control: it separates membership bookkeeping from
   loss of quantitative scores. Report hits versus accepted experiments as well as rounds,
   repeats, short batches, input/output tokens, wall time, compaction events and retrieval cost.
7. Scale meaningful context only after measuring actual prompt occupancy and compaction.
   Add screens or richer evidence with required cross-round dependencies, and extend probe
   delays to 16/32/64; do not equate a nominal 100-round run with ultra-long context stress.
   Keep closed-book probes separate from probes allowed to use memory tools.
8. Sonnet/Haiku are a secondary capability study. A weaker model forgetting would not establish
   a length threshold for the main strong-model comparison. Consider LongDS-Bench only after
   checking its actual data, task semantics and evaluator; no local validation exists here.

## Contamination audit to include in the report

Document public source, release dates, exact dataset hashes, and whether the selected model's
training provenance can be established. Verify the target screen is absent from feature inputs,
check sibling-screen overlap, and record DepMap source and symbol matching. Keep evaluation-only
state inaccessible to the runtime. Opaque names reduce direct gene recall but leave structural
or numerical identification possible. Report residual uncertainty rather than claiming clean
training data. Compare anonymized and real-name arms only as a diagnostic, with fixed features.

## What remained incomplete on November 9

No DepMap CSV is present. No Linux prototype runtime or full interface is supplied. No new
model experiments have been run. A real prototype adapter and comparison remain pending those
inputs; a fabricated adapter based only on the README would not establish compatibility.

## Validation completed

Available BDA, interruption, and audit suites: **17 passed**. The mocked Claude failure test
now skips real retry sleeps. Complete full-run replay exactly matched original totals,
rounds, probes, diagnoses, checks, tested IDs, curve and call count. No new inference calls.
