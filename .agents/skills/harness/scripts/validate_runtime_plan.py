#!/usr/bin/env python3
"""Validate an ephemeral Harness runtime execution plan without writing state."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

import harness_metadata
import harness_state
import harness_teamplay
import harness_topology


RUNTIME_PLAN_SCHEMA_VERSION = 1
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
RUNTIME_SPECIFIC_TOKENS = (
    "TeamCreate",
    "SendMessage",
    "TaskCreate",
    "spawn_agent",
    "collaboration.send_message",
)
FORBIDDEN_PERSISTENT_KEYS = {
    "currentTask",
    "runtimeExecutionPlan",
    "runtimeMessages",
    "runtimeParticipants",
    "runtimePlan",
    "runtimeRole",
    "runtimeTasks",
    "runtimeTeam",
    "taskExecution",
    "taskExecutionClass",
}
ABSOLUTE_PATH_KEYS = {"absolutePath", "cwd", "repositoryPath", "repositoryRoot", "root"}
ADAPTERS = {
    "runtime-probed",
    "codex-subagent-relay",
    "sequential-relay",
    # v6.5 aliases remain accepted for ephemeral-plan compatibility.
    "native-multi-agent",
    "worktree-team",
    "delegated-fan-out",
    "leader-relay",
    "sequential",
    "direct",
}
RETENTION_MODES = {"ephemeral", "redacted", "full-audit"}


class RuntimePlanError(ValueError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def manifest_sha256(manifest_path: Path) -> str:
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def topology_sha256(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(manifest.get("topology"))).hexdigest()


def default_retention() -> dict[str, Any]:
    return {
        "mode": "ephemeral",
        "storeRawMessages": False,
        "storeRawArtifacts": False,
        "storeHashes": True,
    }


def frozen_handoff_is_current(handoff: dict[str, Any], observed_sha256: str) -> bool:
    expected = handoff.get("frozenSha256")
    return bool(HASH_RE.fullmatch(observed_sha256)) and expected == observed_sha256


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimePlanError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise RuntimePlanError(f"{label} must be an array")
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimePlanError(f"{label} must be non-empty text")
    return value


def _require_id(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if not harness_topology.ID_RE.fullmatch(text):
        raise RuntimePlanError(f"{label} must be a kebab-case identifier")
    return text


def _require_integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise RuntimePlanError(f"{label} must be an integer >= {minimum}")
    return value


def _require_boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimePlanError(f"{label} must be a boolean")
    return value


def _require_text_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    items = _require_list(value, label)
    if nonempty and not items:
        raise RuntimePlanError(f"{label} must not be empty")
    if not all(isinstance(item, str) and item.strip() for item in items):
        raise RuntimePlanError(f"{label} entries must be non-empty strings")
    if len(items) != len(set(items)):
        raise RuntimePlanError(f"{label} must not contain duplicates")
    return items


def _require_keys(
    value: dict[str, Any],
    *,
    required: Iterable[str],
    optional: Iterable[str] = (),
    label: str,
) -> None:
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = required_set - set(value)
    extra = set(value) - allowed
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if extra:
            details.append("unsupported " + ", ".join(sorted(extra)))
        raise RuntimePlanError(f"{label} fields are invalid: {'; '.join(details)}")


def _walk(value: Any, path: str = "plan") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")


def _reject_runtime_specific_syntax(plan: dict[str, Any]) -> None:
    for path, value in _walk(plan):
        if isinstance(value, str) and any(token in value for token in RUNTIME_SPECIFIC_TOKENS):
            raise RuntimePlanError(f"{path} contains runtime-specific tool syntax")
    for path, value in _walk(plan):
        if not isinstance(value, dict):
            continue
        forbidden = ABSOLUTE_PATH_KEYS.intersection(value)
        if forbidden:
            raise RuntimePlanError(
                f"{path} stores an absolute repository-path field: {', '.join(sorted(forbidden))}"
            )


def _reject_persistent_runtime_state(manifest: dict[str, Any]) -> None:
    for path, value in _walk(manifest, "manifest"):
        if isinstance(value, dict):
            forbidden = FORBIDDEN_PERSISTENT_KEYS.intersection(value)
            if forbidden:
                raise RuntimePlanError(
                    f"{path} contains runtime-only persistent fields: {', '.join(sorted(forbidden))}"
                )


def _normalize_scope(value: Any, label: str) -> str:
    try:
        harness_topology.normalize_scope(value, label)
    except harness_topology.TopologyError as exc:
        raise RuntimePlanError(str(exc)) from exc
    return str(value)


def _scope_is_contained(scope: str, permitted: Iterable[str]) -> bool:
    return any(harness_topology.scope_contains(container, scope) for container in permitted)


def _participant_id(participant: dict[str, Any], *, provisional: bool, label: str) -> str:
    agent = participant.get("agent")
    runtime_id = participant.get("runtimeParticipantId")
    if (agent is None) == (runtime_id is None):
        raise RuntimePlanError(f"{label} must contain exactly one of agent or runtimeParticipantId")
    if runtime_id is not None:
        if not provisional:
            raise RuntimePlanError(f"{label}.runtimeParticipantId is allowed only for a provisional plan")
        return _require_id(runtime_id, f"{label}.runtimeParticipantId")
    return _require_text(agent, f"{label}.agent")


def _has_dependency_path(tasks: dict[str, dict[str, Any]], source: str, target: str) -> bool:
    pending = list(tasks[target]["dependsOn"])
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current == source:
            return True
        if current not in seen:
            seen.add(current)
            pending.extend(tasks[current]["dependsOn"])
    return False


def _validate_acyclic(tasks: dict[str, dict[str, Any]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in visiting:
            raise RuntimePlanError("runtime task dependency graph must be acyclic")
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in tasks[identifier]["dependsOn"]:
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in tasks:
        visit(identifier)


def validate_message(
    message: Any,
    *,
    participants: set[str],
    task_ids: set[str],
    leader: str,
    max_rounds: int,
) -> dict[str, Any]:
    item = _require_object(message, "message")
    forbidden_scope_keys = {"grantWriteScopes", "newOwner", "writeScopes"}.intersection(item)
    if forbidden_scope_keys:
        raise RuntimePlanError("peer messages cannot expand write scope or reassign ownership")
    message_type = item.get("type")
    if message_type not in harness_teamplay.MESSAGE_TYPES:
        raise RuntimePlanError("message.type is unsupported")
    task_id = _require_id(item.get("taskId"), "message.taskId")
    if task_id not in task_ids:
        raise RuntimePlanError("message.taskId references an unknown task")
    sender = _require_text(item.get("from"), "message.from")
    target = _require_text(item.get("to"), "message.to")
    if sender not in participants:
        raise RuntimePlanError("message.from references an unknown participant")
    if target == "broadcast":
        if sender != leader:
            raise RuntimePlanError("broadcast is leader-only")
    elif target not in participants:
        raise RuntimePlanError("message.to references an unknown participant")
    round_number = _require_integer(item.get("round"), "message.round", minimum=1)
    if round_number > max_rounds:
        raise RuntimePlanError("message exceeds the communication round budget")

    if message_type == "challenge":
        _require_text(item.get("claim"), "challenge.claim")
        _require_text_list(item.get("evidenceRefs"), "challenge.evidenceRefs", nonempty=True)
        scopes = _require_text_list(item.get("affectedScopes"), "challenge.affectedScopes", nonempty=True)
        for index, scope in enumerate(scopes):
            _normalize_scope(scope, f"challenge.affectedScopes[{index}]")
        _require_text(item.get("requestedAction"), "challenge.requestedAction")
    elif message_type == "finding":
        _require_text(item.get("claim"), "finding.claim")
        _require_text_list(item.get("evidenceRefs"), "finding.evidenceRefs", nonempty=True)
        _require_text(item.get("downstreamImpact"), "finding.downstreamImpact")
    elif message_type == "request":
        _require_text(item.get("requestedAction"), "request.requestedAction")
    elif message_type == "handoff":
        _require_text_list(item.get("artifacts"), "handoff.artifacts", nonempty=True)
        _require_text_list(item.get("verification"), "handoff.verification", nonempty=True)
        if not isinstance(item.get("frozenSha256"), str) or not HASH_RE.fullmatch(
            item["frozenSha256"]
        ):
            raise RuntimePlanError("handoff.frozenSha256 must be a SHA-256 hash")
    elif message_type == "complete":
        _require_text_list(item.get("artifacts"), "complete.artifacts", nonempty=True)
        _require_text_list(item.get("verification"), "complete.verification", nonempty=True)
        _require_text_list(item.get("incomplete"), "complete.incomplete")
        _require_text_list(item.get("unresolvedRisks"), "complete.unresolvedRisks")
        if not isinstance(item.get("frozenSha256"), str) or not HASH_RE.fullmatch(
            item["frozenSha256"]
        ):
            raise RuntimePlanError("complete.frozenSha256 must be a SHA-256 hash")
    return item


def validate_message_batch(
    messages: Any,
    *,
    participants: set[str],
    task_ids: set[str],
    leader: str,
    max_rounds: int,
    max_messages_per_agent: int,
) -> None:
    counts: dict[str, int] = {}
    for message in _require_list(messages, "messages"):
        item = validate_message(
            message,
            participants=participants,
            task_ids=task_ids,
            leader=leader,
            max_rounds=max_rounds,
        )
        sender = item["from"]
        counts[sender] = counts.get(sender, 0) + 1
        if counts[sender] > max_messages_per_agent:
            raise RuntimePlanError(f"participant {sender!r} exceeds maxMessagesPerAgent")


class RuntimePlanValidator:
    def __init__(self, root: Path, plan: Any):
        self.root = root.resolve()
        self.plan = _require_object(plan, "plan")
        self.manifest_path = self.root / ".harness" / "manifest.json"
        self.manifest: dict[str, Any] = {}
        self.manifest_bytes = b""

    def _load_manifest(self) -> None:
        harness_directory = self.root / ".harness"
        if harness_directory.is_symlink() or self.manifest_path.is_symlink():
            raise RuntimePlanError("runtime-plan control paths must not be symbolic links")
        try:
            self.manifest_bytes = self.manifest_path.read_bytes()
            manifest = json.loads(self.manifest_bytes.decode("utf-8"))
        except FileNotFoundError as exc:
            raise RuntimePlanError("missing .harness/manifest.json") from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimePlanError(f"invalid manifest: {exc}") from exc
        if not isinstance(manifest, dict):
            raise RuntimePlanError("manifest root must be an object")
        if not self.manifest_path.is_file():
            raise RuntimePlanError("missing .harness/manifest.json")
        if manifest.get("schemaVersion") != harness_metadata.MANIFEST_SCHEMA_VERSION:
            raise RuntimePlanError(
                f"manifest schemaVersion must be {harness_metadata.MANIFEST_SCHEMA_VERSION}"
            )
        try:
            harness_state.validate_runtime(manifest)
            harness_topology.validate_contract(
                manifest.get("topology"), manifest.get("capabilityPolicies")
            )
        except (harness_state.StateError, harness_topology.TopologyError) as exc:
            raise RuntimePlanError(f"invalid persistent manifest: {exc}") from exc
        _reject_persistent_runtime_state(manifest)
        self.manifest = manifest

    def _validate_source(self) -> None:
        source = _require_object(self.plan.get("source"), "source")
        _require_keys(
            source,
            required=("manifestSha256", "topologySha256"),
            label="source",
        )
        manifest_hash = source.get("manifestSha256")
        topology_hash = source.get("topologySha256")
        if not isinstance(manifest_hash, str) or not HASH_RE.fullmatch(manifest_hash):
            raise RuntimePlanError("source.manifestSha256 must be a SHA-256 hash")
        if not isinstance(topology_hash, str) or not HASH_RE.fullmatch(topology_hash):
            raise RuntimePlanError("source.topologySha256 must be a SHA-256 hash")
        if manifest_hash != hashlib.sha256(self.manifest_bytes).hexdigest():
            raise RuntimePlanError("runtime plan is stale: manifest hash does not match")
        if topology_hash != topology_sha256(self.manifest):
            raise RuntimePlanError("runtime plan is stale: topology hash does not match")

    def _validate_task_contract(self) -> None:
        task = _require_object(self.plan.get("task"), "task")
        _require_keys(
            task,
            required=("summary", "completionCriteria", "criticality"),
            label="task",
        )
        _require_text(task.get("summary"), "task.summary")
        _require_text_list(
            task.get("completionCriteria"), "task.completionCriteria", nonempty=True
        )
        if task.get("criticality") not in {"low", "medium", "high"}:
            raise RuntimePlanError("task.criticality is unsupported")

    def _validate_execution(self) -> tuple[dict[str, Any], bool]:
        execution = _require_object(self.plan.get("execution"), "execution")
        _require_keys(
            execution,
            required=("class", "pattern", "adapter", "capabilityPolicyRef", "retention"),
            optional=("evidenceStatus", "persistenceAllowed", "leader"),
            label="execution",
        )
        execution_class = execution.get("class")
        if execution_class not in harness_teamplay.EXECUTION_CLASSES:
            raise RuntimePlanError("execution.class is unsupported")
        pattern = execution.get("pattern")
        if execution_class == "direct":
            if pattern is not None:
                raise RuntimePlanError("direct execution must not declare a collaboration pattern")
        elif pattern not in harness_teamplay.COLLABORATION_PATTERNS:
            raise RuntimePlanError("execution.pattern is unsupported")
        if execution.get("adapter") not in ADAPTERS:
            raise RuntimePlanError("execution.adapter is unsupported")
        if execution.get("retention") not in RETENTION_MODES:
            raise RuntimePlanError("execution.retention is unsupported")
        policies = {
            item.get("id"): item
            for item in self.manifest.get("capabilityPolicies", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        policy_ref = _require_id(execution.get("capabilityPolicyRef"), "execution.capabilityPolicyRef")
        if policy_ref not in policies:
            raise RuntimePlanError("execution.capabilityPolicyRef references an unknown policy")
        policy = policies[policy_ref]
        if execution.get("adapter") in {"native-multi-agent", "codex-subagent-relay"}:
            if policy.get("probe", {}).get("mode") != "runtime-check":
                raise RuntimePlanError("subagent adapter requires a runtime capability probe")
        fallback = policy.get("fallback")
        required_capabilities = policy.get("requiredCapabilities", [])
        if required_capabilities or policy.get("preferredRuntimeMapping") == "runtime-native":
            if not isinstance(fallback, dict) or set(fallback.get("preserves", [])) != set(
                harness_teamplay.PRESERVED_CONTRACTS
            ):
                raise RuntimePlanError("capability fallback must preserve input, output, and verification")
        provisional = execution.get("evidenceStatus") == "provisional"
        if provisional:
            if execution.get("persistenceAllowed") is not False:
                raise RuntimePlanError("provisional runtime execution must set persistenceAllowed to false")
        elif "persistenceAllowed" in execution:
            raise RuntimePlanError("persistenceAllowed is only valid for provisional runtime execution")
        return execution, provisional

    def _validate_participants(
        self, *, provisional: bool
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        persistent_agents = {
            item.get("name"): item
            for item in self.manifest["topology"].get("agents", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        persistent_boundaries = {
            item.get("id")
            for item in self.manifest["topology"].get("boundaries", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        participants: dict[str, dict[str, Any]] = {}
        for index, value in enumerate(_require_list(self.plan.get("participants"), "participants")):
            label = f"participants[{index}]"
            participant = _require_object(value, label)
            _require_keys(
                participant,
                required=("runtimeRole", "boundaryRefs", "readScopes", "writeScopes"),
                optional=("agent", "runtimeParticipantId", "isolation"),
                label=label,
            )
            identifier = _participant_id(participant, provisional=provisional, label=label)
            if identifier in participants:
                raise RuntimePlanError(f"duplicate runtime participant: {identifier}")
            persistent = persistent_agents.get(identifier)
            if participant.get("agent") is not None and persistent is None:
                raise RuntimePlanError(f"{label}.agent references an unknown persistent agent")
            if participant.get("runtimeRole") not in harness_teamplay.RUNTIME_ROLES:
                raise RuntimePlanError(f"{label}.runtimeRole is unsupported")
            boundary_refs = _require_text_list(participant.get("boundaryRefs"), f"{label}.boundaryRefs")
            if set(boundary_refs) - persistent_boundaries:
                raise RuntimePlanError(f"{label}.boundaryRefs references an unknown boundary")
            if persistent is not None and set(boundary_refs) - set(persistent.get("boundaryRefs", [])):
                raise RuntimePlanError(f"{label}.boundaryRefs exceeds the persistent agent boundary")
            read_scopes = _require_text_list(participant.get("readScopes"), f"{label}.readScopes")
            write_scopes = _require_text_list(participant.get("writeScopes"), f"{label}.writeScopes")
            for scope_index, scope in enumerate(read_scopes):
                _normalize_scope(scope, f"{label}.readScopes[{scope_index}]")
            for scope_index, scope in enumerate(write_scopes):
                _normalize_scope(scope, f"{label}.writeScopes[{scope_index}]")
            if persistent is not None:
                accesses = persistent.get("fileAccess", [])
                permitted_reads = [item["scope"] for item in accesses if isinstance(item, dict)]
                permitted_writes = [
                    item["scope"]
                    for item in accesses
                    if isinstance(item, dict) and item.get("mode") == "write"
                ]
                if any(not _scope_is_contained(scope, permitted_reads) for scope in read_scopes):
                    raise RuntimePlanError(f"{label}.readScopes exceeds persistent file access")
                if any(not _scope_is_contained(scope, permitted_writes) for scope in write_scopes):
                    raise RuntimePlanError(f"{label}.writeScopes exceeds persistent file access")
            if participant.get("runtimeRole") == "reviewer" and write_scopes:
                raise RuntimePlanError("reviewer runtime roles must be read-only")
            if write_scopes and participant.get("isolation") not in {"worktree", "equivalent"}:
                raise RuntimePlanError("runtime writers require an isolated worktree or equivalent")
            if not write_scopes and participant.get("isolation") is not None:
                if participant.get("isolation") not in {"read-only", "frozen-diff"}:
                    raise RuntimePlanError("read-only participants use read-only or frozen-diff isolation")
            participants[identifier] = participant
        return participants, persistent_agents

    def _validate_tasks(
        self, participants: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        tasks: dict[str, dict[str, Any]] = {}
        output_owners: dict[str, str] = {}
        for index, value in enumerate(_require_list(self.plan.get("tasks"), "tasks")):
            label = f"tasks[{index}]"
            task = _require_object(value, label)
            _require_keys(
                task,
                required=("id", "owner", "dependsOn", "inputs", "outputs", "required", "verification"),
                label=label,
            )
            identifier = _require_id(task.get("id"), f"{label}.id")
            if identifier in tasks:
                raise RuntimePlanError(f"duplicate runtime task id: {identifier}")
            owner = _require_text(task.get("owner"), f"{label}.owner")
            if owner not in participants:
                raise RuntimePlanError(f"{label}.owner references an unknown participant")
            task["dependsOn"] = _require_text_list(task.get("dependsOn"), f"{label}.dependsOn")
            task["inputs"] = _require_text_list(task.get("inputs"), f"{label}.inputs")
            task["outputs"] = _require_text_list(task.get("outputs"), f"{label}.outputs")
            required = _require_boolean(task.get("required"), f"{label}.required")
            verification = _require_text_list(task.get("verification"), f"{label}.verification")
            if required and (not task["outputs"] or not verification):
                raise RuntimePlanError("every required task needs an output and verification")
            for output in task["outputs"]:
                if output in output_owners:
                    raise RuntimePlanError(
                        f"runtime output {output!r} has more than one owner"
                    )
                output_owners[output] = owner
            tasks[identifier] = task
        for identifier, task in tasks.items():
            unknown = set(task["dependsOn"]) - set(tasks)
            if unknown or identifier in task["dependsOn"]:
                raise RuntimePlanError(f"task {identifier!r} has an invalid dependency")
        _validate_acyclic(tasks)
        for identifier, task in tasks.items():
            upstream_outputs = {
                output
                for upstream_id, upstream in tasks.items()
                if _has_dependency_path(tasks, upstream_id, identifier)
                for output in upstream["outputs"]
            }
            read_scopes = participants[task["owner"]]["readScopes"]
            for input_value in task["inputs"]:
                if input_value in upstream_outputs:
                    continue
                _normalize_scope(input_value, f"task {identifier!r} repository input")
                if not _scope_is_contained(input_value, read_scopes):
                    raise RuntimePlanError(
                        f"task {identifier!r} input is neither an upstream output nor an owner read scope"
                    )
        return tasks

    def _validate_handoffs(
        self,
        participants: dict[str, dict[str, Any]],
        tasks: dict[str, dict[str, Any]],
    ) -> None:
        handoffs: list[dict[str, Any]] = []
        for index, value in enumerate(_require_list(self.plan.get("handoffs", []), "handoffs")):
            label = f"handoffs[{index}]"
            handoff = _require_object(value, label)
            _require_keys(
                handoff,
                required=("fromTask", "toTask", "scope", "frozenSha256", "verification"),
                label=label,
            )
            source = _require_id(handoff.get("fromTask"), f"{label}.fromTask")
            target = _require_id(handoff.get("toTask"), f"{label}.toTask")
            if source not in tasks or target not in tasks or not _has_dependency_path(tasks, source, target):
                raise RuntimePlanError(f"{label} must follow the task dependency graph")
            handoff["scope"] = _normalize_scope(handoff.get("scope"), f"{label}.scope")
            if not isinstance(handoff.get("frozenSha256"), str) or not HASH_RE.fullmatch(
                handoff["frozenSha256"]
            ):
                raise RuntimePlanError(f"{label}.frozenSha256 must be a SHA-256 hash")
            _require_text(handoff.get("verification"), f"{label}.verification")
            handoffs.append(handoff)

        task_items = list(tasks.items())
        for index, (first_id, first_task) in enumerate(task_items):
            first_participant = participants[first_task["owner"]]
            for second_id, second_task in task_items[index + 1 :]:
                second_participant = participants[second_task["owner"]]
                if first_task["owner"] == second_task["owner"]:
                    continue
                for first_scope in first_participant["writeScopes"]:
                    for second_scope in second_participant["writeScopes"]:
                        if not harness_topology.scopes_overlap(first_scope, second_scope):
                            continue
                        if _has_dependency_path(tasks, first_id, second_id):
                            source, target = first_id, second_id
                        elif _has_dependency_path(tasks, second_id, first_id):
                            source, target = second_id, first_id
                        else:
                            raise RuntimePlanError("concurrent runtime writers have overlapping scopes")
                        shared = harness_topology.scope_intersection(first_scope, second_scope)
                        if shared is None or not any(
                            item["fromTask"] == source
                            and item["toTask"] == target
                            and harness_topology.scopes_equivalent(item["scope"], shared)
                            for item in handoffs
                        ):
                            raise RuntimePlanError(
                                "ordered overlapping runtime writers require a complete verified handoff"
                            )

    def _validate_communication(
        self,
        execution: dict[str, Any],
        participants: dict[str, dict[str, Any]],
        tasks: dict[str, dict[str, Any]],
    ) -> None:
        communication = _require_object(self.plan.get("communication"), "communication")
        _require_keys(
            communication,
            required=(
                "allowedTypes",
                "maxRounds",
                "maxMessagesPerAgent",
                "broadcastPolicy",
                "challengeRequiresEvidence",
            ),
            label="communication",
        )
        allowed_types = set(
            _require_text_list(communication.get("allowedTypes"), "communication.allowedTypes")
        )
        if allowed_types != harness_teamplay.MESSAGE_TYPES:
            raise RuntimePlanError("communication.allowedTypes must contain the complete semantic set")
        max_rounds = _require_integer(communication.get("maxRounds"), "communication.maxRounds")
        max_messages = _require_integer(
            communication.get("maxMessagesPerAgent"), "communication.maxMessagesPerAgent"
        )
        if execution["class"] == "coordinated" and (max_rounds < 1 or max_messages < 1):
            raise RuntimePlanError("coordinated execution requires finite positive communication budgets")
        if communication.get("broadcastPolicy") != "leader-only":
            raise RuntimePlanError("communication.broadcastPolicy must be leader-only")
        if communication.get("challengeRequiresEvidence") is not True:
            raise RuntimePlanError("communication challenges must require evidence")
        leader = execution.get("leader")
        if leader is None:
            leader = next(
                (
                    identifier
                    for identifier, participant in participants.items()
                    if participant.get("runtimeRole") in {"supervisor", "integrator"}
                ),
                next(iter(participants), "primary"),
            )
        elif leader not in participants:
            raise RuntimePlanError("execution.leader references an unknown participant")
        if "messages" in self.plan:
            validate_message_batch(
                self.plan["messages"],
                participants=set(participants),
                task_ids=set(tasks),
                leader=leader,
                max_rounds=max_rounds,
                max_messages_per_agent=max_messages,
            )

    def _validate_stopping(self, execution: dict[str, Any]) -> None:
        stopping = _require_object(self.plan.get("stopping"), "stopping")
        _require_keys(
            stopping,
            required=(
                "maxReassignments",
                "failOnMissingRequiredArtifact",
                "failOnWriteScopeViolation",
                "failOnUnresolvedCriticalChallenge",
            ),
            label="stopping",
        )
        max_reassignments = _require_integer(
            stopping.get("maxReassignments"), "stopping.maxReassignments"
        )
        if execution["class"] == "coordinated" and max_reassignments > 3:
            raise RuntimePlanError("coordinated reassignment budget must be finite and at most 3")
        for key in (
            "failOnMissingRequiredArtifact",
            "failOnWriteScopeViolation",
            "failOnUnresolvedCriticalChallenge",
        ):
            if _require_boolean(stopping.get(key), f"stopping.{key}") is not True:
                raise RuntimePlanError(f"stopping.{key} must be true")

    def _validate_retention(self, execution: dict[str, Any]) -> None:
        retention = _require_object(self.plan.get("retention"), "retention")
        mode = retention.get("mode")
        if mode != execution.get("retention"):
            raise RuntimePlanError("execution.retention must match retention.mode")
        common = {"mode", "storeRawMessages", "storeRawArtifacts", "storeHashes"}
        full_audit = {"explicitUserOptIn", "storageLocation", "retentionDuration", "purgeMethod"}
        _require_keys(
            retention,
            required=common,
            optional=full_audit if mode == "full-audit" else (),
            label="retention",
        )
        if mode not in RETENTION_MODES:
            raise RuntimePlanError("retention.mode is unsupported")
        store_messages = _require_boolean(retention.get("storeRawMessages"), "retention.storeRawMessages")
        store_artifacts = _require_boolean(retention.get("storeRawArtifacts"), "retention.storeRawArtifacts")
        _require_boolean(retention.get("storeHashes"), "retention.storeHashes")
        if mode in {"ephemeral", "redacted"} and (store_messages or store_artifacts):
            raise RuntimePlanError(f"{mode} retention cannot store raw messages or artifacts")
        if mode == "full-audit":
            if retention.get("explicitUserOptIn") is not True:
                raise RuntimePlanError("full-audit retention requires explicit user opt-in")
            for key in ("storageLocation", "retentionDuration", "purgeMethod"):
                _require_text(retention.get(key), f"retention.{key}")

    def validate(self) -> dict[str, Any]:
        if not self.root.is_dir():
            raise RuntimePlanError(f"repository root is not a directory: {self.root}")
        _require_keys(
            self.plan,
            required=(
                "schemaVersion",
                "source",
                "task",
                "execution",
                "participants",
                "tasks",
                "communication",
                "stopping",
                "retention",
            ),
            optional=("handoffs", "messages"),
            label="plan",
        )
        if self.plan.get("schemaVersion") != RUNTIME_PLAN_SCHEMA_VERSION:
            raise RuntimePlanError(
                f"runtime plan schemaVersion must be {RUNTIME_PLAN_SCHEMA_VERSION}"
            )
        _reject_runtime_specific_syntax(self.plan)
        self._load_manifest()
        self._validate_source()
        self._validate_task_contract()
        execution, provisional = self._validate_execution()
        participants, _ = self._validate_participants(provisional=provisional)
        tasks = self._validate_tasks(participants)
        if execution["class"] == "coordinated" and (
            len(participants) < 2 or len(tasks) < 2
        ):
            raise RuntimePlanError(
                "coordinated execution requires at least two participants and two tasks"
            )
        self._validate_handoffs(participants, tasks)
        self._validate_communication(execution, participants, tasks)
        self._validate_stopping(execution)
        self._validate_retention(execution)
        if self.manifest_path.read_bytes() != self.manifest_bytes:
            raise RuntimePlanError("manifest changed during runtime-plan validation")
        return {
            "schemaVersion": RUNTIME_PLAN_SCHEMA_VERSION,
            "valid": True,
            "executionClass": execution["class"],
            "pattern": execution["pattern"],
            "participants": len(participants),
            "tasks": len(tasks),
            "retention": self.plan["retention"]["mode"],
            "warnings": [],
            "errors": [],
        }


def validate_runtime_plan(root: Path, plan: Any) -> dict[str, Any]:
    return RuntimePlanValidator(root, plan).validate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--plan", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        report = validate_runtime_plan(root, plan)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, RuntimePlanError) as exc:
        print(
            json.dumps(
                {
                    "schemaVersion": RUNTIME_PLAN_SCHEMA_VERSION,
                    "valid": False,
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
