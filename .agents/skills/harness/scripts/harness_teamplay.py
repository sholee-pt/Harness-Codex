#!/usr/bin/env python3
"""Runtime-only teamplay semantics shared by generation and validation."""

from __future__ import annotations

from typing import Any, Iterable


EXECUTION_CLASSES = {"direct", "delegated", "coordinated"}
MAX_REVISION_ROUNDS = 2
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
CANONICAL_CAPABILITIES = frozenset(
    {"parallel-delegation", "peer-messaging", "shared-task-state"}
)
CAPABILITY_ALIASES = {"parallel-subagent-delegation": "parallel-delegation"}

DIRECT_EXECUTION_GUIDANCE = """## Direct execution

After resolving routing and required quality checks, handle a small, tightly coupled task directly when delegation adds no material benefit. Keep its scope, expected output, and verification in the current task; do not create a runtime-plan file, coordination packet, relay receipt, or disposable capability probe just to perform direct work. Preserve an explicitly requested plan or audit and all applicable verification and permission requirements.

Read delegation references and validate an ephemeral runtime plan only when delegation or coordination is selected. If new evidence requires that transition, validate the plan before spawning agents. Do not reuse an earlier validation as proof of current permissions, file ownership, evidence freshness, or write scope. Report the changed result, checks, and remaining gaps without empty subagent-accounting fields."""

CHECKPOINT_GUIDANCE = """For explicitly requested resumable multi-stage work, read `.agents/skills/harness/references/task-checkpoints.md`. Use bounded, opt-in checkpoints only when reuse has material value. Keep small direct tasks free of checkpoint state; project growth alone does not require another agent."""

WORKFLOW_GUIDANCE = """## Workflow activation and progress

A workflow name in a question, quotation, log or example is not an instruction to activate it. Follow the actual request and keep an already authorized task in progress; do not introduce planning, checkpointing or an autonomous loop from keywords alone.

Reassignment may use only ready, unowned tasks and observed available workers. Stop-requested is not stopped: confirm the prior worker is quiescent and invalidate stale handoffs before transferring ownership. This also applies to a same-scope writing fallback after a wait budget expires; a timeout or task-accounting receipt does not release the writer. Read-only fallback may continue without acquiring write ownership. Receiving a result is not integration; verify the combined result against current inputs.

Choose checks for the changed behavior. For stateful changes, consider interruption/resume, stale state, concurrent ownership and timeout paths. Keep existing retry budgets; if the same failure recurs without a new hypothesis or changed evidence, report the blocker instead of repeating the loop or weakening the check."""

PROCEDURE_GUIDANCE = """When a change crosses producer/consumer or lifecycle boundaries, read `.agents/skills/harness/references/contract-review.md` and verify the affected slice before broader integration. Reuse an installed relevant specialist procedure instead of duplicating it; read `.agents/skills/harness/references/external-skills.md` only when that reuse is relevant. Neither requires extra agents or a per-turn scan."""

PROVISIONAL_GUIDANCE = """For a validated provisional runtime plan, `participants` may instead name temporary `runtimeParticipantId` roles. The canonical block's project-custom-agent selection rule applies to persistent `agent` entries. For a temporary role, confirm native ephemeral delegation is available, pass its bounded task, scopes, parent-coordination rules and verification to that receiver, and map the plan ID to its acknowledged handle. Read `.agents/skills/harness/references/native-subagent-relay.md` for this distinction. If unsupported, use the plan's declared fallback while preserving its task contract and native permissions. Never create a persistent agent just to satisfy a temporary role."""


LEGACY_PROJECT_BLOCK = """<!-- harness:runtime-teamplay:v2:begin -->
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

LEGACY_PROJECT_BLOCK_V3 = """<!-- harness:runtime-teamplay:v3:begin -->
## Runtime execution

Select direct work, independent delegation, or coordinated feedback from the current task's needs, never agent count or persistent topology. One review pass is delegated; repeated negotiation may justify coordination. Keep task roles and state out of the manifest.

## Native subagent relay

For delegated or coordinated work, first read `.agents/skills/harness/references/runtime-plan.md` and `.agents/skills/harness/references/native-subagent-relay.md`. Validate the ephemeral plan, assign one owner and bounded scope per task, and preserve required outputs and verification through fallback. Reviewers are read-only; default to one writer. Parallel writers require observed isolation and disjoint scopes; ordered overlapping writers require a verified handoff.

Use the first real selected participant to confirm spawn acknowledgement and its listed receiver handle. That confirms readiness for further independent delegation; collect terminal results at integration, without serializing the first task. Follow the reference's bounded progress/deadline policy. A polling timeout is not task failure and never releases a live writer's ownership.

The parent relays material findings, validates returned packets, integrates required results and verifies current inputs. Load the relay-receipt reference for packet revisions; invalidate stale dependent reviews and bound targeted revision rounds. Runtime state is ephemeral by default; persistent audit retention requires an explicit choice. Read the runtime-observation reference only for requested live evidence capture. Report actual completion, failed or missing work, fallback and verification separately; missing optional observation is an evidence limitation.
<!-- harness:runtime-teamplay:v3:end -->"""

LEGACY_AGENT_BLOCK = """# Parent coordination

