#!/usr/bin/env python3
"""Build and validate privacy-safe receipts from bounded Codex JSONL events."""

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
import harness_teamplay
import validate_runtime_plan


RECEIPT_SCHEMA_VERSION = 1
PARSER_SCHEMA_VERSION = 1
OBSERVATION_SCHEMA_VERSION = 1
SUPPORTED_CODEX_CLI_VERSIONS = frozenset({"0.152.1"})
MAX_WAIT_ATTEMPTS_PER_AGENT = 3
MAX_WAIT_TOTAL_MS_PER_AGENT = 300_000
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY_ID_RE = re.compile(r"^repo-[0-9a-f]{16,64}$")
PSEUDONYM_RE = re.compile(r"^(?:parent|child)-[0-9a-f]{16}$")
KNOWN_EVENTS = {
    "thread.started",
    "turn.started",
    "turn.completed",
    "turn.failed",
    "item.started",
    "item.updated",
    "item.completed",
    "error",
}
KNOWN_NONCOLLAB_ITEM_TYPES = {
    "agent_message",
    "reasoning",
    "plan",
    "command_execution",
    "mcp_tool_call",
    "web_search",
    "file_change",
    "todo_list",
    "error",
}
COLLAB_ITEM_TYPES = {"collab_tool_call"}
SPAWN_ACTIONS = {"spawn_agent"}
WAIT_ACTIONS = {"wait"}
FOLLOWUP_ACTIONS = {"send_input", "close_agent"}
SUCCESS_STATUSES = {"completed"}
FAILURE_STATUSES = {"failed"}
ACTIVE_AGENT_STATUSES = {"pending_init", "running"}
COMPLETED_AGENT_STATUSES = {"completed"}
FAILED_AGENT_STATUSES = {"interrupted", "errored", "shutdown", "not_found"}
FORBIDDEN_RECEIPT_KEYS = {
    "absolutepath",
    "auth",
    "authentication",
    "authorization",
    "command",
    "credential",
    "cwd",
    "message",
    "prompt",
    "rawagentmessage",
    "rawjsonl",
    "rawmessage",
    "rawprompt",
    "repositorypath",
    "repositoryroot",
    "rootpath",
    "secret",
    "sourcecontent",
    "sourcepath",
    "transcript",
}


class RuntimeReceiptError(ValueError):
    pass


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


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeReceiptError(f"{label} must be an object")
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeReceiptError(f"{label} must be non-empty text")
    return value


def _require_text_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise RuntimeReceiptError(f"{label} must be an array of non-empty strings")
    if len(value) != len(set(value)):
        raise RuntimeReceiptError(f"{label} must not contain duplicates")
    return value


def _integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeReceiptError(f"{label} must be a non-negative integer")
    return value


def _participant_id(value: dict[str, Any]) -> str:
    identifier = value.get("agent", value.get("runtimeParticipantId"))
    return _require_text(identifier, "participant identifier")


def _new_state(participant: str) -> dict[str, Any]:
    return {
        "participant": participant,
        "selected": True,
        "spawnRequested": False,
        "spawned": False,
        "observed": False,
        "completed": False,
        "failed": False,
        "fallback": False,
        "bindingValidated": False,
        "observationSource": "unobserved",
        "childThreadPseudonym": None,
        "spawnFingerprint": None,
        "completionFingerprint": None,
        "waitAttempts": 0,
        "waitTimeMs": 0,
        "failureCodes": [],
        "fallbackAdapter": None,
    }


def _extract_action(item: dict[str, Any]) -> str | None:
    for key in ("tool", "action", "name"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_thread_ids(item: dict[str, Any], key: str) -> list[str] | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(entry, str) and entry for entry in value):
        return None
    return value


def _add_failure(state: dict[str, Any], code: str) -> None:
    state["failed"] = True
    if code not in state["failureCodes"]:
        state["failureCodes"].append(code)


def _sanitized_collab_event(
    event_type: str, item: dict[str, Any], salt: bytes
) -> dict[str, Any]:
    """Remove prompt/message content and pseudonymize all thread identifiers."""
    sender = item.get("sender_thread_id")
    receivers = _extract_thread_ids(item, "receiver_thread_ids") or []
    raw_states = item.get("agents_states")
    statuses: dict[str, str] = {}
    if isinstance(raw_states, dict):
        for child_id, raw_state in raw_states.items():
            if not isinstance(child_id, str) or not isinstance(raw_state, dict):
                continue
            status = raw_state.get("status")
            if isinstance(status, str):
                statuses[pseudonym("child", child_id, salt)] = status
    return {
        "eventType": event_type,
        "itemType": item.get("type"),
        "tool": item.get("tool"),
        "status": item.get("status"),
        "sender": (
            pseudonym("parent", sender, salt)
            if isinstance(sender, str) and sender
            else None
        ),
        "receivers": [pseudonym("child", child_id, salt) for child_id in receivers],
        "agentStatuses": statuses,
    }


