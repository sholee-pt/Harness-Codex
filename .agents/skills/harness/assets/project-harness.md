---
name: project-harness
description: Coordinate __PROJECT_DOMAIN__ work across the workspace's generated agents and skills. Use for __PROJECT_TRIGGERS__. Do not use for unrelated tasks or simple questions that need no project workflow.
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

## Persistent evolution

- Treat a change in the current topic, task phase, or requested emphasis as runtime routing input first. It does not by itself deprecate an existing agent or justify a persistent topology change.
- When a task repeatedly falls outside the current routes, report a Harness reassessment candidate instead of silently creating or rewriting persistent agents.
- Recommend rerunning `$harness` only when stable workspace evidence shows a new or changed responsibility, contract boundary, recurring workflow, or verification risk.
- Preserve clean managed artifacts during reassessment. Report obsolete artifacts as removal candidates and never remove them without explicit user authorization.

## Direct execution

After resolving routing and required quality checks, handle a small, tightly coupled task directly when delegation adds no material benefit. Keep its scope, expected output, and verification in the current task; do not create a runtime-plan file, coordination packet, relay receipt, or disposable capability probe just to perform direct work. Preserve an explicitly requested plan or audit and all applicable verification and permission requirements.

Read delegation references and validate an ephemeral runtime plan only when delegation or coordination is selected. If new evidence requires that transition, validate the plan before spawning agents. Do not reuse an earlier validation as proof of current permissions, file ownership, evidence freshness, or write scope. Report the changed result, checks, and remaining gaps without empty subagent-accounting fields.

<!-- harness:runtime-teamplay:v3:begin -->
## Runtime execution

Select direct work, independent delegation, or coordinated feedback from the current task's needs, never agent count or persistent topology. One review pass is delegated; repeated negotiation may justify coordination. Keep task roles and state out of the manifest.

## Native subagent relay

For delegated or coordinated work, first read `.agents/skills/harness/references/runtime-plan.md` and `.agents/skills/harness/references/native-subagent-relay.md`. Validate the ephemeral plan, assign one owner and bounded scope per task, and preserve required outputs and verification through fallback. Reviewers are read-only; default to one writer. Parallel writers require observed isolation and disjoint scopes; ordered overlapping writers require a verified handoff.

Use the first real selected participant to confirm spawn acknowledgement and its listed receiver handle. That confirms readiness for further independent delegation; collect terminal results at integration, without serializing the first task. Follow the reference's bounded progress/deadline policy. A polling timeout is not task failure and never releases a live writer's ownership.

The parent relays material findings, validates returned packets, integrates required results and verifies current inputs. Load the relay-receipt reference for packet revisions; invalidate stale dependent reviews and bound targeted revision rounds. Runtime state is ephemeral by default; persistent audit retention requires an explicit choice. Read the runtime-observation reference only for requested live evidence capture. Report actual completion, failed or missing work, fallback and verification separately; missing optional observation is an evidence limitation.
<!-- harness:runtime-teamplay:v3:end -->

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
