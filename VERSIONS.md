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

Trigger-profile evaluation and optional live model comparisons remain future work. Evolution history, feedback approval, privacy, retention, and automated self-modification remain future Harness for Codex v6.0 scope.

## Harness for Claude Code releases

Harness for Claude Code editions are maintained independently on `claude/*` branches. Their version numbers identify Harness releases for that runtime, not Claude Code product versions. Release details remain on those branches so this document does not duplicate mutable Claude-specific state.
