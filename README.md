<p align="center">
  <img src="https://img.shields.io/badge/Harness_for_Codex-v7.1-brightgreen.svg" alt="Harness for Codex v7.1">
  <img src="https://img.shields.io/badge/Runtime-Codex-111827.svg" alt="Codex Runtime">
  <img src="https://img.shields.io/badge/Type-Harness_Generator-orange.svg" alt="Harness Generator">
  <img src="https://img.shields.io/badge/License-Proprietary-blue.svg" alt="Proprietary License">
</p>

# Harness for Codex

> Generate the smallest evidence-backed Codex agent system that matches a project's persistent decision boundaries.

Harness is a user-level Codex skill. Run it inside a local project workspace and it analyzes the available evidence, selects only justified agent and skill boundaries, and writes a native project harness for later work. A workspace may be a plain directory or a local Git work tree; GitHub is not required.

## What It Generates

```text
target-project/
├── .codex/agents/                 # Project-specific custom agents, when justified
├── .agents/skills/
│   ├── project-harness/           # Project orchestration skill
│   └── <project-skill>/           # Reusable project procedures, when justified
├── .harness/manifest.json         # Ownership, topology, and content hashes
├── .harness/transaction.json      # Present only while recovery or cleanup is required
└── AGENTS.md or AGENTS.override.md # Optional local pointer when the path is safe to manage
```

Simple projects may receive only `project-harness`. Harness does not create a fixed team or assume a frontend/backend architecture. It classifies persistent project topology independently from the execution complexity of any one task.

## Installation

Harness requires Anaconda or Miniconda. Clone this branch, create the dedicated `harness` environment, and copy the generator to the user skill directory.

### PowerShell

```powershell
git clone --branch codex/v7.1 --single-branch https://github.com/sholee-pt/Harness.git Harness
conda env create --file "Harness/environment.yml"
New-Item -ItemType Directory -Force "$HOME/.agents/skills" | Out-Null
New-Item -ItemType Directory -Force "$HOME/.agents/skills/harness" | Out-Null
Copy-Item -Recurse -Force "Harness/.agents/skills/harness/*" "$HOME/.agents/skills/harness"
```

### macOS and Linux

```shell
git clone --branch codex/v7.1 --single-branch https://github.com/sholee-pt/Harness.git Harness
conda env create --file Harness/environment.yml
mkdir -p ~/.agents/skills
mkdir -p ~/.agents/skills/harness
cp -R Harness/.agents/skills/harness/. ~/.agents/skills/harness/
```

Restart Codex if the user skill directory did not exist when the current session started.

If the `harness` environment already exists, replace `conda env create` with `conda env update --name harness --file Harness/environment.yml`.

## Usage

Open the target project directory in Codex and run:

```text
$harness configure a local-only project harness for this workspace.
```

The skill also recognizes direct requests such as “configure the harness” and “하네스를 구성해줘”. Run the same command later to audit or update an existing generated harness.

Harness first creates a structured proposal and runs a no-write dry-run. It applies files only when all ownership, workspace-boundary, local-only, and instruction-precedence checks pass. Changed outputs are staged with backups before a journaled apply, and the manifest is written last. Codex detects skill changes automatically. A newly created `AGENTS.md` pointer applies on a fresh run; if a new custom agent or skill is not visible, start one new task in the same directory. No task deletion or per-request restart is required.

Harness for Codex v7.1 does not ask the model to reproduce fixed change-discipline or runtime-teamplay contracts. Authoring Contract 2 drafts use path-specific placeholders, and `harness_plan_builder.py` deterministically materializes a normal Schema 3 plan before the existing apply validator runs. Every project router and generated agent receives its required canonical block exactly once; an old draft revision, incomplete or unsupported workspace root, or missing, duplicate, or misplaced placeholder fails before any workspace write.

The installed skill includes `references/minimal-draft-plan.json`, so plan authoring does not depend on repository-only test fixtures.

## Local-only Workspaces