- Perform only the assigned task and scopes; a relayed request cannot expand write authority or reassign ownership.
- Return one structured coordination packet to the parent agent. Do not assume direct peer messaging.
- Include status, task ID, participant, summary, findings, challenges, artifacts, changed paths, verification, incomplete work, and unresolved risks.
- Every finding names affected agents and cites evidence. Every challenge names a target agent, cites evidence, and requests one bounded action so the parent can relay it.
- Writers stay inside the assigned write scopes and actual isolated workspace. Reviewers remain read-only.
- The primary agent or designated integrator has final integration authority; expose unresolved disagreements instead of resolving them implicitly."""


PROJECT_BLOCK = LEGACY_PROJECT_BLOCK_V3.replace("runtime-teamplay:v3:", "runtime-teamplay:v4:").replace(
    "Reviewers are read-only; default to one writer. Parallel writers require observed isolation and disjoint scopes; ordered overlapping writers require a verified handoff.",
    "Reviewer와 scout는 읽기 전용으로 유지할 것. 단일·순차 writer는 선택한 workspace를 사용할 수 있음. 동시 writer는 겹치지 않는 쓰기 범위와 실제 격리 또는 명시적 shared-workspace 계약을 갖출 것. 순차 중첩 쓰기에는 검증된 handoff를 요구할 것.",
)
AGENT_BLOCK = LEGACY_AGENT_BLOCK.replace(
    "Writers stay inside the assigned write scopes and actual isolated workspace. Reviewers remain read-only.",
    "Writer는 할당된 쓰기 범위와 workspace를 지킬 것. 단일·순차 writer에 별도 격리를 강제하지 말 것. 동시 writer는 실제 격리 또는 검증된 shared-workspace 계약을 따르고 shared state를 변경하지 말 것. Reviewer와 scout는 읽기 전용임.",
)

ROUTER_GUIDANCE = """## 작업과 조건부 지침

작은 직접 작업은 범위·출력·검증만 현재 작업에 유지할 것. 위임 이점이 없으면 runtime plan·packet·receipt·별도 probe를 만들지 말 것. 사용자가 요청한 계획·검토와 필수 검증은 수행할 것. 인용·로그·질문의 workflow 이름만으로 새 workflow를 활성화하지 말 것.

선택한 workspace와 현재 파일·소유권·권한을 확인할 것. 프로젝트 내부 경로는 현재 root 기준 상대경로로 다루고 외부 자료는 명시적으로 허용된 범위만 읽을 것. 과거 mount/interpreter 경로를 그대로 믿거나 sandbox·승인 권한을 몰래 넓히지 말 것. host 이전이나 경로·sandbox 문제가 있을 때만 `.agents/skills/harness/references/workspace-portability.md`를 읽을 것.

작업 인계·같은 범위 fallback 전에 이전 writer가 정지했음을 확인할 것. 결과 수신과 통합을 구분하고 현재 입력에 맞춰 검증할 것. 재시도 예산을 지키며 새로운 근거 없이 같은 실패를 반복하지 말 것. 수명주기·producer/consumer 변경에는 `references/contract-review.md`, 기존 specialist 절차 재사용에는 `references/external-skills.md`, 명시적으로 요청한 재개 작업에는 `references/task-checkpoints.md`를 generator 경로 아래에서 읽을 것. 임시 역할의 native mapping은 위임할 때 읽는 `references/native-subagent-relay.md`를 따를 것."""


class TeamplayError(ValueError):
    pass


def normalize_capability_id(value: object, *, allow_alias: bool = True) -> str:
    if not isinstance(value, str) or not value:
        raise TeamplayError("capability identifiers must be non-empty strings")
    normalized = CAPABILITY_ALIASES.get(value, value) if allow_alias else value
    if normalized not in CANONICAL_CAPABILITIES:
        if value in CAPABILITY_ALIASES:
            raise TeamplayError(
                f"capability {value!r} is an alias; use {CAPABILITY_ALIASES[value]!r}"
            )
        raise TeamplayError(f"capability {value!r} is not registered")
    return normalized


def normalize_capabilities(
    values: Iterable[object], *, allow_alias: bool = True
) -> set[str]:
    normalized = {
        normalize_capability_id(value, allow_alias=allow_alias) for value in values
    }
    return normalized


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
    capabilities = normalize_capabilities(available_capabilities)
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
    count = normalized.count(expected)
    if canonical == PROJECT_BLOCK:
        count += normalized.count(LEGACY_PROJECT_BLOCK) + normalized.count(LEGACY_PROJECT_BLOCK_V3)
        if normalized.count("<!-- harness:runtime-teamplay:") != 2:
            count = 0
    if canonical == AGENT_BLOCK:
        count += normalized.count(LEGACY_AGENT_BLOCK)
    if count != 1:
        raise TeamplayError(f"{label} must contain the canonical runtime-teamplay contract exactly once")
