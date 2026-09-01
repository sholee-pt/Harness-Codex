# Harness Version History

Harness releases are maintained as runtime-specific branches. Names such as `codex/v5.1` mean **Harness for Codex v5.1**; they do not identify the Codex product or model version. Displayed release and generator versions use two components (`N.M`). A major Harness version changes a generation contract, state format, ownership model, or required workflow. A minor Harness version contains backward-compatible corrections and validation improvements.

## Harness for Codex releases

| Branch | Harness release | Plan | Manifest | Transaction | Main change or patch |
| --- | --- | --- | --- | --- | --- |
| `codex/v1` | Harness for Codex v1.0 | Direct generation | Schema 1 | None | Project-adaptive agents and skills, native Codex paths, initial ownership manifest |
| `codex/v2` | Harness for Codex v2.0 | Schema 1 | Schema 2 | None | JSON proposal, no-write dry-run, guarded deterministic apply, instruction precedence |
| `codex/v2.1` | Harness for Codex v2.1 | Schema 1 | Schema 2 | None | True no-op updates, complete action-map checks, CI and fixture dry-run corrections |
| `codex/v3` | Harness for Codex v3.0 | Schema 1 | Schema 3 | Schema 1 | Journaled multi-file apply, verified staging, rollback, recovery, manifest-last commit |
| `codex/v3.1` | Harness for Codex v3.1 | Schema 1 | Schema 3 | Schema 1 | Recovery hardening, orphan inspection and cleanup, directory sync, live smoke-test guide |
| `codex/v4` | Harness for Codex v4.0 | Schema 2 | Schema 4 | Schema 2 | SHA-256-bound structured evidence, line ranges, POSIX permission tracking and recovery |
| `codex/v5` | Harness for Codex v5.0 | Schema 3 | Schema 5 | Schema 2 | Machine-verifiable material boundaries, persistent topology classes, routing and quality contracts, deterministic golden evaluation |
| `codex/v5.1` | Harness for Codex v5.1 | Schema 3 | Schema 5 | Schema 2 | Literal/prefix scope correction, portable case collision checks, topology cross-validation, unambiguous routing, exact quality budgets, expanded fixtures and Windows CI |
| `codex/v5.2` | Harness for Codex v5.2 | Schema 3 | Schema 5 | Schema 2 | Portable output namespace validation, complete-overlap handoffs, unique decision ownership, linked coordination witnesses, coordinated full-plan integration |
| `codex/v5.3` | Harness for Codex v5.3 | Schema 3 | Schema 5 | Schema 2 | Default-off local evaluation, JSONL provenance, isolated paired comparison, immutable records, non-binding evidence proposals |
| `codex/v5.4` | Harness for Codex v5.4 | Schema 3 | Schema 5 | Schema 2 | Minimal-change discipline, self-contained writer safeguards, four-case behavioral classification probe |
| `codex/v5.5` | Harness for Codex v5.5 | Schema 3 | Schema 5 | Schema 2 | Canonical discipline enforcement, complete bounded result fingerprints, isolated user homes, annotation semantics, experiment-only positive proposals |
| `codex/v6` | Harness for Codex v6.0 | Schema 3 | Schema 5 | Schema 2 | Evaluation Schema 2, declared configuration-delta attribution, observation and annotation lifecycles, derived views, structured ingest, patch-scope evaluation |
| `codex/v6.1` | Harness for Codex v6.1 | Schema 3 | Schema 5 | Schema 2 | Plan-bound positive and negative attribution, conservative patch-scope eligibility, exact symmetric support thresholds, v6.0/v6.1 evidence separation |
| `codex/v6.2` | Harness for Codex v6.2 | Schema 3 | Schema 5 | Schema 2 | Independent complete evidence units, arm-specific task bases, store-verified proposal eligibility, runtime-stratum and untracked-budget corrections |
| `codex/v6.3` | Harness for Codex v6.3 | Schema 3 | Schema 5 | Schema 2 | Derived-view comparison lifecycle, verification-pure task measurement, explicit stratum selection, auxiliary binding and clean-tree hardening |

All earlier branches remain preserved for existing installations. New changes are added on a later Harness branch rather than rewriting a published version branch.

## Harness for Codex v1.0

Harness for Codex v1.0 introduced the project-adaptive generator.