Harness for Codex v7.1 never queries GitHub or Git remotes and never stages, commits, pushes, opens pull requests, or changes branches. In a local Git root with exactly one registered worktree, it refuses targets already tracked by Git and writes literal-encoded generated paths to a marker-owned block in the local `info/exclude` file before applying files. Multiple registered worktrees are rejected because that exclude file is shared. A synchronous project-apply failure restores the original exclude bytes only when no transaction is pending and no external edit occurred; an unbound block is detected rather than adopted. These protections prevent ordinary `git add` and status workflows from picking up generated files, but cannot prevent a deliberate force-add or guarantee recovery from process termination before project journaling begins.

Inventory Schema 4 classifies `plain-directory`, `directory-workspace`, `git-repository`, and `git-worktree` roots. A non-Git directory may contain multiple nested repositories, which remain analysis boundaries. A Git root may contain registered submodules, but an unacknowledged independent nested repository remains ambiguous. Root-boundary scanning includes dependency, vendor, output, data, and checkpoint trees even when the content inventory excludes them, and reports truncated or unreadable coverage instead of claiming that no boundary exists.

If `AGENTS.md` or `AGENTS.override.md` is already user-owned or tracked, Harness preserves it byte-for-byte and records `explicit-skill` activation. Use `$project-harness` directly in that case. Harness never creates an override merely to bypass existing project guidance.

## Optional Evaluation

Harness for Codex v7.1 can record local metadata for an explicitly requested run, compare isolated with/without-Harness arms, attribute results only to a plan-bound declared or preassigned configuration delta, ingest structured observations, and probe change-discipline decisions against synthetic cases. The delta comes from immutable arm configuration snapshots; it does not prove that every declared route, agent, skill, or policy was used at runtime. Evaluation is disabled by default and does not change generation, ownership, apply, recovery, or runtime-teamplay validation behavior.

```shell
conda run -n harness python .agents/skills/harness/scripts/harness_eval.py run \
  --root TARGET_REPOSITORY \
  --task-file TASK.txt \
  --sandbox read-only

conda run -n harness python .agents/skills/harness/scripts/harness_eval.py list

conda run -n harness python .agents/skills/harness/scripts/harness_eval.py add-observation \
  --run RUN_ID \
  --report OBSERVATION.json

conda run -n harness python .agents/skills/harness/scripts/harness_eval.py view \
  --run RUN_ID

conda run -n harness python .agents/skills/harness/scripts/harness_eval.py change-discipline-suite \
  --root TARGET_REPOSITORY \
  --cases tests/fixtures/evaluation/change-discipline-cases.json
```

Run records distinguish measured empty sets, unavailable values, and non-applicable concepts. Schema 2 separately records declared configuration, expected execution, runtime discovery, and observed execution. Raw prompts, reports, component names, transcripts, commands, paths, source content, and JSONL events are not written to Harness evaluation state. `--ephemeral` prevents local Codex rollout persistence; service-side processing still follows the configured Codex account and provider policy.

The change-discipline suite checks a model's declared decision and behavior tags for four synthetic cases: material ambiguity, a one-line direct change, a file-scoped bug fix, and verification-first handling of a reproducible bug. It is a classification probe, not proof that a later code-editing run followed the declared behavior. Use `--validate-only` to validate the fixture without invoking Codex.

See [evaluation-contract.md](.agents/skills/harness/references/evaluation-contract.md) for the boundary, [run-record-schema.md](.agents/skills/harness/references/run-record-schema.md) for schemas, and [evaluation-isolation.md](.agents/skills/harness/references/evaluation-isolation.md) before paired runs.

