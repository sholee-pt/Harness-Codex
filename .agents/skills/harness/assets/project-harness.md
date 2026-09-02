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

<!-- harness:runtime-teamplay:v1:begin -->
## Runtime execution classification

- Classify the current task as `direct`, `delegated`, or `coordinated`; do not infer runtime coordination from the persistent topology or agent count alone.
- Use `coordinated` only when repeated feedback, conflicting expert judgment, cross-boundary agreement, dynamic reassignment, or reviewer-chain negotiation has material value.

## Teamplay selection criteria

- Prefer direct execution for a small, tightly coupled change.
- Use delegated fan-out/fan-in for independent work, a pipeline for sequential work, and delegated producer-reviewer for one review pass.
- Keep current participants, runtime roles, tasks, messages, and retention out of the persistent manifest.

## Runtime roles

Assign producer, reviewer, skeptic, integrator, supervisor, or scout only for the current task. A runtime role does not create or rename a persistent agent.

## Task graph and ownership

Give every task one owner, dependencies, required outputs, and verification. Missing required artifacts or verification is a hard failure on a critical path.

## Communication contract

Share only material findings, challenges, requests, handoffs, blockers, decisions, and completion packets. Challenges require evidence and a requested action. Bound rounds and messages; peers cannot grant write scope or reassign tasks.

## Capability probe and fallback

Probe live runtime capabilities before native collaboration. If peer messaging or shared task state is unavailable, preserve input, output, and verification through leader relay, delegated fan-out, sequential handoff, or direct execution.

## Writer isolation

Use an isolated worktree or equivalent for every writer. Reviewers are read-only. Reject concurrent overlapping write scopes; ordered overlap requires a verified handoff for the complete shared scope.

## Phase freeze and handoff

Record a content hash before downstream validation. If a frozen input changes, invalidate dependent validation and repeat it against the new hash.

## Failure and stopping rules

Retry a transient failure at most once. Stop on scope violations, stale plans, missing required artifacts, unresolved critical challenges, or exhausted communication and reassignment budgets.

## Retention policy

Runtime plans and workspaces are ephemeral by default, store no raw messages or artifacts, and are removed after completion. Redacted or full-audit retention requires an explicit runtime choice; full audit requires explicit user opt-in.

## Completion report

Report produced artifacts, verification, incomplete or skipped work, unresolved risks, fallback use, and frozen-output references. Structural validation is not proof of native peer-to-peer execution.
<!-- harness:runtime-teamplay:v1:end -->

<!-- harness:change-discipline:v1:begin -->
## Change discipline

For code-changing work:

- Surface material assumptions, conflicting interpretations, and simpler alternatives before editing.
- Implement the smallest change that satisfies the stated objective. Do not add speculative abstractions, configuration, or unrelated features.
- Limit edits to the requested responsibility and scope. Do not refactor, reformat, or clean up adjacent code unless the current change requires it. Remove only artifacts made obsolete by the current change.
- Define verification before implementation. Report completion only after the checks pass, or report the failure and remaining uncertainty explicitly.
<!-- harness:change-discipline:v1:end -->

## Failure policy

- Retry only a clearly transient failure, at most once.
- Do not retry authentication, permission, quota, unsupported capability, or invalid-input failures without a state change.
- Inspect partial artifacts and label each output complete, partial, skipped, or failed.
- Never hide a missing output behind a plausible final summary.

## Completion report

Report completed work, validation evidence, partial or failed branches, frozen-input changes, and remaining risks.
