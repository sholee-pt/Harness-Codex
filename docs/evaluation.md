# Quality evaluation and local evidence

Evaluation purge removes evaluation records while preserving active pending runs and opaque registry identities. Stable identities prevent retained operations evidence and concurrent writes from becoming unreachable. New operations records are scoped to the selected workspace rather than its enclosing Git repository; older shared records are retained separately and are not attributed to a workspace automatically.

## Optional Local Operations Evidence

The current Harness for Codex can observe long-running interactive use without treating one CLI session as one task. Each `UserPromptSubmit` turn becomes a separate pseudonymous work item. Subagent lifecycle events, enum-only execution and agent-selection assessments, verification state, outcome, and an optional relationship to an earlier turn are attached to that work item. Explicit acceptance, correction, refinement, follow-up, reopened work, cancellation, or an unrelated new task can therefore be distinguished inside the same session.

This mode is disabled until the user explicitly installs the user-level hook. Generate a candidate configuration first:

```shell
harness-codex helper harness_ops hooks-template
```

If `~/.codex/hooks.json` does not exist, it may be created explicitly with `--output ~/.codex/hooks.json`. Existing hook files are never overwritten; merge the printed entries manually and review or trust them with `/hooks`. The handler ignores directories without a current project-local Harness manifest, so installing the user hook does not turn every filesystem directory into a Harness workspace.

The hook stores no raw prompt, response, transcript, agent name, or absolute path. Local HMAC references and finite enums are written only to the user-local Harness state directory. Completion is not treated as success, agent-reported success is not user acceptance, and missing evidence remains `unknown`. Operations evidence never changes topology or regenerates agents automatically.

