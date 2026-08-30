---
name: project-harness
description: Coordinate __PROJECT_DOMAIN__ work across the repository's generated agents and skills. Use for __PROJECT_TRIGGERS__. Do not use for unrelated tasks or simple questions that need no project workflow.
---

# Project Harness

## Project contract

- Objective: __PROJECT_OBJECTIVE__
- Boundaries: __PROJECT_BOUNDARIES__
- Quality risks: __QUALITY_BOUNDARIES__

## Routing

__TASK_TO_AGENT_AND_SKILL_ROUTING__

Use direct execution when delegation has no material benefit. Use only agents and skills justified by the current task.

## Run protocol

1. State the objective, completion criteria, planned outputs, dependencies, and ownership.
2. Confirm that every required runtime capability is actually available. Fall back to supported direct or sequential execution when it is not.
3. Run independent scopes in parallel only when their write boundaries do not overlap.
4. Collect an explicit completion status for every planned output.
5. When dependent phases need immutable inputs and a deterministic hash mechanism is available, freeze completed phase artifacts before downstream review or validation. Do not claim a phase is frozen without recorded hashes.
6. If a recorded frozen artifact changes, invalidate dependent validation and repeat it.
7. Integrate results and run project-native checks.

## Failure policy

- Retry only a clearly transient failure, at most once.
- Do not retry authentication, permission, quota, unsupported capability, or invalid-input failures without a state change.
- Inspect partial artifacts and label each output complete, partial, skipped, or failed.
- Never hide a missing output behind a plausible final summary.

## Completion report

Report completed work, validation evidence, partial or failed branches, frozen-input changes, and remaining risks.