Paired runs require Comparison Plan Schema 2 before either arm executes, including a declared intervention and task stratum. The resulting comparisons are bound to that plan digest. Standalone comparisons are also plan-bound, but Harness does not claim that their plans existed before the underlying runs or provide durable preregistration. Paired runs accept `--repetitions` and an `--order` policy of `randomized`, `counterbalanced`, `baseline-first`, or `harness-first`. Each arm uses an isolated temporary user home and a clean synthetic pre-task commit while retaining the original user commit as the shared source snapshot. Task fingerprinting and patch-scope measurement occur immediately after Codex exits. Verification profiles must not change repository content, `HEAD`, symbolic `HEAD`, index entries, or porcelain status; a changed or non-quiescent repository is retained descriptively with partial comparability and a `verification-repository-state-mutated` gap. Verification runs in a dedicated process group and its cleanup must be confirmed. Known Harness skills in user, compatibility, Codex-home, or readable POSIX admin locations downgrade isolation; a dirty dedicated `CODEX_HOME` is rejected. Fixed arm order is retained as an explicit confounder. Windows runs require a matching user-local cleanup receipt before isolation can be labelled complete.

Structured reports use raw logical component IDs only as user-owned input. Ingest validates those IDs against the immutable configuration snapshot attached to that run, stores only local HMAC pseudonyms, and never copies the report. Observations are create-only supplements, replacements, or terminal withdrawals. Annotation Schema 2 similarly maintains one active user-outcome chain. The `view` command computes current selected values, field-specific provenance, protocol deviations, and conflicts without persisting a second source of truth.

Patch-scope evaluation is optional. A user-owned profile declares allowed path scopes and budgets; rename and copy operations count both affected paths. If untracked files exist while a line budget is active, completeness is conservatively partial because their line count is not inferred. The run stores only its digest, counts, and pseudonymous path references. It verifies path scope, not semantic minimality.

Concrete positive or negative configuration attribution requires `propose --comparison-plan PLAN.json`. The plan hash and attribution target must match every included comparison. Proposal support counts only complete comparisons made from independent Run pairs; partial comparisons remain individually inspectable but are excluded from pair counts, direction statistics, and candidates. Reusing either Run in the same attribution group excludes every connected comparison instead of selecting a favorable subset. A changed Observation or Annotation makes its older Comparison stale, while a new Comparison over the same Run pair is allowed when the Derived View fingerprints differ. If more than one concrete-eligible evaluation stratum remains, `propose` requires an explicit `--evaluation-stratum SHA256` instead of choosing a favorable group; a well-formed fingerprint that is absent from the matching comparisons is an error rather than a no-change proposal. Without a verified plan, or with a descriptive-only target, Harness emits only an experiment suggestion or no-change record and leaves the candidate empty. When a plan declares patch scope, both arms must have a complete matching measurement and stay within the declared limits; incomplete or violated scope remains descriptive evidence but cannot support a concrete proposal.

## Runtime Teamplay

Harness for Codex v7.1 keeps persistent workspace topology separate from current-task execution. It creates no permanent team merely because multiple agents exist. A temporary runtime plan selects `direct`, `delegated`, or `coordinated` execution from interaction value: independent work delegates, one review pass uses delegated producer-reviewer, and only repeated feedback, conflicting expert judgment, cross-boundary agreement, or dynamic reassignment justifies coordination.

Runtime plans are bound to the exact manifest and canonical topology, validated before execution, and ephemeral by default. Their `participants` are the persistent agents activated for the current task. For delegated or coordinated work, Codex is instructed to spawn only those custom agents, collect parent-facing coordination packets, relay material evidence to affected agents, and keep final integration and task state under parent control. Parallel delegation uses `codex-subagent-relay`; unavailable delegation falls back to sequential relay or direct execution while preserving input, output, and verification contracts. Runtime roles and task state are never inserted into the persistent manifest.

```shell
conda run -n harness python .agents/skills/harness/scripts/validate_runtime_plan.py \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json

conda run -n harness python .agents/skills/harness/scripts/validate_coordination_packet.py \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json \
  --packet COORDINATION_PACKET.json

conda run -n harness python .agents/skills/harness/scripts/harness_relay_receipt.py \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json \
  --receipt RELAY_RECEIPT.json
```

