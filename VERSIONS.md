# Version History

Harness versions are maintained as runtime-specific branches. A major branch is created when the generation contract, state format, ownership model, or required workflow changes.

## Codex Editions

| Branch | Generator | Manifest | Status | Recommended for |
| --- | --- | --- | --- | --- |
| `codex/v1` | `1.0.0` | Schema 1 | Maintenance | Existing installations that need the original direct-generation workflow |
| `codex/v2` | `2.0.0` | Schema 2 | Current | New installations and guarded updates to existing project harnesses |

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

## Migrating from Codex v1

1. Create or preserve a recovery branch for the target project.
2. Install Harness from `codex/v2`.
3. Run analysis and review the generated plan.
4. Run the fixture or project dry-run and inspect every proposed action.
5. Apply only when validation passes and no ownership conflict is reported.
6. Start a new Codex task so newly written instructions and custom agents are discovered.

Codex v2 can read and migrate a clean v1 manifest. User-modified managed files are not silently re-baselined or overwritten.

## Claude Code Editions

Claude Code versions are maintained independently under `claude/vN`. `claude/v1` remains the current Claude-native edition; a `claude/v2` branch has not been released.