def _normalize_observation_bindings(
    value: Any,
    participants: list[str],
    states: dict[str, dict[str, Any]],
    salt: bytes,
) -> tuple[str | None, dict[str, str], dict[str, int], str | None]:
    """Validate a temporary raw-ID index without copying raw identifiers to output."""
    if value is None:
        for state in states.values():
            _add_failure(state, "missing-observation-binding")
        return None, {}, {}, None
    observation = _require_object(value, "observation bindings")
    expected = {"schemaVersion", "source", "parentThreadId", "children"}
    if set(observation) != expected:
        raise RuntimeReceiptError("observation binding fields are invalid")
    if observation.get("schemaVersion") != OBSERVATION_SCHEMA_VERSION:
        raise RuntimeReceiptError("observation binding schema version is unsupported")
    if observation.get("source") != "local-session-observer":
        raise RuntimeReceiptError("observation binding source is unsupported")
    parent = _require_text(observation.get("parentThreadId"), "parentThreadId")
    children = observation.get("children")
    if not isinstance(children, list):
        raise RuntimeReceiptError("observation bindings children must be an array")
    expected_participants = set(participants)
    seen_participants: set[str] = set()
    child_to_participant: dict[str, str] = {}
    expected_wait_attempts: dict[str, int] = {}
    sanitized_children: list[dict[str, Any]] = []
    for index, raw in enumerate(children):
        entry = _require_object(raw, f"children[{index}]")
        required = {
            "participant",
            "childThreadId",
            "parentThreadId",
            "threadSource",
            "agentRole",
            "waitAttempts",
            "waitTimeMs",
        }
        if set(entry) != required:
            raise RuntimeReceiptError(f"children[{index}] fields are invalid")
        participant = _require_text(entry.get("participant"), f"children[{index}].participant")
        child_id = _require_text(entry.get("childThreadId"), f"children[{index}].childThreadId")
        child_parent = _require_text(
            entry.get("parentThreadId"), f"children[{index}].parentThreadId"
        )
        role = _require_text(entry.get("agentRole"), f"children[{index}].agentRole")
        attempts = _integer(entry.get("waitAttempts"), f"children[{index}].waitAttempts")
        wait_ms = _integer(entry.get("waitTimeMs"), f"children[{index}].waitTimeMs")
        if participant not in expected_participants or participant in seen_participants:
            raise RuntimeReceiptError(
                f"children[{index}] references an unknown or duplicate participant"
            )
        if child_id in child_to_participant:
            raise RuntimeReceiptError("observation bindings reuse a child thread id")
        state = states[participant]
        state["waitTimeMs"] = wait_ms
        if child_parent != parent:
            _add_failure(state, "parent-mismatch")
        if entry.get("threadSource") != "subagent":
            _add_failure(state, "invalid-thread-source")
        if role != participant:
            _add_failure(state, "role-mismatch")
        if attempts > MAX_WAIT_ATTEMPTS_PER_AGENT or wait_ms > MAX_WAIT_TOTAL_MS_PER_AGENT:
            _add_failure(state, "wait-budget-exhausted")
        if not state["failed"]:
            state["bindingValidated"] = True
        seen_participants.add(participant)
        child_to_participant[child_id] = participant
        expected_wait_attempts[participant] = attempts
        sanitized_children.append(
            {
                "participant": participant,
                "child": pseudonym("child", child_id, salt),
                "parentMatches": child_parent == parent,
                "threadSource": entry.get("threadSource"),
                "agentRole": role,
                "waitAttempts": attempts,
                "waitTimeMs": wait_ms,
            }
        )
    for participant in expected_participants - seen_participants:
        _add_failure(states[participant], "missing-observation-binding")
    return parent, child_to_participant, expected_wait_attempts, digest(
        {
            "schemaVersion": OBSERVATION_SCHEMA_VERSION,
            "source": observation["source"],
            "parent": pseudonym("parent", parent, salt),
            "children": sorted(sanitized_children, key=lambda item: item["participant"]),
        }
    )