See [teamplay-contract.md](.agents/skills/harness/references/teamplay-contract.md), [runtime-plan.md](.agents/skills/harness/references/runtime-plan.md), [native-subagent-relay.md](.agents/skills/harness/references/native-subagent-relay.md), [runtime-observation.md](.agents/skills/harness/references/runtime-observation.md), [relay-receipt.md](.agents/skills/harness/references/relay-receipt.md), and [team-recipes.md](.agents/skills/harness/references/team-recipes.md). v7.1 keeps Codex as the execution engine while using canonical receiver handles for bounded control, optional versioned public/local observation profiles for evidence, required-task accounting, and hash-bound offline review lineage. Capability policies use a small canonical registry so validated names cannot silently select a different fallback path. Missing observation evidence lowers confidence without cancelling a valid handle execution; verified binding or terminal-outcome contradictions fail closed.

## Design Rules

- Workspace evidence determines roles, skills, and orchestration. Every evidence claim is bound to an existing file hash and may identify an exact line range.
- Persistent material boundaries record topology-wide unique decision-area IDs, project persistence, contracts, verification, failure impact, and separation benefits.
- Project topology is `minimal`, `modular`, or `coordinated`. Boundary count alone does not force coordination; recurring workspace-level coordination does.
- Current tasks are routed independently as `direct`, `delegated`, or `coordinated`. One-off task risk is never persisted as project topology.
- Runtime coordination is selected from repeated interaction value, not agent count, repository size, or simple parallelism.
- Runtime roles, tasks, messages, adapter choice, and retention live only in a manifest-bound ephemeral plan.
- Six collaboration patterns are available as design vocabulary, not mandatory templates.
- Quality patterns are separate policies with workspace evidence, finite budgets, stopping conditions, and failure handling.
- Concurrent writers may not overlap. Ordered overlapping writers require a verified handoff covering their complete shared scope between explicit execution lanes.
- Literal file scopes cannot authorize recursive directory scopes. Writer overlap is compared case-insensitively for portable Windows safety.
- A persistent task category belongs to at most one route. Multiple matches may share one route; conflicting routes are reported as ambiguous instead of being merged or selected by order. If no route matches, the current task is classified at runtime instead of defaulting blindly to direct execution.
- Runtime capability declarations require a probe and contract-preserving fallback when a special capability is needed.
- Runtime packets are bounded; challenges require evidence, relays cannot expand write scope, and required artifacts cannot be silently omitted.
- User-owned files and edits are never silently overwritten.
- Planned and recorded output paths reject case-only collisions and file/child target conflicts before transaction staging.
- Generated files are updated only when their recorded hash still matches.
- Outputs classified as unchanged are not rewritten.
- A failed multi-file apply is rolled back from verified backups before another plan may run. POSIX file permission modes are restored with content.
- Phase outputs are treated as frozen only when hashes were actually recorded.
- Authentication, permission, and quota failures are reported without pointless retries.
- Runtime and model settings are inherited unless workspace evidence requires an override.
- Code-changing work surfaces material ambiguity and simpler alternatives, uses the smallest scoped edit, avoids adjacent cleanup, defines verification before implementation, and reports unverified outcomes explicitly.

## Validation

The generator includes standard-library-only Python tools. Run them through the dedicated Conda environment:

