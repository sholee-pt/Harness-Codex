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

<!-- harness:runtime-teamplay:v2:begin -->
## Runtime execution classification

- Classify the current task as `direct`, `delegated`, or `coordinated`; do not infer runtime coordination from the persistent topology or agent count alone.
- Use `coordinated` only when repeated feedback, conflicting expert judgment, cross-boundary agreement, dynamic reassignment, or reviewer-chain negotiation has material value.

## Teamplay selection criteria

- Prefer direct execution for a small, tightly coupled change.
- Use delegated fan-out/fan-in for independent work, a pipeline for sequential work, and delegated producer-reviewer for one review pass.
- Keep current participants, runtime roles, tasks, messages, and retention out of the persistent manifest.

## Runtime roles

Assign producer, reviewer, skeptic, integrator, supervisor, or scout only for the current task. A runtime role does not create or rename a persistent agent.

`participants` in the ephemeral runtime plan are the persistent agents activated for the current task. Do not create or persist a second active-agent list.

## Native subagent relay

For `delegated` or `coordinated` execution:

1. Ask the current Codex session to spawn only the selected project custom agents as subagents. Use the first real selected task agent as the capability probe; do not create a disposable probe.
2. Treat spawn as acknowledged after the runtime returns a non-empty canonical receiver handle and the current agent list confirms that handle. Use that handle for wait, follow-up, and interrupt. Do not require a raw child thread ID in the model-visible response; child ID, role, and parent belong to optional session-binding evidence.
3. Give every acknowledged subagent one bounded task, input scope, output contract, write boundary, and verification requirement. Bound waits to at most three attempts and 300000 total milliseconds per agent.
4. Wait for every required acknowledged subagent result before integration. Record `selected`, `receiverHandleAcknowledged`, `sessionBound`, `observed`, `completed`, `failed`, and `fallback` separately.
5. Require each subagent to return one structured coordination packet to the parent agent. Do not assume direct peer messaging.
6. Relay only material findings, evidence-backed challenges, and bounded requests to named affected agents. Bind every review to the exact input packet hash in a separate relay receipt.
7. For coordinated execution, use no more than two targeted revision rounds and rerun only the affected agents. Reject stale reviews after a packet hash changes.
8. Keep ownership and write scopes fixed during relay; a returned packet cannot expand either.
9. Let the primary agent or designated integrator decide, integrate, run project-native verification, and account for every required task.

If acknowledgement or the bounded wait fails, use the declared sequential relay or direct fallback and disclose it. Missing optional public or local evidence lowers evidence strength but does not stop a valid canonical-handle execution. Fail closed only on an actual terminal-outcome or role/parent/session-binding contradiction. Do not automatically change between ephemeral and persistent execution because the retention policy would change; a new persistent run requires explicit user consent.

## Task graph and ownership

Give every task one owner, dependencies, required outputs, and verification. Missing required artifacts or verification is a hard failure on a critical path.

## Communication contract

Subagents return packets to the parent agent containing status, task ID, participant, summary, findings, challenges, artifacts, changed paths, verification, incomplete work, and unresolved risks. Findings name affected agents; challenges include evidence and a requested action. Bound rounds and packets; subagents cannot grant write scope or reassign tasks.

## Capability probe and fallback

Probe live runtime capabilities with the first selected task agent before further delegation. A spawn request alone is not success: require a non-empty canonical receiver handle, confirm that handle in the current agent list, and collect its terminal result through a bounded wait. Cross-check child ID, role, and parent only when compatible local session evidence is available; its absence cannot invalidate a working handle. Preserve input, output, and verification through sequential relay or direct execution when subagents are unavailable.

## Writer isolation

Default to multiple read-only subagents and one writer. Reviewers are read-only. Permit parallel writers only when the runtime proves separate worktrees or equivalent isolation and their write scopes do not overlap; ordered overlap requires a verified handoff for the complete shared scope. A declared isolation value alone is not execution proof.

## Phase freeze and handoff

Record a content hash before downstream validation. If a frozen input changes, invalidate dependent validation and repeat it against the new hash.

## Failure and stopping rules

Retry a transient failure at most once. Never wait on an empty or unlisted receiver handle. Stop delegation and use the declared fallback on a missing or unknown handle, a failed terminal wait, or an exhausted wait budget. Treat a verified role, parent, spawn-instance, or incompatible terminal-outcome contradiction as fail-closed; treat `not-exposed`, `unobserved`, `partial`, or unsupported observation profiles only as evidence limitations.

## Retention policy

Runtime plans and workspaces are ephemeral by default, store no raw messages or artifacts, and are removed after completion. Redacted or full-audit retention requires an explicit runtime choice; full audit requires explicit user opt-in.

## Completion report

Report selected, receiver-handle acknowledgement, session binding, observed lifecycle, completion sources, failure sources, fallback, task accounting, produced artifacts, relays, revision rounds, verification, and unresolved risks separately. A bounded control-plane wait may establish completion; compatible local session evidence raises its strength to cross-validated. Agent-reported text alone never establishes completion.
<!-- harness:runtime-teamplay:v2:end -->

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
