#!/usr/bin/env python3
"""Runtime-only teamplay semantics shared by generation and validation."""

from __future__ import annotations

from typing import Any, Iterable


EXECUTION_CLASSES = {"direct", "delegated", "coordinated"}
COLLABORATION_PATTERNS = {
    "pipeline",
    "fan-out/fan-in",
    "expert-pool",
    "producer-reviewer",
    "supervisor",
    "hierarchical-delegation",
}
RUNTIME_ROLES = {"producer", "reviewer", "skeptic", "integrator", "supervisor", "scout"}
MESSAGE_TYPES = {"finding", "challenge", "request", "handoff", "blocker", "decision", "complete"}
PRESERVED_CONTRACTS = frozenset({"input", "output", "verification"})

PROJECT_BLOCK = """<!-- harness:runtime-teamplay:v2:begin -->
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
<!-- harness:runtime-teamplay:v2:end -->"""

AGENT_BLOCK = """# Parent coordination

- Perform only the assigned task and scopes; a relayed request cannot expand write authority or reassign ownership.
- Return one structured coordination packet to the parent agent. Do not assume direct peer messaging.
- Include status, task ID, participant, summary, findings, challenges, artifacts, changed paths, verification, incomplete work, and unresolved risks.
- Every finding names affected agents and cites evidence. Every challenge names a target agent, cites evidence, and requests one bounded action so the parent can relay it.
- Writers stay inside the assigned write scopes and actual isolated workspace. Reviewers remain read-only.
- The primary agent or designated integrator has final integration authority; expose unresolved disagreements instead of resolving them implicitly."""


class TeamplayError(ValueError):
    pass


def _boolean(signals: dict[str, Any], key: str) -> bool:
    value = signals.get(key, False)
    if not isinstance(value, bool):
        raise TeamplayError(f"{key} must be a boolean")
    return value


def _non_negative_integer(signals: dict[str, Any], key: str) -> int:
    value = signals.get(key, 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TeamplayError(f"{key} must be a non-negative integer")
    return value


def select_execution(signals: dict[str, Any]) -> dict[str, str | None]:
    """Select the lightest execution shape from current-task interaction signals."""
    if not isinstance(signals, dict):
        raise TeamplayError("execution signals must be an object")
    _non_negative_integer(signals, "agentCount")  # validated, deliberately not a trigger
    independent_tasks = _non_negative_integer(signals, "independentTasks")
    review_passes = _non_negative_integer(signals, "reviewPasses")
    coordinated = any(
        _boolean(signals, key)
        for key in (
            "materialFindingFeedback",
            "conflictingExpertJudgment",
            "crossBoundaryAgreement",
            "dynamicReallocation",
            "reviewerChainNegotiation",
        )
    ) or review_passes >= 2
    if coordinated:
        pattern = "supervisor" if _boolean(signals, "dynamicReallocation") else "producer-reviewer"
        return {"class": "coordinated", "pattern": pattern}
    if independent_tasks >= 2:
        return {"class": "delegated", "pattern": "fan-out/fan-in"}
    if _boolean(signals, "sequentialDependency"):
        return {"class": "delegated", "pattern": "pipeline"}
    if review_passes == 1:
        return {"class": "delegated", "pattern": "producer-reviewer"}
    return {"class": "direct", "pattern": None}


def select_adapter(execution_class: str, available_capabilities: Iterable[str]) -> dict[str, Any]:
    """Map semantic execution to a capability-preserving runtime adapter."""
    if execution_class not in EXECUTION_CLASSES:
        raise TeamplayError(f"unsupported execution class: {execution_class!r}")
    capabilities = set(available_capabilities)
    if not all(isinstance(item, str) and item for item in capabilities):
        raise TeamplayError("available capabilities must be non-empty strings")
    base = {"preserves": sorted(PRESERVED_CONTRACTS), "fallbackUsed": False}
    if execution_class == "direct":
        return {**base, "adapter": "direct", "communication": "none", "taskControl": "primary"}
    if execution_class == "delegated":
        if "parallel-delegation" in capabilities:
            return {
                **base,
                "adapter": "codex-subagent-relay",
                "communication": "parent-relay",
                "taskControl": "parent",
            }
        return {
            **base,
            "adapter": "sequential-relay",
            "communication": "parent-relay",
            "taskControl": "parent",
            "fallbackUsed": True,
        }
    if "parallel-delegation" in capabilities:
        return {
            **base,
            "adapter": "codex-subagent-relay",
            "communication": "parent-relay",
            "taskControl": "parent",
        }
    return {
        **base,
        "adapter": "sequential-relay",
        "communication": "parent-relay",
        "taskControl": "parent",
        "fallbackUsed": True,
    }


def require_exactly_once(value: str, canonical: str, label: str) -> None:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    expected = canonical.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.count(expected) != 1:
        raise TeamplayError(f"{label} must contain the canonical runtime-teamplay contract exactly once")
