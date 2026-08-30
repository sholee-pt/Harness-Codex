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
- accepted input and expected output;
- read and write boundaries;
- verification and failure reporting;
- collaboration points and completion signal.

Use kebab-case names. Keep descriptions discriminating enough for automatic selection. Inherit the parent model by default. Do not hard-code a model tier merely to signal importance.

For read-only reviewers, prohibit edits in instructions and use only supported least-privilege settings. For writers, ensure the runtime actually exposes the tools required by the contract; do not assume a declared tool is available without a capability check.