- Inspects repository evidence before choosing a topology.
- Generates native Codex artifacts under `.codex/agents/`, `.agents/skills/`, and `AGENTS.md`.
- Records generated paths in `.harness/manifest.json` using manifest schema 1.
- Supports role, skill, and orchestrator generation without assuming a frontend/backend split.
- Uses the original direct-generation and validation workflow.

This branch receives documentation or critical maintenance corrections only.

## Harness for Codex v2.0

Harness for Codex v2.0 added a guarded and reproducible generation lifecycle.

- Separates analysis from mutation through generation plan schema 1.
- Requires a no-write dry-run before applying a plan.
- Applies artifacts through deterministic `harness_apply.py` validation.
- Refuses the complete update before writing when ownership checks or managed hashes conflict.
- Preserves user-owned content and detects `AGENTS.override.md` precedence.
- Introduces manifest schema 2 with topology rationale, artifact purpose, and the active instruction path.
- Adds the dedicated Anaconda `harness` environment and fixture-based validation.

## Harness for Codex v2.1

Harness for Codex v2.1 patched the v2.0 lifecycle without changing its plan or manifest schemas.

- Skips writes for artifacts, root instructions, and manifests classified as unchanged.
- Validates the complete action map before the first write.
- Adds regression coverage proving unchanged applies perform no writes.
- Adds automated unit-test and fixture dry-run checks.
- Declares the limited generated skill-frontmatter contract and removes an unused YAML dependency.

Existing clean Harness for Codex v2.0 manifests remain compatible.

## Harness for Codex v3.0

Harness for Codex v3.0 replaced sequential multi-file mutation with a recoverable journaled lifecycle.

- Introduces manifest schema 3 and transaction schema 1.
- Revalidates managed hashes and create-path absence immediately before staging.
- Requires normalized POSIX-relative managed paths and rejects traversal.
- Stages every changed output and preserves verified backups before mutation.
- Writes `.harness/transaction.json` before replacing targets and commits the manifest last.
- Rolls back updates and transaction-created files after ordinary mid-apply failures.
- Supports explicit recovery after process interruption.
- Preserves externally edited interrupted targets and leaves the journal for manual resolution.

The filesystem cannot atomically replace unrelated paths as one operation. Transaction schema 1 therefore defines recoverability rather than claiming full multi-file atomicity.

## Harness for Codex v3.1

Harness for Codex v3.1 hardened v3.0 without changing the generation or state schemas.

- Corrects stale release text in repository instructions.
- Reports incomplete legacy evidence without silently fabricating semantic claims.
- Adds non-mutating transaction inspection and explicit orphaned-workspace cleanup.
- Synchronizes parent directory entries after atomic replacement on supported POSIX filesystems.
- Documents a repeatable live Codex discovery and delegation smoke test.

## Harness for Codex v4.0

Harness for Codex v4.0 made evidence and portable permission behavior deterministic contracts.

- Introduces generation plan schema 2 with `path`, `sha256`, `claim`, and optional line ranges.
- Rejects missing, escaped, stale, or out-of-range evidence before planning mutations.
- Introduces manifest schema 4 for auditable evidence hashes and generated-file modes.
- Introduces transaction schema 2 with original and desired permission modes.
- Applies and restores POSIX permissions with content; Windows retains platform-native behavior.
- Adds a read-only evidence helper for normalized paths and SHA-256 values.
- Prepares clean schema 1-3 manifests as schema 4 when all legacy evidence paths still resolve.

Evidence hashes prove which unchanged bytes a claim references; semantic truth remains a review responsibility.

## Harness for Codex v5.0

Harness for Codex v5.0 promotes v4.0 topology guidance into a machine-verifiable contract while retaining transaction schema 2.

- Introduces generation plan schema 3 and manifest schema 5.
- Records persistent material boundaries with stable decision-area IDs, repository evidence, persistence, contracts, verification, and separation benefits.
- Separates persistent project topology (`minimal`, `modular`, `coordinated`) from runtime task execution (`direct`, `delegated`, `coordinated`).
- Prevents one-off task risk from permanently promoting project topology.
- Records boundary merge results and requires explicit rationale for retained overlaps.
- Separates collaboration patterns from bounded, evidence-backed quality policies.
- Links specialist and cross-boundary agents to material boundaries while keeping `project-harness` project-scoped.
- Rejects concurrent writer overlap and requires verified handoffs for ordered overlapping writers.
- Adds capability policies with runtime probes and contract-preserving fallbacks.
- Adds evidence-backed routing policies without persisting the current task's selected route.
- Adds deterministic golden evaluation based on stable decision-area IDs rather than semantic string similarity.
- Keeps model inheritance as the default and does not add an unverified persistent model-selection schema.

