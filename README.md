<p align="center">
  <img src="https://img.shields.io/badge/Harness_for_Codex-v5.1-brightgreen.svg" alt="Harness for Codex v5.1">
  <img src="https://img.shields.io/badge/Runtime-Codex-111827.svg" alt="Codex Runtime">
  <img src="https://img.shields.io/badge/Type-Harness_Generator-orange.svg" alt="Harness Generator">
  <img src="https://img.shields.io/badge/License-Proprietary-blue.svg" alt="Proprietary License">
</p>

# Harness for Codex

> Generate the smallest evidence-backed Codex agent system that matches a project's persistent decision boundaries.

Harness is a user-level Codex skill. Run it inside a project and it analyzes the repository, selects only justified agent and skill boundaries, and writes a native project harness that can be reused in later sessions.

## What It Generates

```text
target-project/
├── .codex/agents/                 # Project-specific custom agents, when justified
├── .agents/skills/
│   ├── project-harness/           # Project orchestration skill
│   └── <project-skill>/           # Reusable project procedures, when justified
├── .harness/manifest.json         # Ownership, topology, and content hashes
├── .harness/transaction.json      # Present only while recovery or cleanup is required
└── AGENTS.md or AGENTS.override.md # Managed pointer in the active root instruction file
```

Simple projects may receive only `project-harness`. Harness does not create a fixed team or assume a frontend/backend architecture. It classifies persistent project topology independently from the execution complexity of any one task.

## Installation

Harness requires Anaconda or Miniconda. Clone this branch, create the dedicated `harness` environment, and copy the generator to the user skill directory.

### PowerShell

```powershell
git clone --branch codex/v5.1 --single-branch https://github.com/sholee-pt/Harness.git Harness
conda env create --file "Harness/environment.yml"
New-Item -ItemType Directory -Force "$HOME/.agents/skills" | Out-Null
New-Item -ItemType Directory -Force "$HOME/.agents/skills/harness" | Out-Null
Copy-Item -Recurse -Force "Harness/.agents/skills/harness/*" "$HOME/.agents/skills/harness"
```

### macOS and Linux

```shell
git clone --branch codex/v5.1 --single-branch https://github.com/sholee-pt/Harness.git Harness
conda env create --file Harness/environment.yml
mkdir -p ~/.agents/skills
mkdir -p ~/.agents/skills/harness
cp -R Harness/.agents/skills/harness/. ~/.agents/skills/harness/
```

Restart Codex if the user skill directory did not exist when the current session started.

If the `harness` environment already exists, replace `conda env create` with `conda env update --name harness --file Harness/environment.yml`.

## Usage

Open the target repository in Codex and run:

```text
$harness configure a project harness for this repository.
```

The skill also recognizes direct requests such as “configure the harness” and “하네스를 구성해줘”. Run the same command later to audit or update an existing generated harness.

Harness first creates a structured proposal and runs a no-write dry-run. It applies files only when all ownership and instruction-precedence checks pass. Changed outputs are staged with backups before a journaled apply, and the manifest is committed last. Start a new Codex task after generation to verify discovery of newly written project instructions and custom agents.

## Design Rules

- Repository evidence determines roles, skills, and orchestration. Every evidence claim is bound to an existing file hash and may identify an exact line range.
- Persistent material boundaries record stable decision-area IDs, project persistence, contracts, verification, failure impact, and separation benefits.
- Project topology is `minimal`, `modular`, or `coordinated`. Boundary count alone does not force coordination; recurring repository-level coordination does.
- Current tasks are routed independently as `direct`, `delegated`, or `coordinated`. One-off task risk is never persisted as project topology.
- Six collaboration patterns are available as design vocabulary, not mandatory templates.
- Quality patterns are separate policies with repository evidence, finite budgets, stopping conditions, and failure handling.
- Concurrent writers may not overlap. Ordered overlapping writers require a verified handoff between explicit execution lanes.
- Literal file scopes cannot authorize recursive directory scopes. Writer overlap is compared case-insensitively for portable Windows safety.
- A persistent task category belongs to at most one route. If no route matches, the current task is classified at runtime instead of defaulting blindly to direct execution.
- Runtime capability declarations require a probe and contract-preserving fallback when a special capability is needed.
- User-owned files and edits are never silently overwritten.
- Generated files are updated only when their recorded hash still matches.
- Outputs classified as unchanged are not rewritten.
- A failed multi-file apply is rolled back from verified backups before another plan may run. POSIX file permission modes are restored with content.
- Phase outputs are treated as frozen only when hashes were actually recorded.
- Authentication, permission, and quota failures are reported without pointless retries.
- Runtime and model settings are inherited unless repository evidence requires an override.

## Validation

The generator includes standard-library-only Python tools. Run them through the dedicated Conda environment:

```shell
conda run -n harness python .agents/skills/harness/scripts/inventory.py .
conda run -n harness python .agents/skills/harness/scripts/harness_state.py evidence --root . --path PATH_TO_EVIDENCE
conda run -n harness python .agents/skills/harness/scripts/harness_state.py status --root .
conda run -n harness python .agents/skills/harness/scripts/harness_apply.py --root . --plan PATH_TO_PLAN.json --dry-run
conda run -n harness python .agents/skills/harness/scripts/harness_apply.py --root . --inspect-transaction
conda run -n harness python .agents/skills/harness/scripts/harness_apply.py --root . --recover
conda run -n harness python .agents/skills/harness/scripts/harness_apply.py --root . --clean-orphaned-transaction
conda run -n harness python .agents/skills/harness/scripts/validate_harness.py .
conda run -n harness python .agents/skills/harness/scripts/evaluate_topology.py --plan PATH_TO_PLAN.json --golden PATH_TO_GOLDEN.json
conda run -n harness python -m unittest discover -s tests -v
```

`evaluate_topology.py` validates only the persistent topology contract and reports `evidenceValidated: false`. It does not replace the evidence, ownership, and no-write checks performed by `harness_apply.py --dry-run`.

Use `--recover` only when status or a failed apply reports a pending journal. Use `--inspect-transaction` before maintenance. `--clean-orphaned-transaction` is restricted to the reserved staging directory when no journal exists; it never replaces recovery for a valid journal. Recovery first verifies that interrupted outputs were not edited externally and refuses destructive cleanup when their hashes are unknown.

If Windows Conda raises `UnicodeEncodeError` while forwarding a child-process error, inspect transaction status before retrying and rerun the diagnostic with `conda run --no-capture-output -n harness python ...`. This keeps the required environment while exposing the original Harness result.

Harness for Codex v5.1 requires generation plan schema 3, manifest schema 5, and transaction schema 2. Clean schema 4 installations are upgraded through repository re-analysis and a reviewed schema 3 plan; boundaries are not inferred from legacy manifest fields. Clean schema 1-3 manifests can first be prepared as schema 4 only when every legacy evidence path still resolves.

## Versioning

- Harness for Codex releases use `codex/vN` or `codex/vN.M` branches. The number identifies the Harness release, not the Codex product version.
- Harness for Claude Code releases use runtime-specific `claude/vN` or `claude/vN.M` branches.
- Displayed Harness and generator versions use two components (`N.M`). Existing major branches such as `codex/v5` represent their `.0` release and remain unchanged.
- Breaking generator changes start a new branch version.

See [VERSIONS.md](VERSIONS.md) for compatibility, migration, and release differences.

Claude-native editions are maintained independently on the repository's `claude/*` branches.

## License

This repository is proprietary and intended for the copyright holder's private use. See [LICENSE](LICENSE).
