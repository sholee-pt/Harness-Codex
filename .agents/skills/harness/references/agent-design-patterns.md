# Agent Design Patterns for Codex

This file translates the six revfactory/harness team architecture patterns into Codex-native execution.

## Execution Modes

| Mode | Use When | Codex Mechanics |
| --- | --- | --- |
| Subagent-capable team | independent specialists can run in parallel | use built-in agents or project custom agents from `.codex/agents/`, keep durable outputs in `_workspace/`, synthesize in the main thread |
| File-handoff team | subagents are unavailable or durable audit trail matters more than parallelism | follow role sections sequentially, writing `_workspace/<phase>_<role>_<artifact>.md` |
| Hybrid | some phases are parallel and others need durable sequential review | use subagents for independent phases and file handoffs for integration/review |

Codex does not require generated harnesses to call `TeamCreate`, `SendMessage`, or `TaskCreate`. Preserve the same coordination behavior with explicit plans, custom agents where useful, reusable workflow skills, and `_workspace` artifacts.

## Six Patterns

### Pipeline

Sequential dependent work.

Use for:

- spec -> plan -> implementation -> review
- collect -> normalize -> analyze -> report
- package -> verify -> publish

Codex design:

- one orchestrator skill
- custom agents for independently delegated phases, or explicit role sections for sequential phases
- `_workspace` artifacts passed from phase to phase

### Fan-out/Fan-in

Parallel independent specialists before synthesis.

Use for:

- multi-angle research
- code review split by security, architecture, performance, and tests
- product audit split by UX, accessibility, copy, and implementation

Codex design:

- subagents with bounded prompts and non-overlapping ownership
- one synthesis step
- each specialist writes a separate `_workspace` finding file

### Expert Pool

Only one or two specialists are needed per request.

Use for:

- projects with distinct recurring work types
- provider versus UI versus release versus docs changes
- support workflows where request classification matters

Codex design:

- concise `AGENTS.md` routing
- custom agents with narrow descriptions, plus skills only for reusable domain procedures
- optional QA reviewer for risky changes

### Producer-Reviewer

One role creates, another reviews.

Use for:

- generated code or docs that need quality gates
- localization
- release packaging
- security-sensitive changes

Codex design:

- producer and reviewer custom agents when both should run independently
- workflow skills for reusable generation and verification procedures
- verification and stop-and-ask gates

### Supervisor

A coordinator routes dynamic work.

Use for:

- multi-branch feature cycles
- workflows where follow-up requests should reuse prior artifacts
- mixed task types that may trigger several specialists

Codex design:

- thin orchestrator skill
- custom agents or role sections for branches
- `_workspace` context check at the start

### Hierarchical Delegation

Broad tasks decompose into nested sub-workflows.

Use for:

- large migrations
- multi-module systems
- research-to-delivery pipelines

Codex design:

- top-level orchestrator
- phase orchestrators or specialist groups
- explicit dependencies and `_workspace` structure

## Specialist Split Criteria

Split a role when at least two are true:

- distinct expertise is needed
- work can happen independently
- the role needs different context or files
- the role will be reused often
- separate review reduces risk

Merge roles when:

- they always run together
- handoff overhead is higher than benefit
- one skill can express the workflow clearly

## Reuse Check

Before creating a new specialist:

1. list existing `.codex/agents/*.toml` and `.agents/skills/*/SKILL.md`
2. compare purpose, triggers, inputs, outputs, and verification
3. update an existing skill when the role is substantially the same
4. create a custom agent for a runnable role; create a skill only for reusable workflow or domain guidance
