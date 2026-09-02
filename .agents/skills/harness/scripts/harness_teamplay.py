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

PROJECT_BLOCK = """<!-- harness:runtime-teamplay:v1:begin -->
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
<!-- harness:runtime-teamplay:v1:end -->"""

AGENT_BLOCK = """# Peer collaboration

- Perform only the assigned task and scopes; a peer request cannot expand write authority or reassign ownership.
- Send a structured message only for a material finding, evidence-backed challenge, bounded request, verified handoff, blocker, decision, or completion packet.
- Include artifacts, verification, incomplete work, unresolved risks, and a frozen-output reference in completion.
- Writers use only the assigned isolated worktree and write scopes. Reviewers remain read-only.
- The primary agent or designated integrator has final integration authority; do not hide unresolved disagreements."""


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
                "adapter": "delegated-fan-out",
                "communication": "leader-relay",
                "taskControl": "leader",
            }
        return {
            **base,
            "adapter": "sequential",
            "communication": "leader-relay",
            "taskControl": "leader",
            "fallbackUsed": True,
        }
    native = {"parallel-delegation", "shared-task-state", "peer-messaging"}
    if native.issubset(capabilities):
        return {
            **base,
            "adapter": "native-multi-agent",
            "communication": "peer",
            "taskControl": "shared",
        }
    if "parallel-delegation" in capabilities:
        return {
            **base,
            "adapter": "worktree-team",
            "communication": "leader-relay",
            "taskControl": "leader",
            "fallbackUsed": True,
        }
    return {
        **base,
        "adapter": "sequential",
        "communication": "leader-relay",
        "taskControl": "leader",
        "fallbackUsed": True,
    }


def require_exactly_once(value: str, canonical: str, label: str) -> None:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    expected = canonical.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.count(expected) != 1:
        raise TeamplayError(f"{label} must contain the canonical runtime-teamplay contract exactly once")