An annotation can explicitly link a recurring harness concern or a particular maintenance change using the [maintenance options](maintenance.md#change-outcomes-and-recovery). This reuses an existing work-item observation rather than adding another per-turn evaluator. The bridge does not infer a persistent defect from an ordinary task failure, enable maintenance, or automatically apply a comparison proposal. Model/runtime differences remain separate context groups and descriptive observations never establish causal benefit.

```shell
harness-codex helper harness_ops audit --root TARGET_WORKSPACE
harness-codex helper harness_ops purge --root TARGET_WORKSPACE
```

An audit reports task-level routing, agent use, verification, adverse outcomes, later correction or reopen relationships, and evidence gaps. It is a review signal rather than proof of semantic quality. See [operations-evidence.md](../.agents/skills/harness/references/operations-evidence.md) for trust, privacy, retention, and interpretation rules.


## Optional Evaluation

The current Harness for Codex can record local metadata for an explicitly requested run, compare isolated with/without-Harness arms, attribute results only to a plan-bound declared or preassigned configuration delta, ingest structured observations, and probe change-discipline decisions against synthetic cases. The delta comes from immutable arm configuration snapshots; it does not prove that every declared route, agent, skill, or policy was used at runtime. Evaluation is disabled by default and does not change generation, ownership, apply, recovery, operations evidence, or runtime-teamplay validation behavior.

```shell
harness-codex helper harness_eval run \
  --root TARGET_REPOSITORY \
  --task-file TASK.txt \
  --sandbox read-only

harness-codex helper harness_eval list

harness-codex helper harness_eval add-observation \
  --run RUN_ID \
  --report OBSERVATION.json

harness-codex helper harness_eval view \
  --run RUN_ID

harness-codex helper harness_eval change-discipline-suite \
  --root TARGET_REPOSITORY \
  --cases test/fixtures/evaluation/change-discipline-cases.json
```

Run records distinguish measured empty sets, unavailable values, and non-applicable concepts. Schema 2 separately records declared configuration, expected execution, runtime discovery, and observed execution. Raw prompts, reports, component names, transcripts, commands, paths, source content, and JSONL events are not written to Harness evaluation state. `--ephemeral` prevents local Codex rollout persistence; service-side processing still follows the configured Codex account and provider policy.

The `view` output includes a presentation-only `usageSummary` that preserves selected measurements, reported-only values, missing counters, conflicts, and partial coverage. Terminal-event counters do not establish parent-only, all-child, or account-wide usage. Harness does not sum overlapping counters or infer billing cost. Comparison plans can select `input-tokens`, `cached-input-tokens`, `output-tokens`, and `reasoning-output-tokens` individually; these are counter comparisons, not total-cost attribution. See [capture-provenance.md](../.agents/skills/harness/references/capture-provenance.md). Existing records and comparison view fingerprints are not rewritten by this display supplement.

The change-discipline suite checks a model's declared decision and behavior tags for four synthetic cases: material ambiguity, a one-line direct change, a file-scoped bug fix, and verification-first handling of a reproducible bug. It is a classification probe, not proof that a later code-editing run followed the declared behavior. Use `--validate-only` to validate the fixture without invoking Codex.

See [evaluation-contract.md](../.agents/skills/harness/references/evaluation-contract.md) for the boundary, [run-record-schema.md](../.agents/skills/harness/references/run-record-schema.md) for schemas, and [evaluation-isolation.md](../.agents/skills/harness/references/evaluation-isolation.md) before paired runs.

Paired runs require a clean Git-root source with a valid compatible project-local Harness installation, exactly one registered worktree, untracked Harness-managed outputs, and Comparison Plan Schema 2. These are optional evaluation preconditions; they do not restrict generation. The user chooses the source Git exclusion/cleanliness policy, since generation no longer installs one. The evaluator verifies and snapshots manifest-managed files, every manifest-referenced evidence file, and bounded project context that can alter Codex behavior: root instruction candidates, `.codex/config.toml`, unmanaged `.codex/agents/*.toml`, and unmanaged `.agents/skills/**`. It then creates two independent local clones at that commit, removes every remote, and gives each clone its own Git metadata and exclusion file. Tracked, ignored, and untracked evidence and project context are materialized identically in both arms. All destinations in both arms are checked before the first write, including lexical symlink, Windows reparse-point, directory-collision, and namespace conflicts. Evidence under `.git/**` or `.harness/**` is rejected before content is read or hashed.

The baseline removes generated-only instruction files completely, then re-runs the same root instruction discovery used during generation so an existing fallback can become active. If a managed instruction file also contains preserved user content but its exact pre-install bytes are unavailable, that content remains in both arms and the comparison records `baseline-instruction-provenance-unavailable`, making it descriptive rather than eligible for concrete attribution. Immediately before clean synthetic pre-task commits are created, the evaluator rechecks evidence and project-context bytes and modes, absence of baseline Harness state, treatment validity, remote removal, source commits, allowed changed paths, and instruction selection. Ignored context is literal force-added to both task bases, and the indexed blob and executable bit are verified so later fingerprints measure changes to those paths. A present `.codex/config.toml` is preserved and hashed, but materialization is not proof that Codex effectively loaded it: until a deterministic load receipt exists, the pair records `project-config-load-unverified`, remains partial, and cannot support concrete configuration attribution. Likewise, unmanaged custom-agent files are preserved symmetrically, but their registry discovery, selected configuration layer, external skill references, and MCP dependencies are not inferred from file presence. A pair containing them records `project-agent-load-unverified` and remains descriptive until deterministic discovery and selected-agent dependency receipts exist. User and project rules are intentionally disabled by `--ignore-rules`; project hooks are not enabled by this evaluator. Paired runs accept `--repetitions` and an `--order` policy of `randomized`, `counterbalanced`, `baseline-first`, or `harness-first`. Task fingerprinting and patch-scope measurement occur immediately after Codex exits. Verification profiles must not change repository content, `HEAD`, symbolic `HEAD`, index entries, or porcelain status; a changed or non-quiescent repository is retained descriptively with partial comparability and a `verification-repository-state-mutated` gap. Verification runs in a dedicated process group and its cleanup must be confirmed. Known Harness skills in user, compatibility, Codex-home, or readable POSIX admin locations downgrade isolation; a dirty dedicated `CODEX_HOME` is rejected. Fixed arm order is retained as an explicit confounder. Windows cleanup cannot verify already orphaned descendants and therefore remains unverified per run; a matching user-local receipt alone cannot establish complete isolation.

Default `paired-run --dry-run` validates source prerequisites without cloning and separately reports project-context discovery, project-config presence, custom-agent count, `projectConfigMaterialized: false`, effective configuration and agent-load status, dependency-verification status, and an unobserved remote-retention result. Add `--validate-materialization` to create disposable clones, reconstruct both arms, verify their task bases, and report exact context materialization and the actually observed no-remote result without invoking Codex or writing evaluation state.

Structured reports use raw logical component IDs only as user-owned input. Ingest validates those IDs against the immutable configuration snapshot attached to that run, stores only local HMAC pseudonyms, and never copies the report. Observations are create-only supplements, replacements, or terminal withdrawals. Annotation Schema 2 similarly maintains one active user-outcome chain. The `view` command computes current selected values, field-specific provenance, protocol deviations, and conflicts without persisting a second source of truth.

Patch-scope evaluation is optional. A user-owned profile declares allowed path scopes and budgets; rename and copy operations count both affected paths. If untracked files exist while a line budget is active, completeness is conservatively partial because their line count is not inferred. The run stores only its digest, counts, and pseudonymous path references. It verifies path scope, not semantic minimality.

Concrete positive or negative configuration attribution requires `propose --comparison-plan PLAN.json`. The plan hash and attribution target must match every included comparison. Proposal support counts only complete comparisons made from independent Run pairs; partial comparisons remain individually inspectable but are excluded from pair counts, direction statistics, and candidates. Reusing either Run in the same attribution group excludes every connected comparison instead of selecting a favorable subset. A changed Observation or Annotation makes its older Comparison stale, while a new Comparison over the same Run pair is allowed when the Derived View fingerprints differ. If more than one concrete-eligible evaluation stratum remains, `propose` requires an explicit `--evaluation-stratum SHA256` instead of choosing a favorable group; a well-formed fingerprint that is absent from the matching comparisons is an error rather than a no-change proposal. Without a verified plan, or with a descriptive-only target, Harness emits only an experiment suggestion or no-change record and leaves the candidate empty. When a plan declares patch scope, both arms must have a complete matching measurement and stay within the declared limits; incomplete or violated scope remains descriptive evidence but cannot support a concrete proposal.


## Validation

The generator includes standard-library-only Python tools. Run them through the dedicated Conda environment:

```shell
harness-codex helper inventory .
harness-codex helper harness_state evidence --root . --path PATH_TO_EVIDENCE
harness-codex helper harness_state status --root .
harness-codex helper harness_plan_builder --root . --input DRAFT_PLAN.json --output PLAN.json
harness-codex helper harness_apply --root . --plan PATH_TO_PLAN.json --dry-run
harness-codex helper harness_apply --root . --inspect-transaction
harness-codex helper harness_apply --root . --recover
harness-codex helper harness_apply --root . --clean-orphaned-transaction
harness-codex helper validate_harness .
harness-codex helper validate_runtime_plan --root . --plan PATH_TO_RUNTIME_PLAN.json
harness-codex helper validate_coordination_packet --root . --plan PATH_TO_RUNTIME_PLAN.json --packet PATH_TO_PACKET.json
harness-codex helper harness_runtime_receipt --root . --plan PATH_TO_RUNTIME_PLAN.json --jsonl PATH_TO_CODEX_EVENTS.jsonl --public-profile codex-public-jsonl-core-v1 --control-plane-report PATH_TO_CONTROL_PLANE_REPORT.json --codex-cli-version 0.152.1 --execution-mode persistent --repository-id repo-0123456789abcdef --harness-commit 0123456789abcdef0123456789abcdef01234567 --salt-file PATH_TO_TEMPORARY_SALT
harness-codex helper harness_relay_receipt --root . --plan PATH_TO_RUNTIME_PLAN.json --receipt PATH_TO_RELAY_RECEIPT.json
harness-codex helper evaluate_topology --plan PATH_TO_PLAN.json --golden PATH_TO_GOLDEN.json
harness-codex helper harness_eval --help
conda run -n harness python -m unittest discover -s test -v
```

Inventory Schema 5 reports the selected workspace kind, bounded scan coverage, Conda manifests, conservative file roles, known nested Git boundaries, and research-output directories separately. Known output directories are excluded from content classification by default and may be inspected deliberately with `--include-artifacts`. Scan uncertainty never changes the selected root. Existing instruction precedence and the instruction path Harness could safely manage are reported separately.

`evaluate_topology.py` validates only the persistent topology contract and reports `evidenceValidated: false`. It does not replace the evidence, ownership, and no-write checks performed by `harness_apply.py --dry-run`.

Use `--recover` only when status or a failed apply reports a pending journal. Use `--inspect-transaction` before maintenance. `--clean-orphaned-transaction` is restricted to the reserved staging directory when no journal exists; it never replaces recovery for a valid journal. Recovery first verifies that interrupted outputs were not edited externally and refuses destructive cleanup when their hashes are unknown.

If Windows Conda raises `UnicodeEncodeError` while forwarding a child-process error, inspect transaction status before retrying and rerun the diagnostic with `conda run --no-capture-output -n harness python ...`. This keeps the required environment while exposing the original Harness result.

The current Harness for Codex uses Manifest Schema 7, Artifact Contract 2, Inventory Schema 5, and Root Context Schema 3. Authoring Contract 3, generation Plan Schema 3, Transaction Schema 2, runtime-plan Schema 1, coordination-packet Schema 1, relay-receipt Schema 1, Runtime Receipt Schema 2, and Evaluation Schema 2 remain unchanged. Operations Event Schema 1 remains separate user-local evidence. Supported historical evaluation records remain readable descriptively; only runs from the current release in complete, independent, plan-verified pairs support concrete attribution. Persistent topology is not changed by runtime, relay, receipt, operations, or evaluation validation.

