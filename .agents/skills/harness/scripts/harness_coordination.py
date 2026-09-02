#!/usr/bin/env python3
"""Validate parent-facing coordination packets returned by Harness subagents."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

import harness_topology


PACKET_SCHEMA_VERSION = 1
PACKET_STATUSES = {"complete", "partial", "blocked", "failed"}
FINDING_SEVERITIES = {"low", "medium", "high", "critical"}


class CoordinationPacketError(ValueError):
    pass


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CoordinationPacketError(f"{label} must be an object")
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CoordinationPacketError(f"{label} must be non-empty text")
    return value


def _require_text_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise CoordinationPacketError(f"{label} must be an array")
    if nonempty and not value:
        raise CoordinationPacketError(f"{label} must not be empty")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise CoordinationPacketError(f"{label} entries must be non-empty strings")
    if len(value) != len(set(value)):
        raise CoordinationPacketError(f"{label} must not contain duplicates")
    return value


def _require_keys(
    value: dict[str, Any], *, required: Iterable[str], label: str
) -> None:
    required_set = set(required)
    missing = required_set - set(value)
    extra = set(value) - required_set
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if extra:
            details.append("unsupported " + ", ".join(sorted(extra)))
        raise CoordinationPacketError(f"{label} fields are invalid: {'; '.join(details)}")


def _participant_id(participant: dict[str, Any]) -> str:
    value = participant.get("agent", participant.get("runtimeParticipantId"))
    return _require_text(value, "participant identifier")


def participant_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    participants: dict[str, dict[str, Any]] = {}
    for value in plan.get("participants", []):
        participant = _require_object(value, "participant")
        participants[_participant_id(participant)] = participant
    return participants


def task_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tasks: dict[str, dict[str, Any]] = {}
    for value in plan.get("tasks", []):
        task = _require_object(value, "task")
        tasks[_require_text(task.get("id"), "task.id")] = task
    return tasks


def _validate_findings(value: Any, participants: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CoordinationPacketError("packet.findings must be an array")
    findings: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        label = f"packet.findings[{index}]"
        finding = _require_object(raw, label)
        _require_keys(
            finding,
            required=("claim", "evidenceRefs", "severity", "affectedAgents"),
            label=label,
        )
        _require_text(finding.get("claim"), f"{label}.claim")
        _require_text_list(finding.get("evidenceRefs"), f"{label}.evidenceRefs", nonempty=True)
        if finding.get("severity") not in FINDING_SEVERITIES:
            raise CoordinationPacketError(f"{label}.severity is unsupported")
        affected = _require_text_list(
            finding.get("affectedAgents"), f"{label}.affectedAgents", nonempty=True
        )
        unknown = set(affected) - participants
        if unknown:
            raise CoordinationPacketError(
                f"{label}.affectedAgents references unknown participants: {', '.join(sorted(unknown))}"
            )
        findings.append(finding)
    return findings


def _validate_challenges(
    value: Any, *, participant: str, participants: set[str]
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CoordinationPacketError("packet.challenges must be an array")
    challenges: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        label = f"packet.challenges[{index}]"
        challenge = _require_object(raw, label)
        _require_keys(
            challenge,
            required=("targetAgent", "claim", "evidenceRefs", "requestedAction"),
            label=label,
        )
        target = _require_text(challenge.get("targetAgent"), f"{label}.targetAgent")
        if target not in participants:
            raise CoordinationPacketError(f"{label}.targetAgent references an unknown participant")
        if target == participant:
            raise CoordinationPacketError(f"{label}.targetAgent must name another participant")
        _require_text(challenge.get("claim"), f"{label}.claim")
        _require_text_list(
            challenge.get("evidenceRefs"), f"{label}.evidenceRefs", nonempty=True
        )
        _require_text(challenge.get("requestedAction"), f"{label}.requestedAction")
        challenges.append(challenge)
    return challenges


def _validate_changed_paths(
    changed_paths: list[str], participant: dict[str, Any]
) -> None:
    write_scopes = participant.get("writeScopes", [])
    for index, path in enumerate(changed_paths):
        try:
            harness_topology.normalize_scope(path, f"packet.changedPaths[{index}]")
        except harness_topology.TopologyError as exc:
            raise CoordinationPacketError(str(exc)) from exc
        if not any(harness_topology.scope_contains(scope, path) for scope in write_scopes):
            raise CoordinationPacketError(
                f"packet.changedPaths[{index}] exceeds the participant write scope"
            )


def validate_coordination_packet(
    packet: Any,
    *,
    participants: dict[str, dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    item = _require_object(packet, "packet")
    _require_keys(
        item,
        required=(
            "schemaVersion",
            "status",
            "taskId",
            "participant",
            "summary",
            "findings",
            "challenges",
            "artifacts",
            "changedPaths",
            "verification",
            "incompleteWork",
            "unresolvedRisks",
        ),
        label="packet",
    )
    if item.get("schemaVersion") != PACKET_SCHEMA_VERSION:
        raise CoordinationPacketError(
            f"packet.schemaVersion must be {PACKET_SCHEMA_VERSION}"
        )
    status = item.get("status")
    if status not in PACKET_STATUSES:
        raise CoordinationPacketError("packet.status is unsupported")
    participant_id = _require_text(item.get("participant"), "packet.participant")
    if participant_id not in participants:
        raise CoordinationPacketError("packet.participant references an unknown participant")
    task_id = _require_text(item.get("taskId"), "packet.taskId")
    if task_id not in tasks:
        raise CoordinationPacketError("packet.taskId references an unknown task")
    task = tasks[task_id]
    if task.get("owner") != participant_id:
        raise CoordinationPacketError("packet participant does not own the referenced task")
    _require_text(item.get("summary"), "packet.summary")
    participant_ids = set(participants)
    findings = _validate_findings(item.get("findings"), participant_ids)
    challenges = _validate_challenges(
        item.get("challenges"),
        participant=participant_id,
        participants=participant_ids,
    )
    artifacts = _require_text_list(item.get("artifacts"), "packet.artifacts")
    changed_paths = _require_text_list(item.get("changedPaths"), "packet.changedPaths")
    verification = _require_text_list(item.get("verification"), "packet.verification")
    incomplete = _require_text_list(item.get("incompleteWork"), "packet.incompleteWork")
    risks = _require_text_list(item.get("unresolvedRisks"), "packet.unresolvedRisks")
    _validate_changed_paths(changed_paths, participants[participant_id])
    if status == "complete":
        if incomplete:
            raise CoordinationPacketError("a complete packet cannot report incomplete work")
        if not verification:
            raise CoordinationPacketError("a complete packet requires verification")
        missing_outputs = set(task.get("outputs", [])) - set(artifacts)
        if missing_outputs:
            raise CoordinationPacketError(
                "a complete packet is missing required task outputs: "
                + ", ".join(sorted(missing_outputs))
            )
        missing_verification = set(task.get("verification", [])) - set(verification)
        if missing_verification:
            raise CoordinationPacketError(
                "a complete packet is missing required task verification: "
                + ", ".join(sorted(missing_verification))
            )
    elif not incomplete:
        raise CoordinationPacketError(
            "a partial, blocked, or failed packet must describe incomplete work"
        )
    canonical = json.dumps(
        item,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schemaVersion": PACKET_SCHEMA_VERSION,
        "valid": True,
        "status": status,
        "taskId": task_id,
        "participant": participant_id,
        "findingCount": len(findings),
        "challengeCount": len(challenges),
        "artifactCount": len(artifacts),
        "changedPathCount": len(changed_paths),
        "verificationCount": len(verification),
        "unresolvedRiskCount": len(risks),
        "packetSha256": hashlib.sha256(canonical).hexdigest(),
        "provesLiveSubagentExecution": False,
        "warnings": [],
        "errors": [],
    }