Harness for Codex v4.0 → v5.0 is a reviewed regeneration upgrade. Harness validates the clean v4.0 ownership state, re-analyzes the repository, dry-runs a schema 3 plan, and writes schema 5 only through the existing journaled apply. It does not infer material boundaries from legacy manifest fields.

## Harness for Codex v5.1

Harness for Codex v5.1 stabilizes the v5.0 contract without changing plan, manifest, or transaction schemas.

- Distinguishes literal file scopes from recursive `/**` scopes during access containment checks.
- Treats case-only writer overlaps as conflicts on every platform for portable Windows safety.
- Requires persistent task categories to belong to only one routing policy and rejects direct routes that declare collaboration patterns.
- Cross-validates `independent`, `cyclic-contract`, and `dynamic` dependency shapes against declared relationships.
- Binds coordination reasons to supporting patterns, contract boundaries, phases, and verified handoffs.
- Requires exact pattern-specific quality budget keys and validates loop budget relationships.
- Labels deterministic evaluation output as topology-only and explicitly reports that evidence was not validated.
- Adds modular expert-pool and coordinated cross-contract golden fixtures.
- Runs CI on both Ubuntu and Windows.
- Uses two-component Harness and generator versions such as `5.1`.

Harness for Codex v5.0 plans and manifests remain on schema 3 and schema 5. The stricter validator may reject previously accepted ambiguous topology declarations; regenerate and review such plans before applying them.

## Harness for Codex v5.2

Harness for Codex v5.2 hardens v5.1 without changing plan, manifest, or transaction schemas.

- Rejects case-only artifact, application, manifest, and transaction target collisions before staging.
- Rejects output sets in which one file target is an ancestor of another file target.
- Requires ordered writer handoffs to name the complete intersection of their write scopes.
- Requires `decisionAreaIds` to have one topology-wide owner.
- Requires cross-contract coordination to reference at least two contract boundaries through a component, policy, or handoff.
- Defines deterministic handling for zero, one, compatible multiple, and conflicting multiple runtime category matches.
- Adds direct relative-root regression coverage on the same drive.
- Adds a coordinated full-plan fixture covering dry-run, journaled apply, manifest validation, and a no-op second apply.
- Keeps generation plan schema 3, manifest schema 5, and transaction schema 2.

Harness for Codex v5.1 plans remain structurally compatible, but the stricter portable namespace, decision ownership, coordination witness, and handoff checks may reject previously accepted ambiguous plans. Regenerate and review those plans before applying them with v5.2.

Runtime enforcement, automatic adaptation, Hooks, and an SDK controller remain outside the v5 generation contract.

## Harness for Codex v5.3

Harness for Codex v5.3 adds an optional evaluation layer without changing the v5.2 generation, ownership, or transaction contracts.

- Records evaluator-started `codex exec --json` metadata without retaining raw JSONL, prompts, transcripts, commands, paths, or source content.
- Distinguishes measured zero, unavailable values, reported values, and partial metric coverage.
- Records parser compatibility, Codex version, model pseudonym, reasoning effort, sandbox, process cleanup, and result fingerprints.
- Stores per-run canonical JSON in a locked, atomic, user-local state tree outside the target repository.
- Keeps completed records immutable and stores user acceptance or corrections as separate annotations.
- Requires a plan-specified primary outcome, correctness gate, verification profile, and complete isolation before labelling paired evidence controlled.
- Creates only non-binding proposals with `causalClaimAllowed: false` and `autoApplicable: false`.
- Keeps evaluation disabled unless `harness_eval.py` is invoked explicitly.
- Keeps generation plan schema 3, manifest schema 5, and transaction schema 2.

Harness for Codex v5.2 installations require no migration. Regenerating with v5.3 changes only the generator version when the same reviewed plan is applied; project artifacts and the managed instruction remain equivalent.

## Harness for Codex v5.4

Harness for Codex v5.4 adds a backward-compatible change-discipline contract without changing the v5 plan, manifest, or transaction schemas.

