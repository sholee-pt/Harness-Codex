<p align="center">
  <img src="https://img.shields.io/badge/Version-v1-brightgreen.svg" alt="Version v1">
  <img src="https://img.shields.io/badge/Runtime-Codex-111827.svg" alt="Codex Runtime">
  <img src="https://img.shields.io/badge/Mode-Adaptive_Orchestration-orange.svg" alt="Adaptive Orchestration">
  <img src="https://img.shields.io/badge/License-Proprietary-blue.svg" alt="Proprietary License">
</p>

# Harness for Codex

> A repository-native workflow for scoping complex work, selecting the right execution mode, coordinating implementation, and validating the result.

## Overview

Harness adds a structured operating layer to Codex without imposing a fixed roster of agents. It derives roles from the task, delegates only when independent work can run safely, and keeps final integration and verification under the primary agent.

The workflow is designed for complex implementation, multi-area code review, and tasks that benefit from a clear separation between execution and validation.

## Key Features

- **Scope control** — Defines the goal, completion criteria, writable surface, and constraints before execution.
- **Adaptive delegation** — Uses subagents only when the work can be split into independent, well-owned units.
- **Evidence-based integration** — Verifies delegated findings against the repository before adopting them.
- **Quality gates** — Applies consistent checks to implementation, review findings, and final reporting.
- **Safe boundaries** — Prevents unrequested commits, merges, deployments, and external changes.

## Workflow

```text
Phase 1: Scope the task
    ↓
Phase 2: Select single-agent or delegated execution
    ↓
Phase 3: Define outputs, ownership, and dependencies
    ↓
Phase 4: Execute and integrate
    ↓
Phase 5: Validate with tests, checks, or reproducible evidence
    ↓
Phase 6: Report outcomes, gaps, and remaining risk
```

## Installation

Clone the Codex branch:

```shell
git clone --branch codex/v1 --single-branch https://github.com/sholee-pt/Harness.git harness-codex
```

Copy the following into the root of the target repository:

```text
AGENTS.md
.agents/skills/harness/
```

If the target repository already has an `AGENTS.md`, merge the relevant rules instead of replacing the file.

## Project Structure

```text
.
├── .agents/
│   └── skills/
│       └── harness/
│           ├── SKILL.md
│           └── references/
│               ├── orchestration.md
│               └── quality-gates.md
├── AGENTS.md
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

## Usage

Invoke the skill with a concrete objective:

```text
$harness implement the authentication module and validate the related tests.
```

For review-oriented work:

```text
$harness review this pull request for correctness, security boundaries, and missing tests.
```

### Execution Modes

| Mode | Behavior | Best suited for |
| --- | --- | --- |
| **Single-agent** | The primary agent investigates, implements, and validates sequentially. | Focused changes with tightly coupled steps |
| **Delegated** | Independent work is assigned with explicit ownership and integrated by the primary agent. | Multi-module work and multi-perspective reviews |

## Use Cases

- Cross-module feature implementation
- Architecture, security, and test-gap reviews
- Refactoring with independent verification
- Research that requires source validation before implementation
- Repository-wide changes with clearly separated ownership

## Versioning

- Codex releases use `codex/vN` branches.
- Claude Code releases use `claude/vN` branches.
- Each new version starts from the previous version of the same runtime.

See the [Claude Code branch](https://github.com/sholee-pt/Harness/tree/claude/v1) for the Claude-native layout.

## License

The original content in this repository is proprietary. See [LICENSE](LICENSE) for the applicable terms.
