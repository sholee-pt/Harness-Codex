#!/usr/bin/env python3
"""Build and validate privacy-safe Runtime Receipt Schema 2 records."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable

import harness_metadata
import harness_state
import harness_runtime_receipt_schema1 as schema1
import harness_teamplay
import validate_runtime_plan


RECEIPT_SCHEMA_VERSION = 2
LEGACY_RECEIPT_SCHEMA_VERSION = 1
PARSER_SCHEMA_VERSION = 2
CONTROL_PLANE_SCHEMA_VERSION = 1
OBSERVATION_SCHEMA_VERSION = 2
PROFILE_SCHEMA_VERSION = 1
MAX_WAIT_ATTEMPTS_PER_AGENT = 3  # Legacy receipt callers only; current policy has no poll-count gate.
MAX_WAIT_TOTAL_MS_PER_AGENT = 1_800_000
LEGACY_WAIT_POLICY = {"maxAttemptsPerAgent": 3, "maxTotalMsPerAgent": 300_000}
WAIT_POLICY = {
    "maxAttemptsPerAgent": None,
    "progressCheckpointMs": 300_000,
    "maxTotalMsPerAgent": MAX_WAIT_TOTAL_MS_PER_AGENT,
}

PUBLIC_CORE_PROFILE = "codex-public-jsonl-core-v1"
PUBLIC_COLLAB_PROFILE = "codex-public-jsonl-collab-v1"
LOCAL_SUBAGENT_PROFILE = "codex-local-rollout-subagent-activity-v1"
REGISTERED_PUBLIC_PROFILES = {
    PUBLIC_CORE_PROFILE: "none",
    PUBLIC_COLLAB_PROFILE: "optional",
}
REGISTERED_LOCAL_PROFILES = {LOCAL_SUBAGENT_PROFILE: "optional"}

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY_ID_RE = re.compile(r"^repo-[0-9a-f]{16,64}$")
PSEUDONYM_RE = re.compile(r"^(?:parent|child)-[0-9a-f]{16}$")
KNOWN_PUBLIC_EVENTS = {
    "thread.started",
    "turn.started",
    "turn.completed",
    "turn.failed",
    "item.started",
    "item.updated",
    "item.completed",
    "error",
}
KNOWN_PUBLIC_ITEMS = {
    "agent_message",
    "reasoning",
    "plan",
    "command_execution",
    "mcp_tool_call",
    "web_search",
    "file_change",
    "todo_list",
    "error",
    "collab_tool_call",
}
PUBLIC_TOP_LEVEL_FIELDS = {
    "type",
    "thread_id",
    "threadId",
    "usage",
    "item",
    "message",
    "error",
}
PUBLIC_ITEM_FIELDS = {
    "type",
    "tool",
    "action",
    "name",
    "status",
    "sender_thread_id",
    "receiver_thread_ids",
    "agents_states",
}
STANDARD_STATUSES = {
    "pending_init",
    "running",
    "completed",
    "failed",
    "interrupted",
    "errored",
    "shutdown",
    "not_found",
}
LOCAL_KINDS = {"started", "interacted", "completed", "interrupted", "errored"}
COMPLETION_SOURCE_ORDER = {
    "control-plane-wait": 0,
    "public-event": 1,
    "local-session-terminal": 2,
    "agent-reported": 3,
}
FAILURE_SOURCE_VALUES = {
    "none",
    "control-plane",
    "public-event",
    "local-session",
    "binding",
    "agent-reported",
    "mixed",
}
FAILURE_CODES = {
    "binding-conflict",
    "capture-incomplete",
    "completion-conflict",
    "empty-receiver-handle",
    "local-terminal-failure",
    "missing-result",
    "profile-conflict",
    "public-terminal-failure",
    "unknown-receiver-handle",
    "wait-budget-exhausted",
    "wait-failed",
    "wait-on-unknown-handle",
}
FALLBACK_REASON_CODES = {
    "capability-unavailable",
    "missing-receiver-handle",
    "packet-invalid",
    "required-result-missing",
    "subagent-unavailable",
    "unknown-receiver-handle",
    "wait-budget-exhausted",
    "wait-failed",
}
FORBIDDEN_RECEIPT_KEYS = schema1.FORBIDDEN_RECEIPT_KEYS | {
    "agentpath",
    "agentthreadid",
    "childthreadid",
    "parentthreadid",
    "receiverhandle",
    "spawninstanceid",
    "taskname",
    "threadid",
}

RuntimeReceiptError = schema1.RuntimeReceiptError


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def pseudonym(kind: str, value: str, salt: bytes) -> str:
    if kind not in {"parent", "child"}:
        raise RuntimeReceiptError("pseudonym kind is unsupported")
    suffix = hashlib.sha256(salt + bytes([0]) + value.encode("utf-8")).hexdigest()[:16]
    return f"{kind}-{suffix}"


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeReceiptError(f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeReceiptError(f"{label} must be non-empty text")
    return value


def _integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeReceiptError(f"{label} must be a non-negative integer")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeReceiptError(f"{label} must be boolean")
    return value


def _text_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise RuntimeReceiptError(f"{label} must be an array of non-empty strings")
    if len(value) != len(set(value)):
        raise RuntimeReceiptError(f"{label} must not contain duplicates")
    return value


def _scan_forbidden_keys(value: Any, label: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z]", "", str(key).lower())
            if normalized in FORBIDDEN_RECEIPT_KEYS:
                raise RuntimeReceiptError(
                    f"{label} contains privacy-forbidden field {key!r}"
                )
            _scan_forbidden_keys(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_forbidden_keys(item, f"{label}[{index}]")


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _surface_fingerprint(
    *, source: str, profile_id: str, codex_cli_version: str, signatures: set[str]
) -> str:
    return digest(
        {
            "profileSchemaVersion": PROFILE_SCHEMA_VERSION,
            "source": source,
            "profileId": profile_id,
            "codexCliVersion": codex_cli_version,
            "signatures": sorted(signatures),
        }
    )


def _participant_id(value: dict[str, Any]) -> str:
    identifier = value.get("agent", value.get("runtimeParticipantId"))
    return _text(identifier, "participant identifier")


def _new_state(participant: str) -> dict[str, Any]:
    return {
        "participant": participant,
        "selected": True,
        "spawnRequested": False,
        "receiverHandleAcknowledged": False,
        "sessionBound": False,
        "observed": False,
        "completed": False,
        "failed": False,
        "failureSource": "none",
        "failureCodes": [],
        "fallback": False,
        "fallbackAdapter": None,
        "fallbackReasonCode": None,
        "completionSources": [],
        "completionEvidenceStrength": "none",
        "executionOutcome": "unknown",
        "lifecycleState": "pending",
        "waitAttempts": 0,
        "waitTimeMs": 0,
        "_failureSources": set(),
        "_controlHandle": None,
        "_spawnInstance": None,
        "_childId": None,
        "_outcomes": {},
    }


def _add_failure(state: dict[str, Any], code: str, source: str) -> None:
    if code not in FAILURE_CODES:
        raise RuntimeReceiptError(f"unsupported failure code {code!r}")
    state["failed"] = True
    if code not in state["failureCodes"]:
        state["failureCodes"].append(code)
    state["_failureSources"].add(source)


def _record_outcome(
    state: dict[str, Any], source: str, outcome: str, failure_source: str
) -> None:
    previous = state["_outcomes"].get(source)
    if previous is not None and previous != outcome:
        _add_failure(state, "completion-conflict", failure_source)
        return
    state["_outcomes"][source] = outcome


def _add_completion(state: dict[str, Any], source: str, outcome: str = "succeeded") -> None:
    if source not in COMPLETION_SOURCE_ORDER:
        raise RuntimeReceiptError(f"unsupported completion source {source!r}")
    if source not in state["completionSources"]:
        state["completionSources"].append(source)
    failure_source = {
        "control-plane-wait": "control-plane",
        "public-event": "public-event",
        "local-session-terminal": "local-session",
        "agent-reported": "agent-reported",
    }[source]
    _record_outcome(state, source, outcome, failure_source)
    if source != "agent-reported" and outcome == "succeeded":
        state["completed"] = True
        state["executionOutcome"] = "succeeded"
        state["lifecycleState"] = "terminal"


def _finalize_state(state: dict[str, Any]) -> dict[str, Any]:
    runtime_outcomes = {
        outcome
        for source, outcome in state["_outcomes"].items()
        if source != "agent-reported" and outcome != "unknown"
    }
    if len(runtime_outcomes) > 1:
        _add_failure(state, "completion-conflict", "binding")
        state["completed"] = False
        state["executionOutcome"] = "unknown"
    elif runtime_outcomes:
        outcome = next(iter(runtime_outcomes))
        state["executionOutcome"] = outcome
        state["completed"] = outcome == "succeeded"
        state["lifecycleState"] = "terminal"
    if state["failed"] and state["executionOutcome"] == "unknown":
        state["executionOutcome"] = "failed"
    sources = state.pop("_failureSources")
    if len(sources) == 1:
        state["failureSource"] = next(iter(sources))
    elif len(sources) > 1:
        state["failureSource"] = "mixed"
    state["completionSources"].sort(key=COMPLETION_SOURCE_ORDER.__getitem__)
    material_sources = set(state["completionSources"]) - {"agent-reported"}
    if state["failed"] and "completion-conflict" in state["failureCodes"]:
        strength = "conflicted"
    elif (
        state["sessionBound"]
        and "control-plane-wait" in material_sources
        and "local-session-terminal" in material_sources
    ) or {"public-event", "local-session-terminal"}.issubset(material_sources):
        strength = "cross-validated"
    elif material_sources == {"control-plane-wait"}:
        strength = "control-plane"
    elif material_sources:
        strength = "single-source-runtime"
    elif "agent-reported" in state["completionSources"]:
        strength = "reported-only"
    else:
        strength = "none"
    state["completionEvidenceStrength"] = strength
    for private_key in ("_controlHandle", "_spawnInstance", "_childId", "_outcomes"):
        state.pop(private_key)
    return state


def _expected_agent_strength(agent: dict[str, Any]) -> str:
    sources = set(agent["completionSources"])
    material = sources - {"agent-reported"}
    if "completion-conflict" in agent["failureCodes"]:
        return "conflicted"
    if (
        agent["sessionBound"]
        and "control-plane-wait" in material
        and "local-session-terminal" in material
    ) or {"public-event", "local-session-terminal"}.issubset(material):
        return "cross-validated"
    if material == {"control-plane-wait"}:
        return "control-plane"
    if material:
        return "single-source-runtime"
    if "agent-reported" in sources:
        return "reported-only"
    return "none"


def _expected_collaboration_completeness(
    agents: list[dict[str, Any]], profiles: list[dict[str, Any]], conflict: bool
) -> str:
    if conflict:
        return "conflicted"
    if not agents:
        if profiles and all(
            profile["collaborationCompleteness"] == "not-exposed"
            for profile in profiles
        ):
            return "not-exposed"
        return "unobserved"
    if all(item["completed"] and not item["failed"] for item in agents):
        return "complete"
    if any(
        item["receiverHandleAcknowledged"]
        or item["observed"]
        or item["completionSources"]
        for item in agents
    ):
        return "partial"
    if profiles and all(
        profile["collaborationCompleteness"] == "not-exposed"
        for profile in profiles
    ):
        return "not-exposed"
    return "unobserved"


def _expected_evidence_strength(
    agents: list[dict[str, Any]], collaboration: str, conflict: bool
) -> str:
    if conflict:
        return "conflicted"
    successful = [item for item in agents if item["completed"] and not item["failed"]]
    if (
        successful
        and collaboration == "complete"
        and all(item["completionEvidenceStrength"] == "cross-validated" for item in successful)
    ):
        return "cross-validated"
    if any(item["completionEvidenceStrength"] == "control-plane" for item in successful):
        return "control-plane"
    if any(
        item["completionEvidenceStrength"] in {"single-source-runtime", "cross-validated"}
        for item in successful
    ):
        return "single-source-runtime"
    if any(item["fallback"] for item in agents):
        return "agent-reported-fallback"
    return "unobserved"


def _normalize_control_plane(
    value: Any,
    *,
    plan: dict[str, Any],
    states: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    report = _object(value, "control-plane report")
    if set(report) != {"schemaVersion", "source", "agents", "tasks"}:
        raise RuntimeReceiptError("control-plane report fields are invalid")
    if report.get("schemaVersion") != CONTROL_PLANE_SCHEMA_VERSION:
        raise RuntimeReceiptError("control-plane report schema version is unsupported")
    if report.get("source") != "codex-control-plane":
        raise RuntimeReceiptError("control-plane report source is unsupported")
    raw_agents = report.get("agents")
    if not isinstance(raw_agents, list):
        raise RuntimeReceiptError("control-plane agents must be an array")
    controls: dict[str, dict[str, Any]] = {}
    seen_handles: set[str] = set()
    seen_spawn_instances: set[str] = set()
    for index, raw in enumerate(raw_agents):
        entry = _object(raw, f"control-plane agents[{index}]")
        expected = {
            "participant",
            "spawnRequested",
            "receiverHandle",
            "spawnInstanceId",
            "listed",
            "waitAttempts",
            "waitTimeMs",
            "waitStatus",
            "resultCollected",
        }
        if set(entry) != expected:
            raise RuntimeReceiptError(f"control-plane agents[{index}] fields are invalid")
        participant = _text(entry.get("participant"), f"control-plane agents[{index}].participant")
        if participant not in states or participant in controls:
            raise RuntimeReceiptError("control-plane agent is unknown or duplicated")
        spawn_requested = _boolean(entry.get("spawnRequested"), "spawnRequested")
        handle = entry.get("receiverHandle")
        if handle is not None:
            handle = _text(handle, "receiverHandle")
        spawn_instance = entry.get("spawnInstanceId")
        if spawn_instance is not None:
            spawn_instance = _text(spawn_instance, "spawnInstanceId")
        listed = _boolean(entry.get("listed"), "listed")
        attempts = _integer(entry.get("waitAttempts"), "waitAttempts")
        wait_ms = _integer(entry.get("waitTimeMs"), "waitTimeMs")
        wait_status = entry.get("waitStatus")
        if wait_status not in {"not-waited", "running", "completed", "failed", "interrupted"}:
            raise RuntimeReceiptError("waitStatus is invalid")
        result_collected = _boolean(entry.get("resultCollected"), "resultCollected")
        state = states[participant]
        state["spawnRequested"] = spawn_requested
        state["waitAttempts"] = attempts
        state["waitTimeMs"] = wait_ms
        state["_controlHandle"] = handle
        state["_spawnInstance"] = spawn_instance
        # Polling cadence and elapsed budget are policy observations, not
        # native terminal failures. Preserve the observed execution outcome.
        if spawn_requested and handle is None:
            _add_failure(state, "empty-receiver-handle", "control-plane")
            if attempts:
                _add_failure(state, "wait-on-unknown-handle", "control-plane")
        if handle is not None and not spawn_requested:
            raise RuntimeReceiptError("receiver handle requires a spawn request")
        if handle is not None and spawn_instance is None:
            raise RuntimeReceiptError("receiver handle requires a spawn instance")
        if handle is not None and handle in seen_handles:
            raise RuntimeReceiptError("control-plane report reuses a receiver handle")
        if spawn_instance is not None and spawn_instance in seen_spawn_instances:
            raise RuntimeReceiptError("control-plane report reuses a spawn instance")
        if handle is not None:
            seen_handles.add(handle)
        if spawn_instance is not None:
            seen_spawn_instances.add(spawn_instance)
        if listed and handle is None:
            raise RuntimeReceiptError("listed agent requires a receiver handle")
        if handle is not None and listed:
            state["receiverHandleAcknowledged"] = True
            state["lifecycleState"] = "running"
        elif handle is not None:
            _add_failure(state, "unknown-receiver-handle", "control-plane")
            if attempts:
                _add_failure(state, "wait-on-unknown-handle", "control-plane")
        if result_collected and wait_status != "completed":
            raise RuntimeReceiptError("resultCollected requires a completed wait")
        if wait_status == "completed":
            if attempts == 0:
                raise RuntimeReceiptError("completed wait requires at least one attempt")
            if state["receiverHandleAcknowledged"] and result_collected:
                _add_completion(state, "control-plane-wait")
            elif state["receiverHandleAcknowledged"]:
                _add_failure(state, "missing-result", "control-plane")
        elif wait_status in {"failed", "interrupted"}:
            if attempts == 0:
                raise RuntimeReceiptError("terminal wait requires at least one attempt")
            _record_outcome(
                state,
                "control-plane-wait",
                "failed" if wait_status == "failed" else "interrupted",
                "control-plane",
            )
            state["lifecycleState"] = "terminal"
            _add_failure(state, "wait-failed", "control-plane")
        elif wait_status == "not-waited" and (attempts or wait_ms):
            raise RuntimeReceiptError("not-waited cannot record wait attempts or time")
        controls[participant] = entry
    if set(controls) != set(states):
        raise RuntimeReceiptError("control-plane report must account for every selected participant")
    raw_tasks = report.get("tasks")
    if not isinstance(raw_tasks, list):
        raise RuntimeReceiptError("control-plane tasks must be an array")
    plan_tasks = {item["id"]: item for item in plan.get("tasks", [])}
    task_records: list[dict[str, Any]] = []
    seen_tasks: set[str] = set()
    resolutions = {
        "none",
        "direct-output",
        "delegated-output",
        "relay-integration",
        "fallback-output",
        "failed",
    }
    for index, raw in enumerate(raw_tasks):
        entry = _object(raw, f"control-plane tasks[{index}]")
        if set(entry) != {"taskId", "participant", "resolution", "validated"}:
            raise RuntimeReceiptError(f"control-plane tasks[{index}] fields are invalid")
        task_id = _text(entry.get("taskId"), "taskId")
        if task_id not in plan_tasks or task_id in seen_tasks:
            raise RuntimeReceiptError("control-plane task is unknown or duplicated")
        participant = entry.get("participant")
        if participant is not None:
            participant = _text(participant, "task participant")
            if participant != plan_tasks[task_id]["owner"]:
                raise RuntimeReceiptError("task participant does not match runtime-plan owner")
        resolution = entry.get("resolution")
        if resolution not in resolutions:
            raise RuntimeReceiptError("task resolution is invalid")
        validated = _boolean(entry.get("validated"), "task validated")
        if resolution in {"none", "failed"} and validated:
            raise RuntimeReceiptError("none or failed task resolution cannot be validated")
        if resolution in {"delegated-output", "relay-integration", "fallback-output"} and participant is None:
            raise RuntimeReceiptError("delegated, relay, and fallback tasks require a participant")
        task_records.append(
            {
                "taskId": task_id,
                "required": bool(plan_tasks[task_id]["required"]),
                "participant": participant,
                "resolution": resolution,
                "validated": validated,
            }
        )
        seen_tasks.add(task_id)
    if seen_tasks != set(plan_tasks):
        raise RuntimeReceiptError("control-plane report must account for every runtime-plan task")
    return controls, sorted(task_records, key=lambda item: item["taskId"])


def _normalize_bindings(
    value: Any,
    *,
    states: dict[str, dict[str, Any]],
    controls: dict[str, dict[str, Any]],
    expected_roles: dict[str, str | None],
    salt: bytes,
) -> tuple[str | None, dict[str, str], dict[str, str], str | None, bool]:
    if value is None:
        return None, {}, {}, None, False
    observation = _object(value, "observation bindings")
    expected = {
        "schemaVersion",
        "source",
        "profileId",
        "parentThreadId",
        "children",
    }
    if set(observation) != expected:
        raise RuntimeReceiptError("observation binding fields are invalid")
    if observation.get("schemaVersion") != OBSERVATION_SCHEMA_VERSION:
        raise RuntimeReceiptError("observation binding schema version is unsupported")
    if observation.get("source") != "local-session-observer":
        raise RuntimeReceiptError("observation binding source is unsupported")
    if observation.get("profileId") != LOCAL_SUBAGENT_PROFILE:
        raise RuntimeReceiptError("observation binding profile is unsupported")
    parent = _text(observation.get("parentThreadId"), "parentThreadId")
    children = observation.get("children")
    if not isinstance(children, list):
        raise RuntimeReceiptError("observation bindings children must be an array")
    child_to_participant: dict[str, str] = {}
    handle_to_participant: dict[str, str] = {}
    sanitized: list[dict[str, Any]] = []
    conflicted = False
    seen: set[str] = set()
    for index, raw in enumerate(children):
        entry = _object(raw, f"children[{index}]")
        required = {
            "participant",
            "receiverHandle",
            "spawnInstanceId",
            "childThreadId",
            "parentThreadId",
            "threadSource",
            "agentRole",
        }
        if set(entry) != required:
            raise RuntimeReceiptError(f"children[{index}] fields are invalid")
        participant = _text(entry.get("participant"), "binding participant")
        if participant not in states or participant in seen:
            raise RuntimeReceiptError("binding participant is unknown or duplicated")
        handle = _text(entry.get("receiverHandle"), "binding receiverHandle")
        spawn_instance = _text(entry.get("spawnInstanceId"), "binding spawnInstanceId")
        child = _text(entry.get("childThreadId"), "binding childThreadId")
        child_parent = _text(entry.get("parentThreadId"), "binding parentThreadId")
        role = _text(entry.get("agentRole"), "binding agentRole")
        if child in child_to_participant or handle in handle_to_participant:
            raise RuntimeReceiptError("binding reuses a child or receiver handle")
        state = states[participant]
        control = controls.get(participant)
        matches = bool(
            control
            and state["receiverHandleAcknowledged"]
            and control.get("receiverHandle") == handle
            and control.get("spawnInstanceId") == spawn_instance
            and child_parent == parent
            and entry.get("threadSource") == "subagent"
        )
        expected_role = expected_roles[participant]
        role_conflict = expected_role is not None and role != expected_role
        if matches and expected_role is not None and not role_conflict:
            state["sessionBound"] = True
            state["_childId"] = child
        elif not matches or role_conflict:
            conflicted = True
            _add_failure(state, "binding-conflict", "binding")
        child_to_participant[child] = participant
        handle_to_participant[handle] = participant
        sanitized.append(
            {
                "participant": participant,
                "child": pseudonym("child", child, salt),
                "matches": state["sessionBound"],
                "spawnInstance": digest({"salt": salt.hex(), "value": spawn_instance}),
            }
        )
        seen.add(participant)
    fingerprint = digest(
        {
            "schemaVersion": OBSERVATION_SCHEMA_VERSION,
            "profileId": LOCAL_SUBAGENT_PROFILE,
            "parent": pseudonym("parent", parent, salt),
            "children": sorted(sanitized, key=lambda item: item["participant"]),
        }
    )
    return parent, child_to_participant, handle_to_participant, fingerprint, conflicted


def _public_signature(event: dict[str, Any]) -> str:
    normalized: dict[str, Any] = {
        "eventType": event.get("type"),
        "fields": sorted(
            (key, _value_type(value))
            for key, value in event.items()
            if key in PUBLIC_TOP_LEVEL_FIELDS
        ),
    }
    item = event.get("item")
    if isinstance(item, dict):
        normalized["itemType"] = item.get("type") if item.get("type") in KNOWN_PUBLIC_ITEMS else "unknown"
        normalized["itemFields"] = sorted(
            (key, _value_type(value))
            for key, value in item.items()
            if key in PUBLIC_ITEM_FIELDS
        )
        status = item.get("status")
        if status in STANDARD_STATUSES:
            normalized["status"] = status
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _parse_public_events(
    lines: Iterable[str],
    *,
    profile_id: str,
    codex_cli_version: str,
    states: dict[str, dict[str, Any]],
    child_to_participant: dict[str, str],
    binding_parent: str | None,
) -> tuple[dict[str, Any], dict[str, int | None], str | None, bool, str, str]:
    # Version is provenance only. Each event must satisfy the selected wire contract.
    profile_key = profile_id
    compatibility = (
        "supported" if profile_key in REGISTERED_PUBLIC_PROFILES else "unsupported"
    )
    visibility = REGISTERED_PUBLIC_PROFILES.get(profile_key, "unknown")
    recorded_profile_id = (
        profile_id if profile_key in REGISTERED_PUBLIC_PROFILES else "unregistered-public"
    )
    malformed = 0
    unknown = 0
    relevant = 0
    terminal_participants: set[str] = set()
    terminal_status: str | None = None
    parent: str | None = None
    signatures: set[str] = set()
    conflict = False
    usage: dict[str, int | None] = {
        "inputTokens": None,
        "cachedInputTokens": None,
        "outputTokens": None,
        "reasoningOutputTokens": None,
    }
    line_count = 0
    for raw_line in lines:
        line_count += 1
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            malformed += 1
            continue
        signatures.add(_public_signature(event))
        event_type = event["type"]
        if event_type not in KNOWN_PUBLIC_EVENTS:
            unknown += 1
            continue
        if event_type == "thread.started":
            if compatibility == "unsupported":
                unknown += 1
                continue
            raw_parent = event.get("thread_id", event.get("threadId"))
            if isinstance(raw_parent, str) and raw_parent:
                if parent is not None and parent != raw_parent:
                    conflict = True
                    for state in states.values():
                        _add_failure(state, "profile-conflict", "public-event")
                parent = raw_parent
            else:
                unknown += 1
            continue
        if event_type == "turn.started":
            continue
        if event_type in {"turn.completed", "turn.failed"}:
            observed_terminal = (
                "succeeded" if event_type == "turn.completed" else "failed"
            )
            if compatibility != "unsupported" and terminal_status is not None and terminal_status != observed_terminal:
                conflict = True
                for state in states.values():
                    _add_failure(state, "completion-conflict", "public-event")
            terminal_status = observed_terminal
            raw_usage = event.get("usage")
            if isinstance(raw_usage, dict):
                mapping = {
                    "input_tokens": "inputTokens",
                    "cached_input_tokens": "cachedInputTokens",
                    "output_tokens": "outputTokens",
                    "reasoning_output_tokens": "reasoningOutputTokens",
                }
                for source, target in mapping.items():
                    amount = raw_usage.get(source)
                    if isinstance(amount, int) and not isinstance(amount, bool) and amount >= 0:
                        usage[target] = amount
            continue
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") not in KNOWN_PUBLIC_ITEMS:
            unknown += 1
            continue
        if event_type.startswith("item.") and not isinstance(item, dict):
            unknown += 1
            continue
        if not isinstance(item, dict) or item.get("type") != "collab_tool_call":
            continue
        relevant += 1
        if profile_id == PUBLIC_CORE_PROFILE:
            # An optional surface extension is not a native task failure.
            unknown += 1
            continue
        if compatibility != "supported" or event_type != "item.completed":
            continue
        sender = item.get("sender_thread_id")
        if not isinstance(sender, str) or not sender:
            unknown += 1
            continue
        if binding_parent is not None and sender != binding_parent:
            conflict = True
            for state in states.values():
                _add_failure(state, "binding-conflict", "binding")
            continue
        receivers = item.get("receiver_thread_ids")
        if not isinstance(receivers, list) or not all(
            isinstance(value, str) and value for value in receivers
        ):
            unknown += 1
            continue
        action = item.get("tool", item.get("action", item.get("name")))
        raw_states = item.get("agents_states")
        if action not in {"wait", "spawn_agent", "send_input", "close_agent", "resume_agent"}:
            unknown += 1
            continue
        if action == "wait" and not isinstance(raw_states, dict):
            unknown += 1
            continue
        if action == "wait" and isinstance(raw_states, dict):
            for child in receivers:
                participant = child_to_participant.get(child)
                if participant is None:
                    unknown += 1
                    continue
                state = states[participant]
                state["observed"] = True
                raw_state = raw_states.get(child)
                child_status = raw_state.get("status") if isinstance(raw_state, dict) else None
                if not isinstance(child_status, str) or child_status not in STANDARD_STATUSES:
                    unknown += 1
                    continue
                if child_status == "completed":
                    terminal_participants.add(participant)
                    _add_completion(state, "public-event")
                elif child_status in {"failed", "errored", "interrupted"}:
                    terminal_participants.add(participant)
                    _record_outcome(
                        state,
                        "public-event",
                        "interrupted" if child_status == "interrupted" else "failed",
                        "public-event",
                    )
                    _add_failure(state, "public-terminal-failure", "public-event")
        elif action == "spawn_agent":
            for child in receivers:
                participant = child_to_participant.get(child)
                if participant is not None:
                    states[participant]["observed"] = True
    if compatibility == "unsupported":
        completeness = "unobserved"
    elif conflict:
        compatibility = "degraded"
        completeness = "conflicted"
    elif visibility == "none":
        completeness = "not-exposed"
    elif terminal_participants and terminal_participants == set(states):
        completeness = "complete"
    elif relevant:
        completeness = "partial"
    else:
        completeness = "unobserved"
    if malformed or unknown:
        compatibility = "degraded" if compatibility == "supported" else compatibility
        if completeness == "not-exposed":
            completeness = "unobserved"
    profile = {
        "source": "public-jsonl",
        "profileId": recorded_profile_id,
        "profileSchemaVersion": PROFILE_SCHEMA_VERSION,
        "codexCliVersion": codex_cli_version,
        "compatibility": compatibility,
        "collaborationVisibility": visibility,
        "collaborationCompleteness": completeness,
        "surfaceFingerprint": _surface_fingerprint(
            source="public-jsonl",
            profile_id=recorded_profile_id,
            codex_cli_version=codex_cli_version,
            signatures=signatures,
        ),
        "lineCount": line_count,
        "malformedLineCount": malformed,
        "unknownStructureCount": unknown,
    }
    stream_completeness = (
        "complete"
        if terminal_status is not None and malformed == 0
        else "partial"
        if line_count
        else "unknown"
    )
    return (
        profile,
        usage,
        parent,
        conflict,
        stream_completeness,
        terminal_status or "unknown",
    )


def _local_signature(event: dict[str, Any]) -> str:
    payload = event.get("payload")
    item = payload.get("item") if isinstance(payload, dict) else None
    normalized = {
        "outerType": event.get("type") if event.get("type") == "event_msg" else "unknown",
        "payloadType": payload.get("type") if isinstance(payload, dict) else None,
        "itemType": item.get("type") if isinstance(item, dict) else None,
        "kind": item.get("kind") if isinstance(item, dict) and item.get("kind") in LOCAL_KINDS else None,
        "types": {
            "ordinal": _value_type(event.get("ordinal")),
            "thread": _value_type(payload.get("thread_id")) if isinstance(payload, dict) else "null",
            "child": _value_type(item.get("agent_thread_id")) if isinstance(item, dict) else "null",
            "handle": _value_type(item.get("agent_path")) if isinstance(item, dict) else "null",
        },
    }
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _parse_local_events(
    lines: Iterable[str] | None,
    *,
    profile_id: str | None,
    codex_cli_version: str,
    states: dict[str, dict[str, Any]],
    child_to_participant: dict[str, str],
    controls: dict[str, dict[str, Any]],
    binding_parent: str | None,
) -> tuple[dict[str, Any] | None, bool]:
    if lines is None and profile_id is None:
        return None, False
    if lines is None or profile_id is None:
        raise RuntimeReceiptError("local lines and local profile must be supplied together")
    profile_key = profile_id
    compatibility = (
        "supported" if profile_key in REGISTERED_LOCAL_PROFILES else "unsupported"
    )
    visibility = REGISTERED_LOCAL_PROFILES.get(profile_key, "unknown")
    recorded_profile_id = (
        profile_id if profile_key in REGISTERED_LOCAL_PROFILES else "unregistered-local"
    )
    malformed = 0
    unknown = 0
    relevant = 0
    terminal_participants: set[str] = set()
    signatures: set[str] = set()
    conflict = False
    line_count = 0
    for raw_line in lines:
        line_count += 1
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(event, dict):
            malformed += 1
            continue
        signatures.add(_local_signature(event))
        payload = event.get("payload")
        item = payload.get("item") if isinstance(payload, dict) else None
        if not (
            event.get("type") == "event_msg"
            and isinstance(payload, dict)
            and payload.get("type") == "item_completed"
            and isinstance(item, dict)
            and item.get("type") == "SubAgentActivity"
        ):
            continue
        relevant += 1
        if compatibility != "supported":
            continue
        kind = item.get("kind")
        child = item.get("agent_thread_id")
        handle = item.get("agent_path")
        parent = payload.get("thread_id")
        if kind not in LOCAL_KINDS or not all(
            isinstance(value, str) and value for value in (child, handle, parent)
        ):
            unknown += 1
            continue
        participant = child_to_participant.get(child)
        if participant is None:
            unknown += 1
            continue
        control = controls.get(participant)
        state = states[participant]
        if (
            binding_parent != parent
            or control is None
            or control.get("receiverHandle") != handle
        ):
            conflict = True
            _add_failure(state, "binding-conflict", "binding")
            continue
        if not state["sessionBound"]:
            unknown += 1
            continue
        state["observed"] = True
        if kind in {"started", "interacted"} and state["lifecycleState"] != "terminal":
            state["lifecycleState"] = "running"
        elif kind == "completed":
            terminal_participants.add(participant)
            _add_completion(state, "local-session-terminal")
        elif kind in {"interrupted", "errored"}:
            terminal_participants.add(participant)
            _record_outcome(
                state,
                "local-session-terminal",
                "interrupted" if kind == "interrupted" else "failed",
                "local-session",
            )
            state["lifecycleState"] = "terminal"
            _add_failure(state, "local-terminal-failure", "local-session")
    if compatibility == "unsupported":
        completeness = "unobserved"
    elif conflict:
        compatibility = "degraded"
        completeness = "conflicted"
    elif terminal_participants and terminal_participants == set(child_to_participant.values()):
        completeness = "complete"
    elif relevant:
        completeness = "partial"
    else:
        completeness = "unobserved"
    if malformed or unknown:
        compatibility = "degraded" if compatibility == "supported" else compatibility
    return {
        "source": "local-rollout",
        "profileId": recorded_profile_id,
        "profileSchemaVersion": PROFILE_SCHEMA_VERSION,
        "codexCliVersion": codex_cli_version,
        "compatibility": compatibility,
        "collaborationVisibility": visibility,
        "collaborationCompleteness": completeness,
        "surfaceFingerprint": _surface_fingerprint(
            source="local-rollout",
            profile_id=recorded_profile_id,
            codex_cli_version=codex_cli_version,
            signatures=signatures,
        ),
        "lineCount": line_count,
        "malformedLineCount": malformed,
        "unknownStructureCount": unknown,
    }, conflict


def _fallback_warnings(participant: str, state: dict[str, Any]) -> list[str]:
    warnings = [f"fallback for {participant} is task-accounted but agent-reported"]
    if state["receiverHandleAcknowledged"] and state["lifecycleState"] not in {"terminal", "closed"}:
        warnings.append(f"fallback for {participant} has no observed quiescence; task accounting does not authorize same-scope writes")
    return warnings


def _agent_warnings(state: dict[str, Any], wait_policy: dict[str, Any]) -> list[str]:
    warnings = _fallback_warnings(state["participant"], state) if state["fallback"] else []
    if wait_policy == WAIT_POLICY and state["waitTimeMs"] > MAX_WAIT_TOTAL_MS_PER_AGENT:
        warnings.append(f"wait budget for {state['participant']} exceeded the bounded policy; observed terminal outcome is preserved and unfinished work requires an explicit new task budget")
    return warnings


def _normalize_fallbacks(
    value: Any,
    *,
    states: dict[str, dict[str, Any]],
    task_records: list[dict[str, Any]],
) -> None:
    fallback_tasks = {
        item["taskId"]
        for item in task_records
        if item["resolution"] == "fallback-output"
    }
    if value is None:
        if fallback_tasks:
            raise RuntimeReceiptError("fallback task accounting requires a fallback report")
        return
    if not isinstance(value, list):
        raise RuntimeReceiptError("fallback report must be an array")
    seen_participants: set[str] = set()
    covered_tasks: set[str] = set()
    by_task = {item["taskId"]: item for item in task_records}
    for index, raw in enumerate(value):
        entry = _object(raw, f"fallbacks[{index}]")
        expected = {"participant", "taskIds", "adapter", "preserves", "reasonCode", "source"}
        if set(entry) != expected:
            raise RuntimeReceiptError(f"fallbacks[{index}] fields are invalid")
        participant = _text(entry.get("participant"), "fallback participant")
        if participant not in states or participant in seen_participants:
            raise RuntimeReceiptError("fallback participant is unknown or duplicated")
        task_ids = _text_list(entry.get("taskIds"), "fallback taskIds")
        if not task_ids or any(
            task_id not in fallback_tasks
            or by_task[task_id]["participant"] != participant
            for task_id in task_ids
        ):
            raise RuntimeReceiptError("fallback taskIds do not match task accounting")
        if covered_tasks.intersection(task_ids):
            raise RuntimeReceiptError("fallback taskIds must be accounted exactly once")
        if entry.get("adapter") not in {"sequential-relay", "direct"}:
            raise RuntimeReceiptError("fallback adapter is unsupported")
        if set(_text_list(entry.get("preserves"), "fallback preserves")) != set(
            harness_teamplay.PRESERVED_CONTRACTS
        ):
            raise RuntimeReceiptError("fallback must preserve input, output, and verification")
        reason = _text(entry.get("reasonCode"), "fallback reasonCode")
        if reason not in FALLBACK_REASON_CODES:
            raise RuntimeReceiptError("fallback reasonCode is unsupported")
        if entry.get("source") != "agent-reported":
            raise RuntimeReceiptError("fallback source must be agent-reported")
        state = states[participant]
        state["fallback"] = True
        state["failed"] = True
        state["fallbackAdapter"] = entry["adapter"]
        state["fallbackReasonCode"] = reason
        state["_failureSources"].add("agent-reported")
        seen_participants.add(participant)
        covered_tasks.update(task_ids)
    if covered_tasks != fallback_tasks:
        raise RuntimeReceiptError("fallback report does not account for every fallback task")


def _task_accounting_status(task_records: list[dict[str, Any]]) -> str:
    required = [item for item in task_records if item["required"]]
    if any(item["resolution"] == "failed" for item in required):
        return "failed"
    if any(item["resolution"] == "none" or not item["validated"] for item in required):
        return "partial"
    if not required:
        return "complete-direct"
    resolutions = {item["resolution"] for item in required}
    if resolutions == {"direct-output"}:
        return "complete-direct"
    if resolutions == {"fallback-output"}:
        return "complete-fallback"
    if resolutions.issubset({"delegated-output", "relay-integration"}):
        return "complete-delegated"
    return "complete-mixed"


def build_runtime_receipt(
    *,
    plan: dict[str, Any],
    lines: Iterable[str],
    public_profile_id: str,
    control_plane: Any,
    observation_bindings: Any,
    codex_cli_version: str,
    execution_mode: str,
    repository_id: str,
    harness_commit: str,
    salt: bytes,
    local_lines: Iterable[str] | None = None,
    local_profile_id: str | None = None,
    fallbacks: Any = None,
) -> dict[str, Any]:
    """Build a Schema 2 receipt without persisting raw handles or event content."""
    if execution_mode not in {"ephemeral", "persistent"}:
        raise RuntimeReceiptError("execution mode must be ephemeral or persistent")
    if not REPOSITORY_ID_RE.fullmatch(repository_id):
        raise RuntimeReceiptError("repository id must be a local repo-<hex> pseudonym")
    if not re.fullmatch(r"[0-9a-f]{7,64}", harness_commit):
        raise RuntimeReceiptError("harness commit must be a lowercase hexadecimal revision")
    if len(salt) < 16:
        raise RuntimeReceiptError("pseudonym salt must contain at least 16 bytes")
    participants = [_participant_id(item) for item in plan.get("participants", [])]
    if len(participants) != len(set(participants)):
        raise RuntimeReceiptError("runtime plan participants must be unique")
    states = {participant: _new_state(participant) for participant in participants}
    controls, task_records = _normalize_control_plane(
        control_plane, plan=plan, states=states
    )
    binding_parent, child_map, _handle_map, binding_fingerprint, binding_conflict = _normalize_bindings(
        observation_bindings,
        states=states,
        controls=controls,
        expected_roles={_participant_id(item): item.get("agent", item.get("nativeAgentRole"))
                        for item in plan.get("participants", [])},
        salt=salt,
    )
    (
        public_profile,
        usage,
        public_parent,
        public_conflict,
        stream_completeness,
        parent_terminal_outcome,
    ) = _parse_public_events(
        lines,
        profile_id=public_profile_id,
        codex_cli_version=codex_cli_version,
        states=states,
        child_to_participant=child_map,
        binding_parent=binding_parent,
    )
    local_profile, local_conflict = _parse_local_events(
        local_lines,
        profile_id=local_profile_id,
        codex_cli_version=codex_cli_version,
        states=states,
        child_to_participant=child_map,
        controls=controls,
        binding_parent=binding_parent,
    )
    if binding_parent is not None and public_parent is not None and binding_parent != public_parent:
        binding_conflict = True
        for state in states.values():
            _add_failure(state, "binding-conflict", "binding")
    _normalize_fallbacks(
        fallbacks, states=states, task_records=task_records,
    )
    conflict = binding_conflict or public_conflict or local_conflict
    agent_records = [_finalize_state(states[name]) for name in participants]
    warnings = [warning for agent in agent_records
                for warning in _agent_warnings(agent, WAIT_POLICY)]
    if any("completion-conflict" in item["failureCodes"] for item in agent_records):
        conflict = True
    profiles = [public_profile] + ([local_profile] if local_profile is not None else [])
    collaboration_completeness = _expected_collaboration_completeness(
        agent_records, profiles, conflict
    )
    task_status = _task_accounting_status(task_records)
    evidence_strength = _expected_evidence_strength(
        agent_records, collaboration_completeness, conflict
    )
    proves_live = bool(
        not conflict
        and any(
            item["completed"]
            and not item["failed"]
            and item["receiverHandleAcknowledged"]
            and "control-plane-wait" in item["completionSources"]
            for item in agent_records
        )
    )
    receipt: dict[str, Any] = {
        "receiptSchemaVersion": RECEIPT_SCHEMA_VERSION,
        "harness": {"version": harness_metadata.HARNESS_VERSION, "commit": harness_commit},
        "repositoryId": repository_id,
        "runtimePlanSha256": digest(plan),
        "codexCliVersion": codex_cli_version,
        "executionMode": execution_mode,
        "parentThreadPseudonym": (
            pseudonym("parent", public_parent or binding_parent, salt)
            if public_parent or binding_parent
            else None
        ),
        "streamCompleteness": stream_completeness,
        "collaborationCompleteness": collaboration_completeness,
        "taskAccountingStatus": task_status,
        "eventProfiles": profiles,
        "evidenceStrength": evidence_strength,
        "provesLiveSubagentExecution": proves_live,
        "parser": {
            "schemaVersion": PARSER_SCHEMA_VERSION,
            "observationSchemaVersion": OBSERVATION_SCHEMA_VERSION,
            "profileSchemaVersion": PROFILE_SCHEMA_VERSION,
        },
        "runtime": {
            "bindingFingerprint": binding_fingerprint,
            "parentTerminalOutcome": parent_terminal_outcome,
            "waitPolicy": dict(WAIT_POLICY),
            "conflictDetected": conflict,
        },
        "agents": agent_records,
        "taskAccounting": task_records,
        "measurements": {
            **usage,
            "completedAgents": sum(1 for item in agent_records if item["completed"]),
            "fallbackAgents": sum(1 for item in agent_records if item["fallback"]),
            "totalWaitAttempts": sum(item["waitAttempts"] for item in agent_records),
            "totalWaitTimeMs": sum(item["waitTimeMs"] for item in agent_records),
        },
        "warnings": warnings,
    }
    _scan_forbidden_keys(receipt)
    receipt["integrity"] = {"algorithm": "sha256", "canonicalSha256": digest(receipt)}
    validate_runtime_receipt(receipt)
    return receipt


def _validate_profile(profile: Any, index: int) -> None:
    item = _object(profile, f"eventProfiles[{index}]")
    expected = {
        "source",
        "profileId",
        "profileSchemaVersion",
        "codexCliVersion",
        "compatibility",
        "collaborationVisibility",
        "collaborationCompleteness",
        "surfaceFingerprint",
        "lineCount",
        "malformedLineCount",
        "unknownStructureCount",
    }
    if set(item) != expected:
        raise RuntimeReceiptError("event profile fields are invalid")
    if item.get("source") not in {"public-jsonl", "local-rollout"}:
        raise RuntimeReceiptError("event profile source is invalid")
    _text(item.get("profileId"), "event profile id")
    if item.get("profileSchemaVersion") != PROFILE_SCHEMA_VERSION:
        raise RuntimeReceiptError("event profile schema version is invalid")
    _text(item.get("codexCliVersion"), "event profile Codex CLI version")
    if item.get("compatibility") not in {"supported", "degraded", "unsupported"}:
        raise RuntimeReceiptError("event profile compatibility is invalid")
    if item.get("collaborationVisibility") not in {"none", "optional", "unknown"}:
        raise RuntimeReceiptError("event profile collaboration visibility is invalid")
    if item.get("collaborationCompleteness") not in {
        "not-exposed",
        "unobserved",
        "partial",
        "complete",
        "conflicted",
    }:
        raise RuntimeReceiptError("event profile collaboration completeness is invalid")
    if not HASH_RE.fullmatch(_text(item.get("surfaceFingerprint"), "surface fingerprint")):
        raise RuntimeReceiptError("event profile fingerprint is invalid")
    for key in ("lineCount", "malformedLineCount", "unknownStructureCount"):
        _integer(item.get(key), f"event profile {key}")
    if item["source"] == "public-jsonl":
        expected_visibility = REGISTERED_PUBLIC_PROFILES.get(
            item["profileId"]
        )
        if expected_visibility is None:
            if item["profileId"] != "unregistered-public" or item["compatibility"] != "unsupported":
                raise RuntimeReceiptError("unregistered public profile is inconsistent")
            expected_visibility = "unknown"
    else:
        expected_visibility = REGISTERED_LOCAL_PROFILES.get(
            item["profileId"]
        )
        if expected_visibility is None:
            if item["profileId"] != "unregistered-local" or item["compatibility"] != "unsupported":
                raise RuntimeReceiptError("unregistered local profile is inconsistent")
            expected_visibility = "unknown"
    if item["collaborationVisibility"] != expected_visibility:
        raise RuntimeReceiptError("event profile visibility is inconsistent")
    if (
        item["collaborationCompleteness"] == "not-exposed"
        and not (
            item["compatibility"] == "supported"
            and item["collaborationVisibility"] == "none"
        )
    ):
        raise RuntimeReceiptError("not-exposed requires an exact supported profile")


def _validate_schema2(receipt: dict[str, Any]) -> dict[str, Any]:
    required = {
        "receiptSchemaVersion",
        "harness",
        "repositoryId",
        "runtimePlanSha256",
        "codexCliVersion",
        "executionMode",
        "parentThreadPseudonym",
        "streamCompleteness",
        "collaborationCompleteness",
        "taskAccountingStatus",
        "eventProfiles",
        "evidenceStrength",
        "provesLiveSubagentExecution",
        "parser",
        "runtime",
        "agents",
        "taskAccounting",
        "measurements",
        "warnings",
        "integrity",
    }
    if set(receipt) != required:
        raise RuntimeReceiptError("runtime receipt Schema 2 fields are invalid")
    if not REPOSITORY_ID_RE.fullmatch(_text(receipt.get("repositoryId"), "repositoryId")):
        raise RuntimeReceiptError("repositoryId is invalid")
    if not HASH_RE.fullmatch(_text(receipt.get("runtimePlanSha256"), "runtimePlanSha256")):
        raise RuntimeReceiptError("runtimePlanSha256 is invalid")
    harness = _object(receipt.get("harness"), "harness")
    if set(harness) != {"version", "commit"} or not re.fullmatch(
        r"[0-9]+(?:\.[0-9]+){1,2}(?:-beta)?", _text(harness.get("version"), "harness.version")
    ):
        raise RuntimeReceiptError("harness metadata is invalid")
    if not re.fullmatch(r"[0-9a-f]{7,64}", _text(harness.get("commit"), "harness.commit")):
        raise RuntimeReceiptError("harness.commit is invalid")
    _text(receipt.get("codexCliVersion"), "codexCliVersion")
    if receipt.get("executionMode") not in {"ephemeral", "persistent"}:
        raise RuntimeReceiptError("executionMode is invalid")
    parent = receipt.get("parentThreadPseudonym")
    if parent is not None and (
        not isinstance(parent, str)
        or not PSEUDONYM_RE.fullmatch(parent)
        or not parent.startswith("parent-")
    ):
        raise RuntimeReceiptError("parentThreadPseudonym is invalid")
    if receipt.get("streamCompleteness") not in {"complete", "partial", "unknown"}:
        raise RuntimeReceiptError("streamCompleteness is invalid")
    if receipt.get("collaborationCompleteness") not in {
        "not-exposed", "unobserved", "partial", "complete", "conflicted"
    }:
        raise RuntimeReceiptError("collaborationCompleteness is invalid")
    if receipt.get("taskAccountingStatus") not in {
        "complete-direct", "complete-delegated", "complete-mixed", "complete-fallback", "partial", "failed"
    }:
        raise RuntimeReceiptError("taskAccountingStatus is invalid")
    if receipt.get("evidenceStrength") not in {
        "cross-validated", "control-plane", "single-source-runtime", "agent-reported-fallback", "unobserved", "conflicted"
    }:
        raise RuntimeReceiptError("evidenceStrength is invalid")
    profiles = receipt.get("eventProfiles")
    if not isinstance(profiles, list) or not profiles:
        raise RuntimeReceiptError("eventProfiles must be a non-empty array")
    for index, profile in enumerate(profiles):
        _validate_profile(profile, index)
    if profiles[0]["source"] != "public-jsonl" or len(
        {profile["source"] for profile in profiles}
    ) != len(profiles):
        raise RuntimeReceiptError("event profile sources are missing or duplicated")
    if any(profile["codexCliVersion"] != receipt["codexCliVersion"] for profile in profiles):
        raise RuntimeReceiptError("event profile CLI versions are inconsistent")
    parser = _object(receipt.get("parser"), "parser")
    if parser != {
        "schemaVersion": PARSER_SCHEMA_VERSION,
        "observationSchemaVersion": OBSERVATION_SCHEMA_VERSION,
        "profileSchemaVersion": PROFILE_SCHEMA_VERSION,
    }:
        raise RuntimeReceiptError("parser metadata is invalid")
    runtime = _object(receipt.get("runtime"), "runtime")
    if set(runtime) != {
        "bindingFingerprint",
        "parentTerminalOutcome",
        "waitPolicy",
        "conflictDetected",
    }:
        raise RuntimeReceiptError("runtime fields are invalid")
    binding = runtime.get("bindingFingerprint")
    if binding is not None and (not isinstance(binding, str) or not HASH_RE.fullmatch(binding)):
        raise RuntimeReceiptError("binding fingerprint is invalid")
    if runtime.get("parentTerminalOutcome") not in {"succeeded", "failed", "unknown"}:
        raise RuntimeReceiptError("parent terminal outcome is invalid")
    expected_stream = (
        "complete"
        if runtime["parentTerminalOutcome"] != "unknown"
        and profiles[0]["malformedLineCount"] == 0
        else "partial"
        if profiles[0]["lineCount"]
        else "unknown"
    )
    if receipt["streamCompleteness"] != expected_stream:
        raise RuntimeReceiptError("streamCompleteness is inconsistent")
    if runtime.get("waitPolicy") not in (WAIT_POLICY, LEGACY_WAIT_POLICY):
        raise RuntimeReceiptError("runtime wait policy is invalid")
    _boolean(runtime.get("conflictDetected"), "runtime conflictDetected")
    agents = receipt.get("agents")
    if not isinstance(agents, list):
        raise RuntimeReceiptError("agents must be an array")
    completed_count = 0
    fallback_count = 0
    expected_warnings: list[str] = []
    seen_participants: set[str] = set()
    agent_fields = {
        "participant", "selected", "spawnRequested", "receiverHandleAcknowledged",
        "sessionBound", "observed", "completed", "failed", "failureSource",
        "failureCodes", "fallback", "fallbackAdapter", "fallbackReasonCode",
        "completionSources", "completionEvidenceStrength", "executionOutcome",
        "lifecycleState", "waitAttempts", "waitTimeMs",
    }
    for index, raw in enumerate(agents):
        agent = _object(raw, f"agents[{index}]")
        if set(agent) != agent_fields:
            raise RuntimeReceiptError("agent fields are invalid")
        participant = _text(agent.get("participant"), "agent participant")
        if participant in seen_participants:
            raise RuntimeReceiptError("agent participants must be unique")
        seen_participants.add(participant)
        for key in (
            "selected", "spawnRequested", "receiverHandleAcknowledged", "sessionBound",
            "observed", "completed", "failed", "fallback",
        ):
            _boolean(agent.get(key), f"agent {key}")
        if not agent["selected"]:
            raise RuntimeReceiptError("receipt agents must be selected participants")
        if agent["receiverHandleAcknowledged"] and not agent["spawnRequested"]:
            raise RuntimeReceiptError("handle acknowledgement requires a spawn request")
        if agent["sessionBound"] and not agent["receiverHandleAcknowledged"]:
            raise RuntimeReceiptError("session binding requires handle acknowledgement")
        if agent["failureSource"] not in FAILURE_SOURCE_VALUES:
            raise RuntimeReceiptError("agent failureSource is invalid")
        codes = _text_list(agent.get("failureCodes"), "agent failureCodes")
        if set(codes) - FAILURE_CODES:
            raise RuntimeReceiptError("agent failureCodes contain an unsupported value")
        if agent["failed"] is (agent["failureSource"] == "none"):
            raise RuntimeReceiptError("agent failure source is inconsistent")
        sources = _text_list(agent.get("completionSources"), "agent completionSources")
        if set(sources) - set(COMPLETION_SOURCE_ORDER):
            raise RuntimeReceiptError("agent completionSources are invalid")
        if agent["completed"] and not (
            set(sources) - {"agent-reported"}
        ):
            raise RuntimeReceiptError("agent-reported alone cannot establish completion")
        if agent["completionEvidenceStrength"] not in {
            "none", "reported-only", "control-plane", "single-source-runtime", "cross-validated", "conflicted"
        }:
            raise RuntimeReceiptError("agent completion evidence strength is invalid")
        if agent["completionEvidenceStrength"] != _expected_agent_strength(agent):
            raise RuntimeReceiptError("agent completion evidence strength is inconsistent")
        if agent["executionOutcome"] not in {"unknown", "succeeded", "failed", "interrupted"}:
            raise RuntimeReceiptError("agent executionOutcome is invalid")
        if agent["completed"] is not (
            agent["executionOutcome"] == "succeeded"
            and bool(set(sources) - {"agent-reported"})
        ):
            raise RuntimeReceiptError("agent completion state is inconsistent")
        if agent["lifecycleState"] not in {"pending", "running", "terminal", "closed"}:
            raise RuntimeReceiptError("agent lifecycleState is invalid")
        _integer(agent.get("waitAttempts"), "agent waitAttempts")
        _integer(agent.get("waitTimeMs"), "agent waitTimeMs")
        if agent["fallback"]:
            fallback_count += 1
            if agent.get("fallbackAdapter") not in {"sequential-relay", "direct"}:
                raise RuntimeReceiptError("fallback adapter is invalid")
            reason = _text(agent.get("fallbackReasonCode"), "fallbackReasonCode")
            if reason not in FALLBACK_REASON_CODES:
                raise RuntimeReceiptError("fallbackReasonCode is unsupported")
        elif agent.get("fallbackAdapter") is not None or agent.get("fallbackReasonCode") is not None:
            raise RuntimeReceiptError("non-fallback agent cannot retain fallback metadata")
        expected_warnings.extend(_agent_warnings(agent, runtime["waitPolicy"]))
        if agent["completed"]:
            completed_count += 1
    tasks = receipt.get("taskAccounting")
    if not isinstance(tasks, list):
        raise RuntimeReceiptError("taskAccounting must be an array")
    seen_task_ids: set[str] = set()
    for index, raw in enumerate(tasks):
        task = _object(raw, f"taskAccounting[{index}]")
        if set(task) != {"taskId", "required", "participant", "resolution", "validated"}:
            raise RuntimeReceiptError("task accounting fields are invalid")
        task_id = _text(task.get("taskId"), "taskId")
        if task_id in seen_task_ids:
            raise RuntimeReceiptError("taskAccounting task IDs must be unique")
        seen_task_ids.add(task_id)
        _boolean(task.get("required"), "task required")
        participant = task.get("participant")
        if participant is not None:
            participant = _text(participant, "task participant")
            if participant not in seen_participants:
                raise RuntimeReceiptError("task participant is not a receipt agent")
        if task.get("resolution") not in {
            "none", "direct-output", "delegated-output", "relay-integration", "fallback-output", "failed"
        }:
            raise RuntimeReceiptError("task resolution is invalid")
        validated = _boolean(task.get("validated"), "task validated")
        resolution = task["resolution"]
        if resolution == "direct-output" and participant is not None:
            raise RuntimeReceiptError("direct task output cannot name an agent participant")
        if resolution in {"delegated-output", "relay-integration", "fallback-output"} and participant is None:
            raise RuntimeReceiptError("delegated, relay, and fallback tasks require a participant")
        if resolution in {"none", "failed"} and validated:
            raise RuntimeReceiptError("none or failed task resolution cannot be validated")
    if receipt["taskAccountingStatus"] != _task_accounting_status(tasks):
        raise RuntimeReceiptError("taskAccountingStatus is inconsistent")
    measurements = _object(receipt.get("measurements"), "measurements")
    measurement_fields = {
        "inputTokens", "cachedInputTokens", "outputTokens", "reasoningOutputTokens",
        "completedAgents", "fallbackAgents", "totalWaitAttempts", "totalWaitTimeMs",
    }
    if set(measurements) != measurement_fields:
        raise RuntimeReceiptError("measurement fields are invalid")
    for key, value in measurements.items():
        if value is not None:
            _integer(value, f"measurements.{key}")
    if measurements["completedAgents"] != completed_count or measurements["fallbackAgents"] != fallback_count:
        raise RuntimeReceiptError("measurement agent counts are inconsistent")
    if measurements["totalWaitAttempts"] != sum(item["waitAttempts"] for item in agents):
        raise RuntimeReceiptError("measurement wait attempts are inconsistent")
    if measurements["totalWaitTimeMs"] != sum(item["waitTimeMs"] for item in agents):
        raise RuntimeReceiptError("measurement wait time is inconsistent")
    warnings = _text_list(receipt.get("warnings"), "warnings")
    if warnings != expected_warnings:
        raise RuntimeReceiptError("warnings are inconsistent")
    if (receipt["collaborationCompleteness"] == "conflicted") is not runtime["conflictDetected"]:
        raise RuntimeReceiptError("conflict state is inconsistent")
    expected_collaboration = _expected_collaboration_completeness(
        agents, profiles, runtime["conflictDetected"]
    )
    if receipt["collaborationCompleteness"] != expected_collaboration:
        raise RuntimeReceiptError("collaborationCompleteness is inconsistent")
    expected_strength = _expected_evidence_strength(
        agents, expected_collaboration, runtime["conflictDetected"]
    )
    if receipt["evidenceStrength"] != expected_strength:
        raise RuntimeReceiptError("evidenceStrength is inconsistent")
    expected_live = bool(
        not runtime["conflictDetected"]
        and any(
            item["completed"]
            and not item["failed"]
            and item["receiverHandleAcknowledged"]
            and "control-plane-wait" in item["completionSources"]
            for item in agents
        )
    )
    if receipt.get("provesLiveSubagentExecution") is not expected_live:
        raise RuntimeReceiptError("live execution claim is inconsistent")
    integrity = _object(receipt.get("integrity"), "integrity")
    if set(integrity) != {"algorithm", "canonicalSha256"} or integrity.get("algorithm") != "sha256":
        raise RuntimeReceiptError("integrity metadata is invalid")
    if not HASH_RE.fullmatch(_text(integrity.get("canonicalSha256"), "integrity hash")):
        raise RuntimeReceiptError("integrity hash is invalid")
    unsigned = dict(receipt)
    unsigned.pop("integrity")
    if digest(unsigned) != integrity["canonicalSha256"]:
        raise RuntimeReceiptError("runtime receipt canonical hash does not match")
    return {
        "receiptSchemaVersion": RECEIPT_SCHEMA_VERSION,
        "valid": True,
        "streamCompleteness": receipt["streamCompleteness"],
        "collaborationCompleteness": receipt["collaborationCompleteness"],
        "taskAccountingStatus": receipt["taskAccountingStatus"],
        "evidenceStrength": receipt["evidenceStrength"],
        "provesLiveSubagentExecution": receipt["provesLiveSubagentExecution"],
        "warnings": list(receipt["warnings"]),
        "errors": [],
    }


def validate_runtime_receipt(value: Any) -> dict[str, Any]:
    receipt = _object(value, "receipt")
    _scan_forbidden_keys(receipt)
    version = receipt.get("receiptSchemaVersion")
    if version == LEGACY_RECEIPT_SCHEMA_VERSION:
        return schema1.validate_runtime_receipt(receipt)
    if version != RECEIPT_SCHEMA_VERSION:
        raise RuntimeReceiptError("runtime receipt schema version is unsupported")
    return _validate_schema2(receipt)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path = harness_state.external_location(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        harness_state.checked_absolute(path)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--jsonl", required=True)
    parser.add_argument("--public-profile", required=True)
    parser.add_argument("--control-plane-report", required=True)
    parser.add_argument("--observation-bindings")
    parser.add_argument("--local-jsonl")
    parser.add_argument("--local-profile")
    parser.add_argument("--codex-cli-version", required=True)
    parser.add_argument("--execution-mode", choices=("ephemeral", "persistent"), required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--harness-commit", required=True)
    parser.add_argument("--salt-file", required=True)
    parser.add_argument("--fallback-report")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        root = Path(args.root).resolve()
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        validate_runtime_plan.validate_runtime_plan(root, plan)
        lines = Path(args.jsonl).read_text(encoding="utf-8").splitlines()
        control_plane = json.loads(
            Path(args.control_plane_report).read_text(encoding="utf-8")
        )
        observation_bindings = (
            json.loads(Path(args.observation_bindings).read_text(encoding="utf-8"))
            if args.observation_bindings
            else None
        )
        local_lines = (
            Path(args.local_jsonl).read_text(encoding="utf-8").splitlines()
            if args.local_jsonl
            else None
        )
        fallbacks = (
            json.loads(Path(args.fallback_report).read_text(encoding="utf-8"))
            if args.fallback_report
            else None
        )
        receipt = build_runtime_receipt(
            plan=plan,
            lines=lines,
            public_profile_id=args.public_profile,
            control_plane=control_plane,
            observation_bindings=observation_bindings,
            codex_cli_version=args.codex_cli_version,
            execution_mode=args.execution_mode,
            repository_id=args.repository_id,
            harness_commit=args.harness_commit,
            salt=Path(args.salt_file).read_bytes(),
            local_lines=local_lines,
            local_profile_id=args.local_profile,
            fallbacks=fallbacks,
        )
        if args.output:
            _write_json_atomic(Path(args.output), receipt)
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
        return 0
    except (
        OSError,
        harness_state.StateError,
        UnicodeError,
        json.JSONDecodeError,
        RuntimeReceiptError,
        validate_runtime_plan.RuntimePlanError,
    ) as exc:
        print(
            json.dumps(
                {
                    "receiptSchemaVersion": RECEIPT_SCHEMA_VERSION,
                    "valid": False,
                    "provesLiveSubagentExecution": False,
                    "warnings": [],
                    "errors": [str(exc)],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
