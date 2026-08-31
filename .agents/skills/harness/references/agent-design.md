# Agent Design

Read this reference after the project profile is complete.

## Separation test

Create a custom agent only when at least one benefit is material and its boundary can be stated precisely:

- specialized judgment that changes the result;
- work that can proceed independently or in parallel;
- context that should be isolated from the primary task;
- a reusable role that will recur in this repository;
- an explicit producer/reviewer or contract-verification boundary.

Do not create agents to mirror every directory, framework, or job title. Merge roles whose inputs, decisions, or outputs substantially overlap.

## Pattern catalog

Patterns are design vocabulary, not templates that must be instantiated.

| Pattern | Use when | Primary risk |
| --- | --- | --- |
| Pipeline | Each result is a required input to the next stage | Rework if an early result changes |
| Fan-out/fan-in | Independent scopes can be analyzed concurrently and compared | Duplicate or inconsistent outputs |
| Expert pool | Different tasks need different specialists on demand | Unnecessary idle roles |
| Producer-reviewer | A high-risk artifact benefits from independent challenge | Reviewer restates instead of tests |
| Supervisor | Work allocation must adapt as results arrive | Coordination overhead and bottleneck |
| Hierarchical delegation | A large domain has independently decomposable subdomains | Context loss; keep depth at two levels or less |

Prefer direct primary-agent execution when coordination costs exceed the expected quality or latency benefit.

## Definition contract

Every generated agent must state:

- unique responsibility and explicit exclusions;
- evidence that justified the role;
- one material-boundary reference for a specialist or at least two for a cross-boundary role;
- accepted input and expected output;
- read and write scopes using literal paths or directory prefixes ending in `/**`;
- execution phase and concurrency group for each file-access scope;
- verification and failure reporting;
- collaboration points and completion signal.

Do not generate one agent per material boundary automatically. A boundary is a persistent project fact; an agent is justified only when delegation materially improves judgment, independence, context isolation, reuse, or review quality. The project-level `project-harness` is a skill rather than a specialist agent and does not reference a single boundary.

Two agents may not write overlapping scopes in the same execution lane. Sequential overlapping writers require an ordered, verified handoff whose scope equals their complete shared scope. Read-only review may overlap a producer's write scope in a later lane.

Use snake_case agent names and matching filenames as the Harness-managed convention. Keep descriptions discriminating enough for automatic selection. Inherit the parent model by default. Do not hard-code a model tier merely to signal importance.

For read-only reviewers, prohibit edits in instructions and use only supported least-privilege settings. For writers, ensure the runtime actually exposes the tools required by the contract; do not assume a declared tool is available without a capability check.

Every writer's `developer_instructions` must carry a concise, self-contained change-discipline rule. It must require the writer to surface material ambiguity and simpler alternatives before editing, make the smallest scoped change without speculative additions or adjacent cleanup, define verification before implementation, and report completion only after checks pass. Do not rely on the writer implicitly inheriting or loading `project-harness`.