```shell
conda run -n harness python .agents/skills/harness/scripts/inventory.py .
conda run -n harness python .agents/skills/harness/scripts/harness_state.py evidence --root . --path PATH_TO_EVIDENCE
conda run -n harness python .agents/skills/harness/scripts/harness_state.py status --root .
conda run -n harness python .agents/skills/harness/scripts/harness_plan_builder.py --root . --input DRAFT_PLAN.json --output PLAN.json
conda run -n harness python .agents/skills/harness/scripts/harness_apply.py --root . --plan PATH_TO_PLAN.json --dry-run
conda run -n harness python .agents/skills/harness/scripts/harness_apply.py --root . --inspect-transaction
conda run -n harness python .agents/skills/harness/scripts/harness_apply.py --root . --recover
conda run -n harness python .agents/skills/harness/scripts/harness_apply.py --root . --clean-orphaned-transaction
conda run -n harness python .agents/skills/harness/scripts/validate_harness.py .
conda run -n harness python .agents/skills/harness/scripts/validate_runtime_plan.py --root . --plan PATH_TO_RUNTIME_PLAN.json
conda run -n harness python .agents/skills/harness/scripts/validate_coordination_packet.py --root . --plan PATH_TO_RUNTIME_PLAN.json --packet PATH_TO_PACKET.json
conda run -n harness python .agents/skills/harness/scripts/harness_runtime_receipt.py --root . --plan PATH_TO_RUNTIME_PLAN.json --jsonl PATH_TO_CODEX_EVENTS.jsonl --public-profile codex-public-jsonl-core-v1 --control-plane-report PATH_TO_CONTROL_PLANE_REPORT.json --codex-cli-version 0.152.1 --execution-mode persistent --repository-id repo-0123456789abcdef --harness-commit 0123456789abcdef0123456789abcdef01234567 --salt-file PATH_TO_TEMPORARY_SALT
conda run -n harness python .agents/skills/harness/scripts/harness_relay_receipt.py --root . --plan PATH_TO_RUNTIME_PLAN.json --receipt PATH_TO_RELAY_RECEIPT.json
conda run -n harness python .agents/skills/harness/scripts/evaluate_topology.py --plan PATH_TO_PLAN.json --golden PATH_TO_GOLDEN.json
conda run -n harness python .agents/skills/harness/scripts/harness_eval.py --help
conda run -n harness python -m unittest discover -s tests -v
```

Inventory Schema 4 reports workspace kind, root-scan completeness, Conda manifests, conservative code/config/docs/test/artifact/unknown role counts, nested local Git roots, and research-output directories separately. Independent nested repositories are allowed as boundaries in a non-Git directory workspace but require a narrower selection inside a Git root; registered submodules do not. Known output directories are excluded from content classification by default but remain visible to the boundary scan, and can be inspected deliberately with `--include-artifacts`. Existing instruction precedence and the instruction path Harness could safely manage are reported separately.

`evaluate_topology.py` validates only the persistent topology contract and reports `evidenceValidated: false`. It does not replace the evidence, ownership, and no-write checks performed by `harness_apply.py --dry-run`.

Use `--recover` only when status or a failed apply reports a pending journal. Use `--inspect-transaction` before maintenance. `--clean-orphaned-transaction` is restricted to the reserved staging directory when no journal exists; it never replaces recovery for a valid journal. Recovery first verifies that interrupted outputs were not edited externally and refuses destructive cleanup when their hashes are unknown.

If Windows Conda raises `UnicodeEncodeError` while forwarding a child-process error, inspect transaction status before retrying and rerun the diagnostic with `conda run --no-capture-output -n harness python ...`. This keeps the required environment while exposing the original Harness result.

Harness for Codex v7.1 keeps generation plan schema 3, manifest schema 6, transaction schema 2, runtime-plan schema 1, coordination-packet schema 1, relay-receipt schema 1, and Evaluation Schema 2. Inventory Schema 4 and Runtime Receipt Schema 2 also remain unchanged. Evaluation records from v6.0 through v7.0 remain readable for descriptive inspection, while only v7.1 runs in complete, independent, plan-verified comparison pairs are eligible for concrete attribution. Runtime-plan, packet, relay, and receipt validation cannot alter persistent topology. Clean Manifest Schema 4 or 5 installations require workspace re-analysis and a reviewed Schema 3 plan; any tracked legacy Harness target must be untracked manually before local-only conversion.

## Versioning

- Harness for Codex releases use `codex/vN` or `codex/vN.M` branches. The number identifies the Harness release, not the Codex product version.
- Harness for Claude Code releases use runtime-specific `claude/vN` or `claude/vN.M` branches.
- Displayed Harness and generator versions use two components (`N.M`). Existing major branches such as `codex/v5` represent their `.0` release and remain unchanged.
- Breaking generator changes start a new branch version.

See [VERSIONS.md](VERSIONS.md) for compatibility, migration, and release differences.

Claude-native editions are maintained independently on the repository's `claude/*` branches.

## License

This repository is proprietary and intended for the copyright holder's private use. See [LICENSE](LICENSE).