- Adds a common code-change discipline to generated `project-harness` skills: surface material ambiguity and simpler alternatives, make the smallest scoped change, avoid unrelated cleanup, and define verification before implementation.
- Requires every generated writer's `developer_instructions` to carry a concise self-contained form of the same contract because delegated agents are not guaranteed to load `project-harness`.
- Adds four synthetic evaluation cases covering ambiguous requirements, one-line direct edits, file-scoped bug fixes, and verification-first handling of reproducible bugs.
- Scores both the selected action and required or forbidden behavior tags.
- Adds `--validate-only` fixture validation that does not invoke Codex and keeps live behavioral probing explicitly opt-in.
- Keeps generation plan schema 3, manifest schema 5, transaction schema 2, and evaluation auxiliary schema 1.

Harness for Codex v5.3 installations require no state migration. A reviewed regeneration may update generated `project-harness` and writer instructions; ownership conflicts continue to stop the full apply before changes are written.

## Harness for Codex v5.5

Harness for Codex v5.5 hardens generation and evaluation semantics without changing any generation or evaluation schema number.

- Requires the canonical project change-discipline block exactly once after line-ending normalization.
- Requires the canonical self-contained discipline block exactly once in every agent whose topology grants write access.
- Fingerprints the complete `git diff HEAD --binary --no-ext-diff` result together with every non-ignored untracked regular file or symlink, including raw Git path bytes and artifact kind.
- Returns no partial result digest when file or byte bounds are exceeded, an artifact cannot be represented, or the repository changes during capture.
- Gives every paired arm an isolated temporary user home without copying authentication or modifying the caller's home.
- Treats known Harness skills in isolated user, compatibility, Codex-home, or readable POSIX admin locations as isolation gaps; a contaminated dedicated `CODEX_HOME` remains a hard preflight error.
- Downgrades Windows live isolation when no matching user-local process-cleanup receipt is supplied.
- Distinguishes an omitted correction count from measured zero and requires at least one measured correction for `accepted-with-corrections`.
- Emits only experiment suggestions for positive Schema 1 evidence and only bundle-level negative signals for harmful evidence; it does not invent a delegated or reviewer configuration.
- Keeps generation plan schema 3, manifest schema 5, transaction schema 2, and all evaluation auxiliary schemas at version 1.

Harness for Codex v5.4 installations require no stored-state migration. Regeneration is required before applying a new plan whose generated discipline text does not satisfy the canonical validator.

## Harness for Codex v6.0

Harness for Codex v6.0 changes the optional evaluation state contract while leaving generation, ownership, and transaction schemas unchanged.

- Introduces Run, Annotation, Comparison Plan, Comparison, and Proposal Schema 2.
- Separates declared configuration, expected execution, discovered configuration, and observed execution.
- Uses state-bearing reference sets so measured empty, unavailable, and not-applicable are not conflated.
- Computes configuration deltas from declared arm snapshots and distinguishes single-factor, bundle, and no-delta attribution.
- Represents an asymmetric unknown configuration as an unavailable delta rather than inventing a change.
- Requires a plan-declared intervention and task stratum; protocol mismatch prevents configuration proposals.
- Records result-fingerprint completeness separately from environment isolation.
- Adds optional patch-scope profiles with pseudonymous changed-path evidence and counts both sides of renames and copies.
- Adds structured user and agent report ingest validated against the immutable Run snapshot rather than the current manifest.
- Introduces create-only Observation Schema 1 with supplement, replacement, and terminal withdrawal lifecycles.
- Introduces Annotation Schema 2 with one active user-outcome chain and explicit legacy ambiguity handling.
- Computes a non-persistent Derived Evaluation View using field-specific authority rules, active conflicts, protocol deviations, and provenance.
- Binds every comparison to the exact Derived Views used and excludes stale comparisons after an observation or annotation lifecycle change.
- Stratifies proposal evidence by task, outcome, actual delta, model, Codex runtime, reasoning effort, and verification profile.
- Retains Schema 1 readers for list, inspect, export, integrity checks, repair, and purge without automatic rewrite or inferred migration.
- Keeps every proposal non-causal and non-auto-applicable. A configuration or bundle proposal can contain only the observed delta supported by eligible Schema 2 comparisons.

Harness for Codex v5.5 evaluation files need no destructive migration. They remain legacy read-only evidence and are excluded from v6 attribution groups. Runtime Hooks, phase enforcement, write-lane control, and automatic adaptation remain outside v6 and are reserved for a later major release.

## Harness for Codex v6.1

Harness for Codex v6.1 corrects attribution eligibility and support statistics without changing any generation, ownership, transaction, or evaluation schema number.

