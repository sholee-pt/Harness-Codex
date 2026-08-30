<p align="center">
  <img src="https://img.shields.io/badge/Version-v1-brightgreen.svg" alt="Version v1">
  <img src="https://img.shields.io/badge/Runtime-Codex-111827.svg" alt="Codex Runtime">
  <img src="https://img.shields.io/badge/Type-Harness_Generator-orange.svg" alt="Harness Generator">
  <img src="https://img.shields.io/badge/License-Proprietary-blue.svg" alt="Proprietary License">
</p>

# Harness for Codex

> Generate a small, project-specific agent system from evidence in the repository.

Harness is a user-level Codex skill. Run it inside a project and it analyzes the repository, selects only justified agent and skill boundaries, and writes a native project harness that can be reused in later sessions.

## What It Generates

```text
target-project/
├── .codex/agents/                 # Project-specific custom agents, when justified
├── .agents/skills/
│   ├── project-harness/           # Project orchestration skill
│   └── <project-skill>/           # Reusable project procedures, when justified
├── .harness/manifest.json         # Ownership, topology, and content hashes
└── AGENTS.md                      # A small managed pointer; existing content is preserved
```

Simple projects may receive only `project-harness`. Harness does not create a fixed team or assume a frontend/backend architecture.

## Installation

Clone this branch and copy the generator to the user skill directory.

### PowerShell

```powershell
git clone --branch codex/v1 --single-branch https://github.com/sholee-pt/Harness.git Harness
New-Item -ItemType Directory -Force "$HOME/.agents/skills" | Out-Null
Copy-Item -Recurse -Force "Harness/.agents/skills/harness" "$HOME/.agents/skills/harness"
```

### macOS and Linux

```shell
git clone --branch codex/v1 --single-branch https://github.com/sholee-pt/Harness.git Harness
mkdir -p ~/.agents/skills
cp -R Harness/.agents/skills/harness ~/.agents/skills/harness
```

Restart Codex if the user skill directory did not exist when the current session started.

## Usage

Open the target repository in Codex and run:

```text
$harness configure a project harness for this repository.
```

The skill also recognizes direct requests such as “configure the harness” and “하네스를 구성해줘”. Run the same command later to audit or update an existing generated harness.

## Design Rules

- Repository evidence determines roles, skills, and orchestration.
- Six collaboration patterns are available as design vocabulary, not mandatory templates.
- User-owned files and edits are never silently overwritten.
- Generated files are updated only when their recorded hash still matches.
- Phase outputs are frozen before downstream validation.
- Authentication, permission, and quota failures are reported without pointless retries.
- Runtime and model settings are inherited unless repository evidence requires an override.

## Validation

The generator includes standard-library-only tools:

```shell
python .agents/skills/harness/scripts/inventory.py .
python .agents/skills/harness/scripts/harness_state.py status --root . --runtime codex
python .agents/skills/harness/scripts/validate_harness.py . --runtime codex
python -m unittest discover -s tests -v
```

## Versioning

- Codex releases use `codex/vN` branches.
- Claude Code releases use `claude/vN` branches.
- Breaking generator changes start a new branch version.

The Claude-native edition is available on [`claude/v1`](https://github.com/sholee-pt/Harness/tree/claude/v1).

## License

This repository is proprietary and intended for the copyright holder's private use. See [LICENSE](LICENSE).
