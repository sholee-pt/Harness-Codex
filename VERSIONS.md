# Version History

Harness versions are maintained as runtime-specific branches. A major branch is created when the generation contract, state format, ownership model, or required workflow changes. A minor branch contains backward-compatible corrections and validation improvements.

## Codex Editions

| Branch | Generator | Manifest | Status | Recommended for |
| --- | --- | --- | --- | --- |
| `codex/v1` | `1.0.0` | Schema 1 | Maintenance | Existing installations that need the original direct-generation workflow |
| `codex/v2` | `2.0.0` | Schema 2 | Maintenance | Existing guarded-generation installations |
| `codex/v2.1` | `2.1.0` | Schema 2 | Maintenance | Existing no-op-safe v2 installations |
| `codex/v3` | `3.0.0` | Schema 3 | Maintenance | Existing recoverable multi-file installations |
| `codex/v3.1` | `3.1.0` | Schema 3 | Current | New installations with review-driven validation and recovery hardening |

## Codex v1

Codex v1 introduced the project-adaptive generator.

- Inspects repository evidence before choosing a topology.
- Generates native Codex artifacts under `.codex/agents/`, `.agents/skills/`, and `AGENTS.md`.
- Records generated paths in `.harness/manifest.json` using manifest schema 1.
- Supports role, skill, and orchestrator generation without assuming a frontend/backend split.
- Uses the original direct-generation and validation workflow.

Codex v1 remains available for compatibility. It receives documentation or critical maintenance corrections only; new workflow features belong on a later major branch.

## Codex v2

Codex v2 adds a guarded and reproducible generation lifecycle.

- Separates analysis from mutation through a structured JSON plan.
- Requires a no-write dry-run before applying a plan.
- Applies generated artifacts through the deterministic `harness_apply.py` entry point.
- Refuses the entire update before writing when ownership checks or managed hashes conflict.
- Writes managed files atomically and preserves user-owned content outside managed boundaries.
- Detects the active root instruction file, including `AGENTS.override.md` precedence.
- Migrates compatible schema 1 manifests to schema 2 while preserving clean managed hashes.
- Records topology rationale, artifact purpose, evidence, and the active instruction file.
- Validates agents and skills independently against Codex-native naming and structure rules.
- Adds an Anaconda `harness` environment definition, fixture-based dry-run coverage, and expanded regression tests.

## Migrating to Codex v3

1. Create or preserve a recovery branch for the target project.
2. Install Harness from `codex/v3`.
3. Run analysis and review the generated plan.
4. Run the fixture or project dry-run and inspect every proposed action.
5. Apply only when validation passes and no ownership conflict is reported.
6. Start a new Codex task so newly written instructions and custom agents are discovered.

Codex v3 can migrate clean schema 1 and schema 2 manifests directly to schema 3. User-modified managed files are not silently re-baselined or overwritten, and a pending transaction must be recovered before migration.

## Codex v2.1

Codex v2.1 is a backward-compatible correction release built on the v2 plan and manifest contracts.

- Skips writes for artifacts, root instructions, and manifests classified as unchanged.
- Validates the complete action map before the first write.
- Adds regression coverage proving unchanged applies perform no writes.
- Adds automated unit-test and fixture dry-run checks for this release branch.
- Declares the intentionally limited generated skill-frontmatter contract and removes the unused YAML dependency.
- Corrects release documentation without changing manifest schema 2.

Existing Codex v2 manifests remain compatible. The first v2.1 apply may update only the generator version recorded in the manifest; later unchanged applies perform no writes.

## Codex v3

Codex v3 replaces sequential multi-file mutation with a recoverable, journaled application lifecycle while retaining plan schema 1.

- Introduces manifest schema 3 with an explicit journaled-application contract.
- Revalidates managed hashes, complete-file hashes, and create-path absence immediately before staging.
- Requires normalized POSIX-relative managed paths and rejects traversal within otherwise allowed output prefixes.
- Stages every changed output and preserves verified backups before target mutation begins.
- Writes `.harness/transaction.json` before replacing targets and commits `.harness/manifest.json` last.
- Automatically rolls back updates and transaction-created files after an ordinary mid-apply failure.
- Supports explicit `--recover` after process interruption, including interruption before the applied-path marker is recorded.
- Refuses recovery when an interrupted target was externally edited, preserving both that edit and the recovery journal.
- Removes transaction staging and backup data only after commit or verified rollback completes.

The filesystem cannot atomically replace unrelated paths as one operation. Schema 3 therefore defines recoverability and conflict-preserving rollback rather than claiming full multi-file atomicity.

## Codex v3.1

Codex v3.1 is a backward-compatible hardening release based on review of the v3 implementation.

- Corrects stale v2 branch text in the repository instructions.
- Reports missing or non-normalized file-level evidence as warnings without rejecting schema 1 plans.
- Adds non-mutating transaction inspection and explicit cleanup for an orphaned reserved staging directory.
- Synchronizes parent directory entries after atomic replacement on supported POSIX filesystems.
- Documents a repeatable live Codex discovery and delegation smoke test.

Plan schema 1, manifest schema 3, and transaction schema 1 remain unchanged. Existing clean v3 manifests can be updated by applying a reviewed v3.1 plan.

## Claude Code Editions

Claude Code editions are maintained independently on `claude/*` branches. Their release status is documented on those branches so Codex release notes do not duplicate mutable Claude version state.
