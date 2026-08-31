# Harness Version History

Harness releases are maintained as runtime-specific branches. Names such as `codex/v5` mean **Harness for Codex v5**; they do not identify the Codex product or model version. A major Harness version changes a generation contract, state format, ownership model, or required workflow. A minor Harness version contains backward-compatible corrections and validation improvements.

## Harness for Codex releases

| Branch | Harness release | Plan | Manifest | Transaction | Main change or patch |
| --- | --- | --- | --- | --- | --- |
| `codex/v1` | Harness for Codex v1.0.0 | Direct generation | Schema 1 | None | Project-adaptive agents and skills, native Codex paths, initial ownership manifest |
| `codex/v2` | Harness for Codex v2.0.0 | Schema 1 | Schema 2 | None | JSON proposal, no-write dry-run, guarded deterministic apply, instruction precedence |
| `codex/v2.1` | Harness for Codex v2.1.0 | Schema 1 | Schema 2 | None | True no-op updates, complete action-map checks, CI and fixture dry-run corrections |
| `codex/v3` | Harness for Codex v3.0.0 | Schema 1 | Schema 3 | Schema 1 | Journaled multi-file apply, verified staging, rollback, recovery, manifest-last commit |
| `codex/v3.1` | Harness for Codex v3.1.0 | Schema 1 | Schema 3 | Schema 1 | Recovery hardening, orphan inspection and cleanup, directory sync, live smoke-test guide |
| `codex/v4` | Harness for Codex v4.0.0 | Schema 2 | Schema 4 | Schema 2 | SHA-256-bound structured evidence, line ranges, POSIX permission tracking and recovery |
| `codex/v5` | Harness for Codex v5.0.0 | Schema 3 | Schema 5 | Schema 2 | Machine-verifiable material boundaries, persistent topology classes, routing and quality contracts, deterministic golden evaluation |

All earlier branches remain preserved for existing installations. New changes are added on a later Harness branch rather than rewriting a published version branch.

## Harness for Codex v1

Harness for Codex v1 introduced the project-adaptive generator.

- Inspects repository evidence before choosing a topology.
- Generates native Codex artifacts under `.codex/agents/`, `.agents/skills/`, and `AGENTS.md`.
- Records generated paths in `.harness/manifest.json` using manifest schema 1.
- Supports role, skill, and orchestrator generation without assuming a frontend/backend split.
- Uses the original direct-generation and validation workflow.

This branch receives documentation or critical maintenance corrections only.

## Harness for Codex v2

Harness for Codex v2 added a guarded and reproducible generation lifecycle.

- Separates analysis from mutation through generation plan schema 1.
- Requires a no-write dry-run before applying a plan.
- Applies artifacts through deterministic `harness_apply.py` validation.
- Refuses the complete update before writing when ownership checks or managed hashes conflict.
- Preserves user-owned content and detects `AGENTS.override.md` precedence.
- Introduces manifest schema 2 with topology rationale, artifact purpose, and the active instruction path.
- Adds the dedicated Anaconda `harness` environment and fixture-based validation.

## Harness for Codex v2.1

Harness for Codex v2.1 patched the v2 lifecycle without changing its plan or manifest schemas.

- Skips writes for artifacts, root instructions, and manifests classified as unchanged.
- Validates the complete action map before the first write.
- Adds regression coverage proving unchanged applies perform no writes.
- Adds automated unit-test and fixture dry-run checks.
- Declares the limited generated skill-frontmatter contract and removes an unused YAML dependency.

Existing clean Harness for Codex v2 manifests remain compatible.

## Harness for Codex v3

Harness for Codex v3 replaced sequential multi-file mutation with a recoverable journaled lifecycle.

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

Harness for Codex v3.1 hardened v3 without changing the generation or state schemas.

- Corrects stale release text in repository instructions.
- Reports incomplete legacy evidence without silently fabricating semantic claims.
- Adds non-mutating transaction inspection and explicit orphaned-workspace cleanup.
- Synchronizes parent directory entries after atomic replacement on supported POSIX filesystems.
- Documents a repeatable live Codex discovery and delegation smoke test.

## Harness for Codex v4

Harness for Codex v4 made evidence and portable permission behavior deterministic contracts.

- Introduces generation plan schema 2 with `path`, `sha256`, `claim`, and optional line ranges.
- Rejects missing, escaped, stale, or out-of-range evidence before planning mutations.
- Introduces manifest schema 4 for auditable evidence hashes and generated-file modes.
- Introduces transaction schema 2 with original and desired permission modes.
- Applies and restores POSIX permissions with content; Windows retains platform-native behavior.
- Adds a read-only evidence helper for normalized paths and SHA-256 values.
- Prepares clean schema 1-3 manifests as schema 4 when all legacy evidence paths still resolve.

Evidence hashes prove which unchanged bytes a claim references; semantic truth remains a review responsibility.

## Harness for Codex v5

Harness for Codex v5 promotes v4 topology guidance into a machine-verifiable contract while retaining transaction schema 2.

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

Harness for Codex v4 → v5 is a reviewed regeneration upgrade. Harness validates the clean v4 ownership state, re-analyzes the repository, dry-runs a schema 3 plan, and writes schema 5 only through the existing journaled apply. It does not infer material boundaries from legacy manifest fields.

Trigger-profile evaluation and optional live model comparisons remain future Harness for Codex v5.1 scope. Evolution history, feedback approval, privacy, retention, and automated self-modification remain future Harness for Codex v6 scope; no corresponding branches are created by the v5 release.

## Harness for Claude Code releases

Harness for Claude Code editions are maintained independently on `claude/*` branches. Their version numbers identify Harness releases for that runtime, not Claude Code product versions. Release details remain on those branches so this document does not duplicate mutable Claude-specific state.
