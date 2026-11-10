# Week 4 / week-3 direction: local review, November 9, 2026

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

## What remains incomplete

No DepMap CSV is present. No Linux prototype runtime or full interface is supplied. No new
model experiments have been run. A real prototype adapter and comparison remain pending those
inputs; a fabricated adapter based only on the README would not establish compatibility.

## Validation completed

Available BDA, interruption, and audit suites: **17 passed**. The mocked Claude failure test
now skips real retry sleeps. Complete full-run replay exactly matched original totals,
rounds, probes, diagnoses, checks, tested IDs, curve and call count. No new inference calls.
