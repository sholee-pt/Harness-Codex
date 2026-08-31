---
name: project-harness
description: Coordinate __PROJECT_DOMAIN__ work across the repository's generated agents and skills. Use for __PROJECT_TRIGGERS__. Do not use for unrelated tasks or simple questions that need no project workflow.
---

# Project Harness

## Project contract

- Objective: __PROJECT_OBJECTIVE__
- Persistent topology: __MINIMAL_MODULAR_OR_COORDINATED__
- Boundaries: __PROJECT_BOUNDARIES__
- Quality risks: __QUALITY_BOUNDARIES__

## Routing

__TASK_TO_AGENT_AND_SKILL_ROUTING__

Classify each current task as direct, delegated, or coordinated without changing the persistent project topology. If multiple task categories match, use a persistent route only when every match resolves to the same route; otherwise report the ambiguity and require an explicit runtime selection. Never merge conflicting routes or select the first route by ordering. Use direct execution when delegation has no material benefit. Use only agents and skills justified by the active boundaries and task risks.

## Run protocol

1. State the objective, completion criteria, planned outputs, dependencies, and ownership.
2. Resolve the applicable routing, quality, and capability policies. Confirm that every required runtime capability is actually available and use the declared contract-preserving fallback when it is not.
3. Run independent scopes in parallel only when their write scopes do not overlap in the same execution lane. Require the planned verified handoff before an ordered writer changes a shared scope.
4. Collect an explicit completion status for every planned output.
5. When dependent phases need immutable inputs and a deterministic hash mechanism is available, freeze completed phase artifacts before downstream review or validation. Do not claim a phase is frozen without recorded hashes.
6. If a recorded frozen artifact changes, invalidate dependent validation and repeat it.
7. Stop every quality loop at its declared budget or stopping condition, preserve unresolved disagreement under its failure policy, then integrate results and run project-native checks.

## Failure policy

- Retry only a clearly transient failure, at most once.
- Do not retry authentication, permission, quota, unsupported capability, or invalid-input failures without a state change.
- Inspect partial artifacts and label each output complete, partial, skipped, or failed.
- Never hide a missing output behind a plausible final summary.

## Completion report

Report completed work, validation evidence, partial or failed branches, frozen-input changes, and remaining risks.