def _scan_forbidden_keys(value: Any, label: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z]", "", str(key).lower())
            if normalized in FORBIDDEN_RECEIPT_KEYS:
                raise RuntimeReceiptError(f"{label} contains privacy-forbidden field {key!r}")
            _scan_forbidden_keys(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_forbidden_keys(item, f"{label}[{index}]")


def _normalize_fallbacks(
    value: Any, states: dict[str, dict[str, Any]]
) -> tuple[int, list[str]]:
    if value is None:
        return 0, []
    if not isinstance(value, list):
        raise RuntimeReceiptError("fallback report must be an array")
    seen: set[str] = set()
    warnings: list[str] = []
    for index, raw in enumerate(value):
        entry = _require_object(raw, f"fallbacks[{index}]")
        expected = {"participant", "adapter", "preserves", "reasonCode", "source"}
        if set(entry) != expected:
            raise RuntimeReceiptError(f"fallbacks[{index}] fields are invalid")
        participant = _require_text(entry.get("participant"), f"fallbacks[{index}].participant")
        if participant not in states or participant in seen:
            raise RuntimeReceiptError(f"fallbacks[{index}] references an unknown or duplicate participant")
        if entry.get("adapter") not in {"sequential-relay", "direct"}:
            raise RuntimeReceiptError(f"fallbacks[{index}].adapter is unsupported")
        if set(_require_text_list(entry.get("preserves"), f"fallbacks[{index}].preserves")) != set(
            harness_teamplay.PRESERVED_CONTRACTS
        ):
            raise RuntimeReceiptError("fallback must preserve input, output, and verification")
        _require_text(entry.get("reasonCode"), f"fallbacks[{index}].reasonCode")
        if entry.get("source") != "agent-reported":
            raise RuntimeReceiptError("fallback source must be agent-reported")
        state = states[participant]
        if state["completed"]:
            raise RuntimeReceiptError("a completed participant cannot also use fallback")
        state["fallback"] = True
        state["fallbackAdapter"] = entry["adapter"]
        if state["observationSource"] == "unobserved":
            state["observationSource"] = "agent-reported"
        warnings.append(f"fallback for {participant} is agent-reported, not runtime-observed")
        seen.add(participant)
    return len(seen), warnings


def build_runtime_receipt(
    *,
    plan: dict[str, Any],
    lines: Iterable[str],
    observation_bindings: Any,
    codex_cli_version: str,
    execution_mode: str,
    repository_id: str,
    harness_commit: str,
    salt: bytes,
    fallbacks: Any = None,
) -> dict[str, Any]:
    """Cross-check a bounded event stream and return a privacy-safe receipt."""
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
    (
        binding_parent_raw,
        child_to_participant,
        expected_wait_attempts,
        observation_binding_fingerprint,
    ) = _normalize_observation_bindings(
        observation_bindings, participants, states, salt
    )
    parser_supported = codex_cli_version in SUPPORTED_CODEX_CLI_VERSIONS
    malformed_count = 0
    unknown_count = 0
    unknown_critical_count = 0
    child_event_count = 0
    error_count = 0
    terminal_observed = False
    terminal_status = "unknown"
    parent_thread_raw: str | None = None
    last_spawn_participant: str | None = None
    empty_wait_count = 0
    unbound_child_event_count = 0
    usage: dict[str, int] = {}

    for raw_line in lines:
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            malformed_count += 1
            continue
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            malformed_count += 1
            continue
        event_type = event["type"]
        if event_type not in KNOWN_EVENTS:
            unknown_count += 1
            if "collab" in event_type or "subagent" in event_type:
                unknown_critical_count += 1
            continue
        if event_type == "thread.started":
            thread_id = event.get("thread_id", event.get("threadId"))
            if isinstance(thread_id, str) and thread_id:
                if parent_thread_raw is not None and thread_id != parent_thread_raw:
                    unknown_critical_count += 1
                parent_thread_raw = thread_id
            continue
        if event_type in {"turn.completed", "turn.failed"}:
            terminal_observed = True
            terminal_status = "completed" if event_type == "turn.completed" else "failed"
            raw_usage = event.get("usage")
            if isinstance(raw_usage, dict):
                for key in (
                    "input_tokens",
                    "cached_input_tokens",
                    "output_tokens",
                    "reasoning_output_tokens",
                ):
                    value = raw_usage.get(key)
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        usage[key] = value
            continue
        if event_type == "error":
            error_count += 1
            error_text = event.get("message", event.get("error", ""))
            if isinstance(error_text, str) and "no thread with id" in error_text.lower():
                if last_spawn_participant in states:
                    _add_failure(states[last_spawn_participant], "missing-thread-registration")
            continue
        item = event.get("item")
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            unknown_count += 1
            continue
        item_type = item["type"]
        if item_type not in COLLAB_ITEM_TYPES:
            if item_type not in KNOWN_NONCOLLAB_ITEM_TYPES:
                unknown_count += 1
                if "collab" in item_type or "subagent" in item_type:
                    unknown_critical_count += 1
            continue
        if event_type != "item.completed":
            continue
        child_event_count += 1
        if not parser_supported:
            unknown_critical_count += 1
            continue
        action = _extract_action(item)
        status = item.get("status")
        sender = item.get("sender_thread_id")
        if action is None or not isinstance(status, str) or not isinstance(sender, str):
            unknown_critical_count += 1
            continue
        if binding_parent_raw is not None and sender != binding_parent_raw:
            unknown_critical_count += 1
            for state in states.values():
                _add_failure(state, "parent-mismatch")
            continue
        event_fingerprint = digest(_sanitized_collab_event(event_type, item, salt))
        if action in SPAWN_ACTIONS:
            receivers = _extract_thread_ids(item, "receiver_thread_ids")
            if receivers is None or len(receivers) != 1:
                unknown_critical_count += 1
                for state in states.values():
                    if not state["spawned"]:
                        _add_failure(state, "missing-child-id")
                continue
            child_id = receivers[0]
            participant = child_to_participant.get(child_id)
            if participant is None:
                unbound_child_event_count += 1
                unknown_critical_count += 1
                continue
            state = states[participant]
            last_spawn_participant = participant
            if state["spawnRequested"]:
                _add_failure(state, "duplicate-spawn")
                continue
            state["spawnRequested"] = True
            if status in SUCCESS_STATUSES:
                raw_agent_states = item.get("agents_states")
                child_state = (
                    raw_agent_states.get(child_id)
                    if isinstance(raw_agent_states, dict)
                    else None
                )
                child_status = (
                    child_state.get("status") if isinstance(child_state, dict) else None
                )
                if child_status not in ACTIVE_AGENT_STATUSES | COMPLETED_AGENT_STATUSES:
                    _add_failure(state, "invalid-spawn-agent-state")
                    continue
                state["spawned"] = True
                state["observationSource"] = "runtime-event+session-metadata"
                state["childThreadPseudonym"] = pseudonym("child", child_id, salt)
                state["spawnFingerprint"] = event_fingerprint
            elif status in FAILURE_STATUSES:
                _add_failure(state, "spawn-failed")
            else:
                _add_failure(state, "unknown-spawn-status")
        elif action in WAIT_ACTIONS:
            receivers = _extract_thread_ids(item, "receiver_thread_ids")
            if not receivers:
                empty_wait_count += 1
                unknown_critical_count += 1
                for state in states.values():
                    if not state["completed"]:
                        _add_failure(state, "empty-wait-blocked")
                continue
            raw_agent_states = item.get("agents_states")
            if not isinstance(raw_agent_states, dict):
                unknown_critical_count += 1
                continue
            for child_id in receivers:
                participant = child_to_participant.get(child_id)
                if participant is None:
                    unbound_child_event_count += 1
                    unknown_critical_count += 1
                    continue
                state = states[participant]
                if not state["spawned"]:
                    _add_failure(state, "wait-before-spawn-ack")
                    continue
                state["waitAttempts"] += 1
                if state["waitAttempts"] > MAX_WAIT_ATTEMPTS_PER_AGENT:
                    _add_failure(state, "wait-budget-exhausted")
                    continue
                raw_agent_state = raw_agent_states.get(child_id)
                agent_status = (
                    raw_agent_state.get("status")
                    if isinstance(raw_agent_state, dict)
                    else None
                )
                if agent_status is None:
                    _add_failure(state, "missing-agent-state")
                    continue
                state["observed"] = True
                state["observationSource"] = "runtime-event+session-metadata"
                if status in FAILURE_STATUSES or agent_status in FAILED_AGENT_STATUSES:
                    _add_failure(state, "wait-failed")
                elif status in SUCCESS_STATUSES and agent_status in COMPLETED_AGENT_STATUSES:
                    state["completed"] = True
                    state["completionFingerprint"] = event_fingerprint
                elif agent_status not in ACTIVE_AGENT_STATUSES:
                    _add_failure(state, "unknown-wait-status")
        elif action in FOLLOWUP_ACTIONS:
            receivers = _extract_thread_ids(item, "receiver_thread_ids")
            if not receivers:
                unknown_critical_count += 1
                continue
            for child_id in receivers:
                participant = child_to_participant.get(child_id)
                if participant is None:
                    unbound_child_event_count += 1
                    unknown_critical_count += 1
                elif not states[participant]["spawned"]:
                    _add_failure(states[participant], "followup-before-spawn-ack")
        else:
            unknown_critical_count += 1

    if (
        binding_parent_raw is not None
        and parent_thread_raw is not None
        and parent_thread_raw != binding_parent_raw
    ):
        unknown_critical_count += 1
        for state in states.values():
            _add_failure(state, "parent-mismatch")
    for participant, expected_attempts in expected_wait_attempts.items():
        if states[participant]["waitAttempts"] != expected_attempts:
            _add_failure(states[participant], "wait-metadata-mismatch")

    fallback_count, fallback_warnings = _normalize_fallbacks(fallbacks, states)
    if not parser_supported:
        for state in states.values():
            _add_failure(state, "unsupported-cli-version")
            state["spawned"] = False
            state["observed"] = False
            state["completed"] = False
            state["childThreadPseudonym"] = None
            state["spawnFingerprint"] = None
            state["completionFingerprint"] = None
            state["observationSource"] = "unobserved" if not state["fallback"] else "agent-reported"
    if malformed_count or unknown_critical_count:
        for state in states.values():
            if not state["completed"]:
                _add_failure(state, "capture-incomplete")

    agent_records = [states[name] for name in participants]
    completed_count = sum(1 for item in agent_records if item["completed"])
    successful_count = sum(
        1 for item in agent_records if item["completed"] and not item["failed"]
    )
    observed_count = sum(1 for item in agent_records if item["observed"])
    all_accounted = all(
        (item["completed"] and not item["failed"]) or item["fallback"]
        for item in agent_records
    )
    parser_compatibility = (
        "unsupported"
        if not parser_supported
        else "degraded"
        if malformed_count or unknown_count or unknown_critical_count
        else "supported"
    )
    if (
        terminal_observed
        and parent_thread_raw is not None
        and all_accounted
        and malformed_count == 0
        and unknown_critical_count == 0
    ):
        completeness = "complete"
    elif observed_count or fallback_count:
        completeness = "partial"
    else:
        completeness = "unknown"
    if successful_count:
        evidence_strength = "cross-validated-runtime"
    elif observed_count:
        evidence_strength = "runtime-observed-partial"
    elif fallback_count:
        evidence_strength = "agent-reported-fallback"
    else:
        evidence_strength = "unobserved"

    receipt: dict[str, Any] = {
        "receiptSchemaVersion": RECEIPT_SCHEMA_VERSION,
        "harness": {"version": harness_metadata.HARNESS_VERSION, "commit": harness_commit},
        "repositoryId": repository_id,
        "runtimePlanSha256": digest(plan),
        "codexCliVersion": codex_cli_version,
        "executionMode": execution_mode,
        "parentThreadPseudonym": (
            pseudonym("parent", parent_thread_raw, salt) if parent_thread_raw else None
        ),
        "observationSource": (
            "runtime-event+session-metadata"
            if observed_count
            else "agent-reported"
            if fallback_count
            else "unobserved"
        ),
        "captureCompleteness": completeness,
        "evidenceStrength": evidence_strength,
        "provesLiveSubagentExecution": bool(
            any(
                item["completed"]
                and not item["failed"]
                and item["bindingValidated"]
                for item in agent_records
            )
            and parser_supported
            and parent_thread_raw is not None
            and binding_parent_raw == parent_thread_raw
            and unknown_critical_count == 0
            and malformed_count == 0
        ),
        "parser": {
            "schemaVersion": PARSER_SCHEMA_VERSION,
            "observationSchemaVersion": OBSERVATION_SCHEMA_VERSION,
            "compatibility": parser_compatibility,
            "malformedLineCount": malformed_count,
            "unknownEventCount": unknown_count,
            "unknownCriticalEventCount": unknown_critical_count,
        },
        "runtime": {
            "terminalEventObserved": terminal_observed,
            "terminalStatus": terminal_status,
            "childEventCount": child_event_count,
            "errorCount": error_count,
            "emptyWaitCount": empty_wait_count,
            "unboundChildEventCount": unbound_child_event_count,
            "observationBindingFingerprint": observation_binding_fingerprint,
            "waitPolicy": {
                "maxAttemptsPerAgent": MAX_WAIT_ATTEMPTS_PER_AGENT,
                "maxTotalMsPerAgent": MAX_WAIT_TOTAL_MS_PER_AGENT,
            },
        },
        "agents": agent_records,
        "measurements": {
            "inputTokens": usage.get("input_tokens"),
            "cachedInputTokens": usage.get("cached_input_tokens"),
            "outputTokens": usage.get("output_tokens"),
            "reasoningOutputTokens": usage.get("reasoning_output_tokens"),
            "completedAgents": completed_count,
            "fallbackAgents": fallback_count,
            "totalWaitAttempts": sum(item["waitAttempts"] for item in agent_records),
            "totalWaitTimeMs": sum(item["waitTimeMs"] for item in agent_records),
        },
        "warnings": fallback_warnings,
    }
    _scan_forbidden_keys(receipt)
    receipt["integrity"] = {"algorithm": "sha256", "canonicalSha256": digest(receipt)}
    validate_runtime_receipt(receipt)
    return receipt


def validate_runtime_receipt(value: Any) -> dict[str, Any]:
    receipt = _require_object(value, "receipt")
    _scan_forbidden_keys(receipt)
    required = {
        "receiptSchemaVersion",
        "harness",
        "repositoryId",
        "runtimePlanSha256",
        "codexCliVersion",
        "executionMode",
        "parentThreadPseudonym",
        "observationSource",
        "captureCompleteness",
        "evidenceStrength",
        "provesLiveSubagentExecution",
        "parser",
        "runtime",
        "agents",
        "measurements",
        "warnings",
        "integrity",
    }
    if set(receipt) != required or receipt.get("receiptSchemaVersion") != RECEIPT_SCHEMA_VERSION:
        raise RuntimeReceiptError("runtime receipt fields or schema version are invalid")
    if not REPOSITORY_ID_RE.fullmatch(_require_text(receipt.get("repositoryId"), "repositoryId")):
        raise RuntimeReceiptError("repositoryId is not a valid pseudonym")
    if not HASH_RE.fullmatch(_require_text(receipt.get("runtimePlanSha256"), "runtimePlanSha256")):
        raise RuntimeReceiptError("runtimePlanSha256 must be a SHA-256 hash")
    parent = receipt.get("parentThreadPseudonym")
    if parent is not None and (
        not isinstance(parent, str)
        or not PSEUDONYM_RE.fullmatch(parent)
        or not parent.startswith("parent-")
    ):
        raise RuntimeReceiptError("parentThreadPseudonym is invalid")
    if receipt.get("executionMode") not in {"ephemeral", "persistent"}:
        raise RuntimeReceiptError("executionMode is invalid")
    if receipt.get("captureCompleteness") not in {"complete", "partial", "unknown"}:
        raise RuntimeReceiptError("captureCompleteness is invalid")
    if receipt.get("evidenceStrength") not in {
        "cross-validated-runtime",
        "runtime-observed-partial",
        "agent-reported-fallback",
        "unobserved",
    }:
        raise RuntimeReceiptError("evidenceStrength is invalid")
    if receipt.get("observationSource") not in {
        "runtime-event+session-metadata",
        "agent-reported",
        "unobserved",
    }:
        raise RuntimeReceiptError("observationSource is invalid")
    _require_text(receipt.get("codexCliVersion"), "codexCliVersion")
    harness = _require_object(receipt.get("harness"), "harness")
    if set(harness) != {"version", "commit"}:
        raise RuntimeReceiptError("harness metadata fields are invalid")
    if _require_text(harness.get("version"), "harness.version") != harness_metadata.HARNESS_VERSION:
        raise RuntimeReceiptError("harness.version is not current")
    if not re.fullmatch(r"[0-9a-f]{7,64}", _require_text(harness.get("commit"), "harness.commit")):
        raise RuntimeReceiptError("harness.commit is invalid")
    parser = _require_object(receipt.get("parser"), "parser")
    if set(parser) != {
        "schemaVersion",
        "observationSchemaVersion",
        "compatibility",
        "malformedLineCount",
        "unknownEventCount",
        "unknownCriticalEventCount",
    }:
        raise RuntimeReceiptError("parser fields are invalid")
    if (
        parser.get("schemaVersion") != PARSER_SCHEMA_VERSION
        or parser.get("observationSchemaVersion") != OBSERVATION_SCHEMA_VERSION
        or parser.get("compatibility") not in {"supported", "degraded", "unsupported"}
    ):
        raise RuntimeReceiptError("parser metadata is invalid")
    for key in ("malformedLineCount", "unknownEventCount", "unknownCriticalEventCount"):
        _integer(parser.get(key), f"parser.{key}")
    expected_parser_compatibility = (
        "unsupported"
        if receipt["codexCliVersion"] not in SUPPORTED_CODEX_CLI_VERSIONS
        else "degraded"
        if parser["malformedLineCount"]
        or parser["unknownEventCount"]
        or parser["unknownCriticalEventCount"]
        else "supported"
    )
    if parser["compatibility"] != expected_parser_compatibility:
        raise RuntimeReceiptError("parser compatibility is inconsistent with version and events")
    agents = receipt.get("agents")
    if not isinstance(agents, list):
        raise RuntimeReceiptError("agents must be an array")
    participants: set[str] = set()
    completed_count = 0
    successful_count = 0
    fallback_count = 0
    observed_count = 0
    expected_warnings: list[str] = []
    for index, raw in enumerate(agents):
        agent = _require_object(raw, f"agents[{index}]")
        if set(agent) != {
            "participant",
            "selected",
            "spawnRequested",
            "spawned",
            "observed",
            "completed",
            "failed",
            "fallback",
            "bindingValidated",
            "observationSource",
            "childThreadPseudonym",
            "spawnFingerprint",
            "completionFingerprint",
            "waitAttempts",
            "waitTimeMs",
            "failureCodes",
            "fallbackAdapter",
        }:
            raise RuntimeReceiptError(f"agents[{index}] fields are invalid")
        participant = _require_text(agent.get("participant"), f"agents[{index}].participant")
        if participant in participants:
            raise RuntimeReceiptError("receipt participants must be unique")
        participants.add(participant)
        for key in (
            "selected",
            "spawnRequested",
            "spawned",
            "observed",
            "completed",
            "failed",
            "fallback",
            "bindingValidated",
        ):
            if not isinstance(agent.get(key), bool):
                raise RuntimeReceiptError(f"agents[{index}].{key} must be boolean")
        if agent["selected"] is not True:
            raise RuntimeReceiptError("every receipt agent must have been selected")
        if agent["spawned"] and not agent["spawnRequested"]:
            raise RuntimeReceiptError("spawned requires a spawn request")
        if agent["observed"] and not agent["spawned"]:
            raise RuntimeReceiptError("observed requires a spawn acknowledgement")
        if agent["completed"] and not agent["observed"]:
            raise RuntimeReceiptError("completed requires runtime observation")
        child = agent.get("childThreadPseudonym")
        if agent["spawned"]:
            if (
                not isinstance(child, str)
                or not PSEUDONYM_RE.fullmatch(child)
                or not child.startswith("child-")
            ):
                raise RuntimeReceiptError("spawned agent requires a child pseudonym")
        elif child is not None:
            raise RuntimeReceiptError("unspawned agent cannot retain a child pseudonym")
        if agent["fallback"] and agent.get("fallbackAdapter") not in {"sequential-relay", "direct"}:
            raise RuntimeReceiptError("fallback requires a supported fallback adapter")
        if not agent["fallback"] and agent.get("fallbackAdapter") is not None:
            raise RuntimeReceiptError("non-fallback agent cannot name a fallback adapter")
        _integer(agent.get("waitAttempts"), f"agents[{index}].waitAttempts")
        _integer(agent.get("waitTimeMs"), f"agents[{index}].waitTimeMs")
        if agent["waitAttempts"] > MAX_WAIT_ATTEMPTS_PER_AGENT or agent["waitTimeMs"] > MAX_WAIT_TOTAL_MS_PER_AGENT:
            if "wait-budget-exhausted" not in agent.get("failureCodes", []):
                raise RuntimeReceiptError("exceeded wait budget must be recorded as a failure")
        if agent["completed"]:
            completed_count += 1
            if not agent["failed"]:
                successful_count += 1
        if agent["observed"]:
            observed_count += 1
        if agent["fallback"]:
            fallback_count += 1
            expected_warnings.append(
                f"fallback for {participant} is agent-reported, not runtime-observed"
            )
        if agent.get("observationSource") not in {
            "runtime-event+session-metadata",
            "agent-reported",
            "unobserved",
        }:
            raise RuntimeReceiptError("agent observationSource is invalid")
        failure_codes = _require_text_list(
            agent.get("failureCodes"), f"agents[{index}].failureCodes"
        )
        allowed_failure_codes = {
            "capture-incomplete",
            "duplicate-child-id",
            "duplicate-spawn",
            "empty-wait-blocked",
            "followup-before-spawn-ack",
            "invalid-spawn-agent-state",
            "invalid-thread-source",
            "invalid-wait-duration",
            "missing-agent-state",
            "missing-child-id",
            "missing-observation-binding",
            "missing-thread-registration",
            "parent-mismatch",
            "role-mismatch",
            "spawn-failed",
            "unknown-receiver",
            "unknown-spawn-status",
            "unknown-wait-status",
            "unsupported-cli-version",
            "wait-before-spawn-ack",
            "wait-budget-exhausted",
            "wait-failed",
            "wait-metadata-mismatch",
        }
        if set(failure_codes) - allowed_failure_codes:
            raise RuntimeReceiptError("agent failureCodes contains an unsupported value")
        for key in ("spawnFingerprint", "completionFingerprint"):
            fingerprint = agent.get(key)
            if fingerprint is not None and (
                not isinstance(fingerprint, str) or not HASH_RE.fullmatch(fingerprint)
            ):
                raise RuntimeReceiptError(f"agents[{index}].{key} is invalid")
    proves_live = receipt.get("provesLiveSubagentExecution")
    expected_live = bool(
        any(
            item["completed"] and not item["failed"] and item["bindingValidated"]
            for item in agents
        )
        and parser.get("compatibility") != "unsupported"
        and parent is not None
        and parser.get("unknownCriticalEventCount") == 0
        and parser.get("malformedLineCount") == 0
    )
    if proves_live is not expected_live:
        raise RuntimeReceiptError("provesLiveSubagentExecution is inconsistent with runtime evidence")
    runtime = _require_object(receipt.get("runtime"), "runtime")
    if set(runtime) != {
        "terminalEventObserved",
        "terminalStatus",
        "childEventCount",
        "errorCount",
        "emptyWaitCount",
        "unboundChildEventCount",
        "observationBindingFingerprint",
        "waitPolicy",
    }:
        raise RuntimeReceiptError("runtime fields are invalid")
    if not isinstance(runtime.get("terminalEventObserved"), bool) or runtime.get(
        "terminalStatus"
    ) not in {"completed", "failed", "unknown"}:
        raise RuntimeReceiptError("runtime terminal metadata is invalid")
    if runtime["terminalEventObserved"] is not (runtime["terminalStatus"] != "unknown"):
        raise RuntimeReceiptError("runtime terminal status is inconsistent")
    _integer(runtime.get("childEventCount"), "runtime.childEventCount")
    _integer(runtime.get("errorCount"), "runtime.errorCount")
    _integer(runtime.get("emptyWaitCount"), "runtime.emptyWaitCount")
    _integer(runtime.get("unboundChildEventCount"), "runtime.unboundChildEventCount")
    binding_fingerprint = runtime.get("observationBindingFingerprint")
    if binding_fingerprint is not None and (
        not isinstance(binding_fingerprint, str) or not HASH_RE.fullmatch(binding_fingerprint)
    ):
        raise RuntimeReceiptError("runtime observation binding fingerprint is invalid")
    wait_policy = _require_object(runtime.get("waitPolicy"), "runtime.waitPolicy")
    if wait_policy != {
        "maxAttemptsPerAgent": MAX_WAIT_ATTEMPTS_PER_AGENT,
        "maxTotalMsPerAgent": MAX_WAIT_TOTAL_MS_PER_AGENT,
    }:
        raise RuntimeReceiptError("runtime wait policy is invalid")
    measurements = _require_object(receipt.get("measurements"), "measurements")
    measurement_fields = {
        "inputTokens",
        "cachedInputTokens",
        "outputTokens",
        "reasoningOutputTokens",
        "completedAgents",
        "fallbackAgents",
        "totalWaitAttempts",
        "totalWaitTimeMs",
    }
    if set(measurements) != measurement_fields:
        raise RuntimeReceiptError("measurement fields are invalid")
    for key in measurement_fields:
        if measurements[key] is not None:
            _integer(measurements[key], f"measurements.{key}")
    if measurements["completedAgents"] != completed_count or measurements[
        "fallbackAgents"
    ] != fallback_count:
        raise RuntimeReceiptError("measurement agent counts are inconsistent")
    if measurements["totalWaitAttempts"] != sum(item["waitAttempts"] for item in agents) or measurements[
        "totalWaitTimeMs"
    ] != sum(item["waitTimeMs"] for item in agents):
        raise RuntimeReceiptError("measurement wait totals are inconsistent")
    warnings = _require_text_list(receipt.get("warnings"), "warnings")
    if warnings != expected_warnings:
        raise RuntimeReceiptError("receipt warnings are inconsistent with fallback evidence")
    all_accounted = all(
        (item["completed"] and not item["failed"]) or item["fallback"] for item in agents
    )
    if (
        runtime["terminalEventObserved"]
        and parent is not None
        and all_accounted
        and parser["malformedLineCount"] == 0
        and parser["unknownCriticalEventCount"] == 0
    ):
        expected_completeness = "complete"
    elif observed_count or fallback_count:
        expected_completeness = "partial"
    else:
        expected_completeness = "unknown"
    if receipt["captureCompleteness"] != expected_completeness:
        raise RuntimeReceiptError("captureCompleteness is inconsistent with runtime evidence")
    expected_source = (
        "runtime-event+session-metadata"
        if observed_count
        else "agent-reported"
        if fallback_count
        else "unobserved"
    )
    if receipt["observationSource"] != expected_source:
        raise RuntimeReceiptError("observationSource is inconsistent with runtime evidence")
    expected_strength = (
        "cross-validated-runtime"
        if successful_count
        else "runtime-observed-partial"
        if observed_count
        else "agent-reported-fallback"
        if fallback_count
        else "unobserved"
    )
    if receipt["evidenceStrength"] != expected_strength:
        raise RuntimeReceiptError("evidenceStrength is inconsistent with runtime evidence")
    integrity = _require_object(receipt.get("integrity"), "integrity")
    if integrity.get("algorithm") != "sha256" or not HASH_RE.fullmatch(
        _require_text(integrity.get("canonicalSha256"), "integrity.canonicalSha256")
    ):
        raise RuntimeReceiptError("receipt integrity metadata is invalid")
    unsigned = dict(receipt)
    unsigned.pop("integrity")
    if digest(unsigned) != integrity["canonicalSha256"]:
        raise RuntimeReceiptError("runtime receipt canonical hash does not match")
    return {
        "receiptSchemaVersion": RECEIPT_SCHEMA_VERSION,
        "valid": True,
        "captureCompleteness": receipt["captureCompleteness"],
        "evidenceStrength": receipt["evidenceStrength"],
        "provesLiveSubagentExecution": proves_live,
        "warnings": list(receipt.get("warnings", [])),
        "errors": [],
    }


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
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
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--jsonl", required=True)
    parser.add_argument("--observation-bindings", required=True)
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
        observation_bindings = json.loads(
            Path(args.observation_bindings).read_text(encoding="utf-8")
        )
        salt = Path(args.salt_file).read_bytes()
        fallbacks = (
            json.loads(Path(args.fallback_report).read_text(encoding="utf-8"))
            if args.fallback_report
            else None
        )
        receipt = build_runtime_receipt(
            plan=plan,
            lines=lines,
            observation_bindings=observation_bindings,
            codex_cli_version=args.codex_cli_version,
            execution_mode=args.execution_mode,
            repository_id=args.repository_id,
            harness_commit=args.harness_commit,
            salt=salt,
            fallbacks=fallbacks,
        )
        if args.output:
            _write_json_atomic(Path(args.output).resolve(), receipt)
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
        return 0
    except (
        OSError,
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