- Requires the original validated Comparison Plan for concrete positive or negative configuration attribution; missing or descriptive-only plans produce only experiment suggestions or no-change records with an empty candidate.
- Binds proposal evidence to one canonical plan digest and includes the plan digest and Harness runtime version in evaluation-stratum calculation.
- Requires a bundle target to predeclare at least two changed factors.
- Rejects mismatched patch-scope profile fingerprints before comparison.
- Preserves partial or violated patch-scope comparisons as descriptive evidence while blocking all concrete factor, bundle, and negative attribution.
- Records baseline scope violations as an explicit confounder and defensively rechecks both arms before proposal creation.
- Treats exact zero as a tie even when the minimum effect is zero.
- Uses the raw treatment-minus-baseline median in records while using an internal direction-adjusted median for support decisions.
- Applies weak, moderate, and strong ratios symmetrically by integer cross multiplication; weak means exactly at least two of three, and at least three non-ties are required.
- Reads v6.0 Schema 2 records descriptively while limiting new concrete attribution to v6.1 run evidence.
- Derives independent-review configuration only from the topology contract's producer-reviewer collaboration pattern or independent-safety-review quality policy.

Harness for Codex v6.0 records remain immutable and readable. They are not rewritten or silently promoted into v6.1 attribution evidence.

## Harness for Codex v6.2

Harness for Codex v6.2 corrects the independence, comparability, and task-baseline rules used by Evaluation Schema 2 without changing generation plan schema 3, manifest schema 5, transaction schema 2, or any persisted evaluation schema number.

- Counts only complete comparisons made from independent Run pairs in Proposal evidence statistics.
- Excludes partial comparability from positive and negative concrete attribution while preserving each Comparison for descriptive inspection.
- Preserves task failures as harmful evidence when comparability is complete and the planned outcome remains measurable.
- Rejects duplicate Comparison IDs, repeated Run pairs, reused Run IDs within an attribution group, and duplicate stored comparisons for the same Run pair and plan digest.
- Centralizes store-aware Proposal eligibility; direct statistics helpers cannot emit a concrete candidate without a verified eligibility result.
- Creates clean synthetic pre-task commits for both paired arms, records the original user commit as their shared `sourceSnapshotId`, and evaluates result fingerprints and patch scope from the arm-specific task base.
- Treats untracked files as partial patch-scope evidence whenever an added- or deleted-line budget is active.
- Checks Codex version, platform, and capture-mode comparability inside each pair and adds platform, sandbox, and capture mode to the evaluation stratum.
- Describes configuration differences as declared or preassigned snapshot deltas rather than proof of runtime component use.
- Distinguishes standalone plan binding, paired-run plans supplied before arm execution, and unsupported durable preregistration.

Harness for Codex v6.0 and v6.1 records remain immutable and readable for descriptive inspection. They are not rewritten or silently promoted into v6.2 concrete attribution evidence.

## Harness for Codex v6.3

Harness for Codex v6.3 completes the Observation and Annotation comparison lifecycle and separates Codex task measurement from verification side effects without changing generation plan schema 3, manifest schema 5, transaction schema 2, or any persisted evaluation schema number.

- Includes both Derived View fingerprints in the Schema 2 Comparison duplicate identity, allowing the same Run pair and Plan to be compared again after a lifecycle change while still rejecting exact duplicates.
- Keeps stale immutable Comparisons for inspection and excludes them before Run-independence accounting, so only the fresh Comparison can contribute evidence.
- Measures the task result fingerprint and patch scope immediately after Codex exits.
- Runs verification afterward and marks Git-visible verification mutations as partial comparability with `verification-worktree-mutated`; an unavailable post-verification measurement is also ineligible.
- Requires `--evaluation-stratum` when more than one concrete-eligible stratum remains instead of selecting a group automatically.
- Binds auxiliary filenames and storage scope to their internal record and repository IDs, and makes repair detect misplaced Comparison and Proposal records.
- Extends the final Linux and Windows CI clean-tree check to include non-ignored untracked files.

Harness for Codex v6.0 through v6.2 records remain immutable and readable for descriptive inspection. They are not rewritten or silently promoted into v6.3 concrete attribution evidence.

## Harness for Claude Code releases

Harness for Claude Code editions are maintained independently on `claude/*` branches. Their version numbers identify Harness releases for that runtime, not Claude Code product versions. Release details remain on those branches so this document does not duplicate mutable Claude-specific state.
