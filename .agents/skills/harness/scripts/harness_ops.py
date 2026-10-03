#!/usr/bin/env python3
"""Record privacy-safe, task-scoped Harness operations evidence from Codex hooks."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import harness_eval_store
import harness_eval_types as types
import harness_metadata
import harness_state


OPS_EVENT_SCHEMA_VERSION = harness_metadata.OPERATIONS_EVENT_SCHEMA_VERSION
MAX_HOOK_INPUT_BYTES = 1024 * 1024
MAX_EVENTS_PER_REPOSITORY = 4096
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_EVENT_BYTES = 16 * 1024
WORK_ITEM_RE = re.compile(r"^work-item:[0-9a-f]{32}$")
SESSION_RE = re.compile(r"^session:[0-9a-f]{32}$")
TURN_RE = re.compile(r"^turn:[0-9a-f]{32}$")
AGENT_RE = re.compile(r"^agent:[0-9a-f]{32}$")
AGENT_INSTANCE_RE = re.compile(r"^agent-instance:[0-9a-f]{32}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

HOOK_EVENTS = {
    "UserPromptSubmit",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "SessionEnd",
}
RELATIONS = {
    "unclassified",
    "new-task",
    "acceptance",
    "refinement",
    "correction",
    "follow-up",
    "reopen",
    "cancel",
}
OUTCOMES = {
    "unknown",
    "verified",
    "provisionally-accepted",
    "user-accepted",
    "needs-revision",
    "failed",
    "abandoned",
}
VERIFICATION_STATES = {"unknown", "passed", "failed", "not-applicable"}
EVIDENCE_SOURCES = {"agent-reported", "user-reported", "verification", "hook-observed"}
EXECUTION_CLASSES = {"unknown", "direct", "delegated", "coordinated"}
AGENT_SELECTIONS = {
    "unknown",
    "not-applicable",
    "appropriate",
    "questionable",
    "inappropriate",
}
TASK_CATEGORIES = set(types.TASK_CATEGORIES)


class OperationsError(ValueError):
    pass


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise OperationsError(f"{label} must be non-empty text")
    return value


def _find_harness_root(cwd: Path) -> Path | None:
    try:
        current = cwd.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not current.is_dir():
        return None
    for candidate in (current, *current.parents):
        manifest_path = candidate / ".harness" / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(manifest, dict):
            return None
        generator = manifest.get("generator")
        workspace = manifest.get("workspace")
        if not (
            manifest.get("schemaVersion") == harness_metadata.MANIFEST_SCHEMA_VERSION
            and isinstance(generator, dict)
            and generator.get("name") == "Harness"
            and generator.get("runtime") == "codex"
            and isinstance(workspace, dict)
            and workspace.get("scope") == "project-local"
        ):
            return None
        return candidate
    return None


def _events_root(store: harness_eval_store.EvaluationStore, repository_id: str) -> Path:
    return store.checked(store.repository_root(repository_id) / "operations" / "events")


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    data = _canonical_text(value).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if os.name != "nt":
        os.chmod(path, 0o600)
    harness_state.sync_directory(path.parent)


def _seal(event: dict[str, Any]) -> dict[str, Any]:
    return types.seal_record(event)


def validate_event(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OperationsError("operations event must be an object")
    required = {
        "schemaVersion",
        "eventId",
        "repositoryId",
        "harnessVersion",
        "createdAt",
        "eventType",
        "sessionRef",
        "turnRef",
        "workItemRef",
        "payload",
        "privacy",
        "integrity",
    }
    if set(value) != required or value.get("schemaVersion") != OPS_EVENT_SCHEMA_VERSION:
        raise OperationsError("operations event fields or schema version are invalid")
    try:
        if str(uuid.UUID(_require_text(value.get("eventId"), "eventId"))) != value["eventId"]:
            raise OperationsError("eventId must use canonical UUID form")
        uuid.UUID(_require_text(value.get("repositoryId"), "repositoryId"))
        datetime.fromisoformat(_require_text(value.get("createdAt"), "createdAt").replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise OperationsError("operations event identity or timestamp is invalid") from exc
    if not isinstance(value.get("harnessVersion"), str):
        raise OperationsError("harnessVersion must be text")
    event_type = value.get("eventType")
    if event_type not in HOOK_EVENTS | {"Annotation"}:
        raise OperationsError("operations eventType is unsupported")
    if not SESSION_RE.fullmatch(_require_text(value.get("sessionRef"), "sessionRef")):
        raise OperationsError("sessionRef is invalid")
    turn_ref = value.get("turnRef")
    work_item_ref = value.get("workItemRef")
    if event_type == "SessionEnd":
        if turn_ref is not None or work_item_ref is not None:
            raise OperationsError("SessionEnd must not retain a turn or work-item reference")
    else:
        if not isinstance(turn_ref, str) or not TURN_RE.fullmatch(turn_ref):
            raise OperationsError("turnRef is invalid")
        if not isinstance(work_item_ref, str) or not WORK_ITEM_RE.fullmatch(work_item_ref):
            raise OperationsError("workItemRef is invalid")
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise OperationsError("operations payload must be an object")
    _validate_payload(event_type, payload)
    privacy = value.get("privacy")
    expected_privacy = {
        "rawPromptStored": False,
        "rawResponseStored": False,
        "rawTranscriptStored": False,
        "rawAgentNameStored": False,
        "absolutePathStored": False,
    }
    if privacy != expected_privacy:
        raise OperationsError("operations privacy contract is invalid")
    try:
        types.verify_integrity(value)
    except types.EvaluationError as exc:
        raise OperationsError(str(exc)) from exc
    return value


def _validate_payload(event_type: str, payload: dict[str, Any]) -> None:
    if event_type == "UserPromptSubmit":
        if set(payload) != {"promptFingerprint"} or not HASH_RE.fullmatch(
            _require_text(payload.get("promptFingerprint"), "promptFingerprint")
        ):
            raise OperationsError("UserPromptSubmit payload is invalid")
        return
    if event_type in {"SubagentStart", "SubagentStop"}:
        if set(payload) != {"agentRef", "agentInstanceRef"}:
            raise OperationsError(f"{event_type} payload fields are invalid")
        if not AGENT_RE.fullmatch(_require_text(payload.get("agentRef"), "agentRef")):
            raise OperationsError("agentRef is invalid")
        if not AGENT_INSTANCE_RE.fullmatch(
            _require_text(payload.get("agentInstanceRef"), "agentInstanceRef")
        ):
            raise OperationsError("agentInstanceRef is invalid")
        return
    if event_type == "Stop":
        if payload:
            raise OperationsError("Stop payload must be empty")
        return
    if event_type == "SessionEnd":
        if payload:
            raise OperationsError("SessionEnd payload must be empty")
        return
    expected = {
        "relation",
        "relatedWorkItemRef",
        "category",
        "executionClass",
        "agentSelection",
        "outcome",
        "verification",
        "evidenceSource",
        "supersedesEventId",
    }
    if set(payload) != expected:
        raise OperationsError("Annotation payload fields are invalid")
    if payload.get("relation") not in RELATIONS:
        raise OperationsError("Annotation relation is invalid")
    related = payload.get("relatedWorkItemRef")
    if related is not None and (not isinstance(related, str) or not WORK_ITEM_RE.fullmatch(related)):
        raise OperationsError("relatedWorkItemRef is invalid")
    if payload["relation"] in {"new-task", "unclassified"} and related is not None:
        raise OperationsError("new or unclassified work items cannot name a related item")
    if payload["relation"] not in {"new-task", "unclassified"} and related is None:
        raise OperationsError("this relation requires an earlier work item")
    if payload.get("category") not in TASK_CATEGORIES:
        raise OperationsError("Annotation category is invalid")
    if payload.get("executionClass") not in EXECUTION_CLASSES:
        raise OperationsError("Annotation executionClass is invalid")
    if payload.get("agentSelection") not in AGENT_SELECTIONS:
        raise OperationsError("Annotation agentSelection is invalid")
    if payload["executionClass"] == "direct" and payload["agentSelection"] not in {
        "not-applicable",
        "unknown",
    }:
        raise OperationsError("direct execution cannot claim a subagent selection")
    if payload["executionClass"] in {"delegated", "coordinated"} and payload[
        "agentSelection"
    ] == "not-applicable":
        raise OperationsError("delegated execution requires an agent-selection assessment")
    if payload.get("outcome") not in OUTCOMES:
        raise OperationsError("Annotation outcome is invalid")
    if payload.get("verification") not in VERIFICATION_STATES:
        raise OperationsError("Annotation verification is invalid")
    if payload.get("evidenceSource") not in EVIDENCE_SOURCES:
        raise OperationsError("Annotation evidenceSource is invalid")
    supersedes = payload.get("supersedesEventId")
    if supersedes is not None:
        try:
            if str(uuid.UUID(supersedes)) != supersedes:
                raise OperationsError("supersedesEventId must use canonical UUID form")
        except (ValueError, AttributeError) as exc:
            raise OperationsError("supersedesEventId is invalid") from exc
    if payload["outcome"] == "user-accepted" and payload["evidenceSource"] != "user-reported":
        raise OperationsError("user-accepted requires user-reported evidence")
    if payload["outcome"] == "verified" and payload["verification"] != "passed":
        raise OperationsError("verified outcome requires passed verification")
    if payload["relation"] == "cancel" and payload["outcome"] != "abandoned":
        raise OperationsError("cancel relation requires abandoned outcome")


def _event_payload(
    event_type: str,
    hook: dict[str, Any],
    store: harness_eval_store.EvaluationStore,
    repository_id: str,
) -> dict[str, Any]:
    if event_type == "UserPromptSubmit":
        prompt = _require_text(hook.get("prompt"), "prompt")
        return {
            "promptFingerprint": store.fingerprint(
                repository_id.encode("ascii") + b"\0prompt\0" + prompt.encode("utf-8")
            )
        }
    if event_type in {"SubagentStart", "SubagentStop"}:
        return {
            "agentRef": store.pseudonym(
                repository_id, "agent", _require_text(hook.get("agent_type"), "agent_type")
            ),
            "agentInstanceRef": store.pseudonym(
                repository_id,
                "agent-instance",
                _require_text(hook.get("agent_id"), "agent_id"),
            ),
        }
    return {}


def _read_events(
    store: harness_eval_store.EvaluationStore, repository_id: str
) -> tuple[list[dict[str, Any]], list[str]]:
    root = _events_root(store, repository_id)
    if not root.is_dir():
        return [], []
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in store.records(root):
        try:
            value = _read_event(path)
            events.append(value)
        except (OSError, UnicodeError, json.JSONDecodeError, OperationsError) as exc:
            errors.append(f"{path.name}: {exc}")
    events.sort(key=lambda item: (item["createdAt"], item["eventId"]))
    return events, errors


def _read_event(path: Path) -> dict[str, Any]:
    with path.open('rb') as stream:
        content = stream.read(MAX_EVENT_BYTES + 1)
    if len(content) > MAX_EVENT_BYTES:
        raise OperationsError("operations event exceeds its size limit")
    value = json.loads(content)
    validate_event(value)
    return value


def _event_key(event: dict[str, Any], *, lifecycle: bool = False) -> str:
    fields = ("eventType", "workItemRef") if lifecycle else ("eventType", "sessionRef", "turnRef", "workItemRef", "payload")
    return hashlib.sha256(_canonical_text([event[key] for key in fields]).encode()).hexdigest()


def _directory_stamp(root: Path) -> list[int] | None:
    if not root.exists():
        return None
    info = root.stat()
    return [info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns]


def _index_path(store: harness_eval_store.EvaluationStore, repository_id: str) -> Path:
    return store.checked(_events_root(store, repository_id).parent / "index.json")


def _index_add(index: dict[str, Any], event: dict[str, Any]) -> None:
    index["count"] += 1
    if event["eventType"] in HOOK_EVENTS:
        index["replay"][_event_key(event)] = event["eventId"]
    if event["eventType"] in {"UserPromptSubmit", "Stop"}:
        index["lifecycle"][_event_key(event, lifecycle=True)] = event["eventId"]


def _write_index(store: harness_eval_store.EvaluationStore, repository_id: str, index: dict[str, Any]) -> None:
    index["directory"] = _directory_stamp(_events_root(store, repository_id))
    value = {**index, "signature": store.fingerprint(_canonical_text(index).encode())}
    content = _canonical_text(value)
    if len(content.encode()) > MAX_INDEX_BYTES:
        raise OperationsError("operations index exceeds its size limit")
    path = _index_path(store, repository_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        path.parent.chmod(0o700)
    harness_state.atomic_write_text(path, content, mode=0o600)


def _event_index(store: harness_eval_store.EvaluationStore, repository_id: str) -> dict[str, Any]:
    # This is a disposable, authenticated replay index, not an audit substitute.
    # Directory changes include an event committed before an interrupted index
    # write. Rebuild from the immutable records under the repository lock.
    path = _index_path(store, repository_id)
    if path.is_file():
        try:
            with path.open('rb') as stream:
                content = stream.read(MAX_INDEX_BYTES + 1)
            if len(content) > MAX_INDEX_BYTES:
                raise ValueError('oversized index')
            value = json.loads(content)
            signature = value.pop('signature')
            if (set(value) != {'schemaVersion', 'repositoryId', 'directory', 'count', 'replay', 'lifecycle'}
                    or value['schemaVersion'] != 1 or value['repositoryId'] != repository_id
                    or type(value['count']) is not int or not 0 <= value['count'] <= MAX_EVENTS_PER_REPOSITORY
                    or not isinstance(signature, str)
                    or not hmac.compare_digest(signature, store.fingerprint(_canonical_text(value).encode()))
                    or value['directory'] != _directory_stamp(_events_root(store, repository_id))):
                raise ValueError('stale index')
            for field in ('replay', 'lifecycle'):
                if not isinstance(value[field], dict) or len(value[field]) > value['count']:
                    raise ValueError('invalid index')
                for key, event_id in value[field].items():
                    if not HASH_RE.fullmatch(key) or str(uuid.UUID(event_id)) != event_id:
                        raise ValueError('invalid index entry')
            return value
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError):
            pass
    events, errors = _read_events(store, repository_id)
    if errors:
        raise OperationsError("operations state contains invalid records; run audit for details")
    if len(events) > MAX_EVENTS_PER_REPOSITORY:
        raise OperationsError("operations event limit reached; audit and purge local state")
    index = {'schemaVersion': 1, 'repositoryId': repository_id, 'directory': None,
             'count': 0, 'replay': {}, 'lifecycle': {}}
    for event in events:
        if event['repositoryId'] != repository_id:
            raise OperationsError("operations event belongs to another repository")
        _index_add(index, event)
    _write_index(store, repository_id, index)
    return index


def _same_event(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    return all(
        existing.get(key) == candidate.get(key)
        for key in ("eventType", "sessionRef", "turnRef", "workItemRef", "payload")
    )


def _store_event(
    store: harness_eval_store.EvaluationStore,
    repository_id: str,
    event: dict[str, Any],
    *,
    deduplicate: bool,
) -> tuple[dict[str, Any], bool]:
    validate_event(event)
    with store.repository_lock(repository_id):
        index = _event_index(store, repository_id)
        if deduplicate:
            matching = index['replay'].get(_event_key(event))
            if matching:
                previous = _read_event(store.checked(_events_root(store, repository_id) / f"{matching}.json"))
                if previous['repositoryId'] != repository_id or previous['eventId'] != matching or not _same_event(previous, event):
                    raise OperationsError("operations replay record changed; run audit for details")
                return previous, False
            if event['eventType'] in {'UserPromptSubmit', 'Stop'} and _event_key(event, lifecycle=True) in index['lifecycle']:
                raise OperationsError("hook replay contradicts an existing work-item event")
        if index['count'] >= MAX_EVENTS_PER_REPOSITORY:
            raise OperationsError("operations event limit reached; audit and purge local state")
        path = store.checked(_events_root(store, repository_id) / f"{event['eventId']}.json")
        _write_exclusive(path, event)
        _index_add(index, event)
        _write_index(store, repository_id, index)
    return event, True


def _new_event(
    *,
    repository_id: str,
    event_type: str,
    session_ref: str,
    turn_ref: str | None,
    work_item_ref: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return _seal(
        {
            "schemaVersion": OPS_EVENT_SCHEMA_VERSION,
            "eventId": str(uuid.uuid4()),
            "repositoryId": repository_id,
            "harnessVersion": harness_metadata.HARNESS_VERSION,
            "createdAt": _timestamp(),
            "eventType": event_type,
            "sessionRef": session_ref,
            "turnRef": turn_ref,
            "workItemRef": work_item_ref,
            "payload": payload,
            "privacy": {
                "rawPromptStored": False,
                "rawResponseStored": False,
                "rawTranscriptStored": False,
                "rawAgentNameStored": False,
                "absolutePathStored": False,
            },
            "integrity": {"recordSha256": None},
        }
    )


def record_hook_event(
    hook: dict[str, Any], *, state_root: Path | None = None
) -> dict[str, Any]:
    event_type = _require_text(hook.get("hook_event_name"), "hook_event_name")
    if event_type not in HOOK_EVENTS:
        raise OperationsError(f"unsupported hook event: {event_type}")
    cwd = Path(_require_text(hook.get("cwd"), "cwd"))
    root = _find_harness_root(cwd)
    if root is None:
        return {"recorded": False, "reason": "not-a-local-harness-workspace"}
    store = harness_eval_store.EvaluationStore(state_root=state_root)
    repository_id = store.register_workspace(root)
    session_id = _require_text(hook.get("session_id"), "session_id")
    session_ref = store.pseudonym(repository_id, "session", session_id)
    if event_type == "SessionEnd":
        turn_ref = None
        work_item_ref = None
    else:
        turn_id = _require_text(hook.get("turn_id"), "turn_id")
        turn_ref = store.pseudonym(repository_id, "turn", turn_id)
        work_item_ref = store.pseudonym(
            repository_id, "work-item", f"{session_id}\0{turn_id}"
        )
    payload = _event_payload(event_type, hook, store, repository_id)
    event = _new_event(
        repository_id=repository_id,
        event_type=event_type,
        session_ref=session_ref,
        turn_ref=turn_ref,
        work_item_ref=work_item_ref,
        payload=payload,
    )
    stored, created = _store_event(
        store, repository_id, event, deduplicate=event_type != "Annotation"
    )
    return {
        "recorded": True,
        "created": created,
        "repositoryId": repository_id,
        "workItemRef": stored["workItemRef"],
        "eventType": event_type,
    }


def _latest_annotation(events: Iterable[dict[str, Any]], work_item_ref: str) -> dict[str, Any] | None:
    matches = [
        event
        for event in events
        if event["eventType"] == "Annotation" and event["workItemRef"] == work_item_ref
    ]
    if not matches:
        return None
    by_id = {event['eventId']: event for event in matches}
    replaced = {event['payload']['supersedesEventId'] for event in matches} - {None}
    active = set(by_id) - replaced
    if len(by_id) != len(matches) or not replaced <= set(by_id) or len(active) != 1:
        raise OperationsError("annotation replacement history is incomplete or branched")
    latest = by_id[active.pop()]
    seen, current = set(), latest
    while current is not None and current['eventId'] not in seen:
        seen.add(current['eventId'])
        current = by_id.get(current['payload']['supersedesEventId'])
    if current is not None or len(seen) != len(matches):
        raise OperationsError("annotation replacement history contains a cycle")
    return latest


def _feedback_files(store: harness_eval_store.EvaluationStore, repository_id: str) -> list[Path]:
    directory = store.checked(_events_root(store, repository_id).parent / "routing-feedback")
    paths = store.records(directory) if directory.is_dir() else []
    if len(paths) > MAX_EVENTS_PER_REPOSITORY:
        raise OperationsError("pending routing feedback exceeds its limit")
    return paths


def _stage_routing_feedback(routing: Any, event: dict[str, Any], cause: str) -> None:
    state = routing.read()
    if not state['enabled'] and event['workItemRef'] not in state['samples'] and event['workItemRef'] not in state['pending']:
        return
    repository_id = event['repositoryId']
    # The repository lock is already held. An interrupted pre-commit stage is
    # removable only here, where its event writer cannot still be running.
    paths = _feedback_files(routing.store, repository_id)
    for path in paths:
        event_path = routing.store.checked(_events_root(routing.store, repository_id) / path.name)
        if not event_path.exists():
            path.unlink()
    if len(_feedback_files(routing.store, repository_id)) >= MAX_EVENTS_PER_REPOSITORY:
        raise OperationsError("pending routing feedback limit reached")
    value = {'schemaVersion': 1, 'eventId': event['eventId'], 'repositoryId': repository_id, 'cause': cause}
    value['signature'] = routing.store.fingerprint(_canonical_text(value).encode())
    path = routing.store.checked(_events_root(routing.store, repository_id).parent / 'routing-feedback' / f"{event['eventId']}.json")
    _write_exclusive(path, value)


def _flush_routing_feedback(routing: Any, repository_id: str, *, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    # Always acquire repository before routing locks. Validate committed events
    # before replaying the bounded outbox; a staged but uncommitted annotation
    # cannot become quality evidence. Replacement links, not wall-clock order,
    # determine the current verdict when the system clock moves backwards.
    from harness_routing_evidence import OUTCOMES as ROUTING_OUTCOMES
    pending = []
    for path in _feedback_files(routing.store, repository_id):
        with path.open('rb') as stream:
            content = stream.read(MAX_EVENT_BYTES + 1)
        if len(content) > MAX_EVENT_BYTES:
            raise OperationsError("pending routing feedback exceeds its size limit")
        value = json.loads(content)
        signature = value.pop('signature', None) if isinstance(value, dict) else None
        if (not isinstance(value, dict) or set(value) != {'schemaVersion', 'eventId', 'repositoryId', 'cause'}
                or value['schemaVersion'] != 1 or value['repositoryId'] != repository_id
                or not isinstance(value['cause'], str) or value['cause'] not in {'unknown', 'inference', 'environment'}
                or not isinstance(value['eventId'], str) or not isinstance(signature, str)
                or not hmac.compare_digest(signature, routing.store.fingerprint(_canonical_text(value).encode()))
                or str(uuid.UUID(value['eventId'])) != value['eventId'] or path.name != value['eventId'] + '.json'):
            raise OperationsError("invalid pending routing feedback")
        event_path = routing.store.checked(_events_root(routing.store, repository_id) / path.name)
        if not event_path.exists():
            path.unlink()
            continue
        event = _read_event(event_path)
        if event['eventId'] != value['eventId'] or event['repositoryId'] != repository_id or event['eventType'] != 'Annotation':
            raise OperationsError("routing feedback event identity changed")
        pending.append((event, value['cause'], path))
    result = {'recorded': False, 'reason': 'disabled-or-no-pending-feedback'}
    if pending and events is None:
        events, errors = _read_events(routing.store, repository_id)
        if errors:
            raise OperationsError("operations state contains invalid records; run audit for details")
    for reference in dict.fromkeys(item[0]['workItemRef'] for item in pending):
        event = _latest_annotation(events, reference)
        if event is None:
            raise OperationsError("pending routing annotation is missing")
        cause = next((cause for item, cause, path in pending if item['eventId'] == event['eventId']), 'unknown')
        outcome, source = event['payload']['outcome'], event['payload']['evidenceSource']
        supported = (outcome in ROUTING_OUTCOMES and (outcome != 'verified' or source == 'verification')
                     and (outcome != 'user-accepted' or source == 'user-reported'))
        if source in {'verification', 'user-reported'}:
            result = routing._feedback(event['workItemRef'], outcome if supported else 'unknown', source, cause, existing_when_disabled=True)
        else:
            result = routing._feedback(event['workItemRef'], 'unknown', 'runtime', 'unknown', existing_when_disabled=True)
        if result.get('reason') != 'disabled':
            for item, cause, path in pending:
                if item['workItemRef'] == reference:
                    path.unlink()
    return result


def annotate(
    *,
    root: Path,
    work_item_ref: str | None,
    relation: str,
    category: str,
    execution_class: str,
    agent_selection: str,
    outcome: str,
    verification: str,
    evidence_source: str,
    related_work_item_ref: str | None = None,
    state_root: Path | None = None,
    maintenance_reason: str | None = None,
    maintenance_evidence: str | None = None,
    maintenance_session_ref: str | None = None,
    maintenance_change: str | None = None,
    maintenance_revision: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    runtime: str | None = None,
    routing_cause: str | None = None,
) -> dict[str, Any]:
    selected_root = _find_harness_root(root)
    if selected_root is None:
        raise OperationsError("--root must be inside a local Harness workspace")
    if routing_cause is not None and routing_cause not in {'unknown', 'inference', 'environment'}:
        raise OperationsError("unsupported routing cause")
    store = harness_eval_store.EvaluationStore(state_root=state_root)
    repository_id = store.register_workspace(selected_root)
    with store.repository_lock(repository_id):
        events, errors = _read_events(store, repository_id)
        if errors:
            raise OperationsError("operations state contains invalid records; run audit for details")
        prompts = [event for event in events if event["eventType"] == "UserPromptSubmit"]
        if work_item_ref is None:
            if not prompts:
                raise OperationsError("no recorded work item is available")
            work_item_ref = prompts[-1]["workItemRef"]
        if not WORK_ITEM_RE.fullmatch(work_item_ref):
            raise OperationsError("work item reference is invalid")
        prompt = next(
            (event for event in reversed(prompts) if event["workItemRef"] == work_item_ref),
            None,
        )
        if prompt is None:
            raise OperationsError("work item does not belong to this repository")
        if related_work_item_ref is None and relation not in {"new-task", "unclassified"}:
            prior = [
                event
                for event in prompts
                if event["sessionRef"] == prompt["sessionRef"]
                and event["createdAt"] < prompt["createdAt"]
            ]
            related_work_item_ref = prior[-1]["workItemRef"] if prior else None
        if related_work_item_ref == work_item_ref:
            raise OperationsError("a work item cannot relate to itself")
        if related_work_item_ref is not None:
            related = next(
                (
                    event
                    for event in prompts
                    if event["workItemRef"] == related_work_item_ref
                    and event["sessionRef"] == prompt["sessionRef"]
                ),
                None,
            )
            if related is None:
                raise OperationsError("related work item must be an earlier item in the same session")
            if related["createdAt"] >= prompt["createdAt"]:
                raise OperationsError("related work item must precede the annotated work item")
        previous = _latest_annotation(events, work_item_ref)
        payload = {
            "relation": relation,
            "relatedWorkItemRef": related_work_item_ref,
            "category": category,
            "executionClass": execution_class,
            "agentSelection": agent_selection,
            "outcome": outcome,
            "verification": verification,
            "evidenceSource": evidence_source,
            "supersedesEventId": previous["eventId"] if previous else None,
        }
        event = _new_event(
            repository_id=repository_id,
            event_type="Annotation",
            session_ref=prompt["sessionRef"],
            turn_ref=prompt["turnRef"],
            work_item_ref=work_item_ref,
            payload=payload,
        )
        validate_event(event)
        if len(events) >= MAX_EVENTS_PER_REPOSITORY:
            raise OperationsError("operations event limit reached; audit and purge local state")
        from harness_routing_evidence import RoutingEvidence
        routing = RoutingEvidence(selected_root, state_root)
        _stage_routing_feedback(routing, event, routing_cause or 'unknown')
        _write_exclusive(
            store.checked(_events_root(store, repository_id) / f"{event['eventId']}.json"), event
        )
        # Preserve annotation order while merging feedback with a possibly later
        # turn/completed observation. Only the enum summary crosses this boundary.
        try:
            routing_result = _flush_routing_feedback(routing, repository_id, events=[*events, event])
        except (OSError, ValueError, TimeoutError):
            routing_result = {'available': False, 'recordPreserved': True}
    result = {
        "valid": True,
        "repositoryId": repository_id,
        "workItemRef": work_item_ref,
        "annotationEventId": event["eventId"],
        "supersedesEventId": payload["supersedesEventId"],
        "rawContentStored": False,
        "routing": routing_result,
    }
    if maintenance_reason or maintenance_evidence or maintenance_change or maintenance_session_ref:
        # Optional, explicitly linked evidence only. A task failure alone never
        # declares a harness defect. A maintenance error cannot erase the record.
        try:
            if bool(maintenance_reason) != bool(maintenance_evidence):
                raise ValueError('Maintenance signal requires both reason and evidence')
            if maintenance_session_ref and not maintenance_reason:
                raise ValueError('Maintenance session context requires a selected evidence signal')
            from harness_maintenance import Maintenance
            manager = Maintenance(selected_root, state_root)
            linked = {}
            if maintenance_reason and maintenance_evidence:
                linked['signal'] = manager.signal(maintenance_reason, maintenance_evidence, work_item_ref, session_ref=maintenance_session_ref)
            if maintenance_change:
                linked['observation'] = manager.observe(maintenance_change, work_item_ref, outcome, evidence_source,
                    maintenance_revision, model=model, effort=effort, category=category, runtime=runtime)
            result['maintenance'] = linked
        except (OSError, ValueError, TimeoutError):
            result['maintenance'] = {'available': False, 'recordPreserved': True}
    return result


def audit(root: Path, *, state_root: Path | None = None) -> dict[str, Any]:
    selected_root = _find_harness_root(root)
    if selected_root is None:
        raise OperationsError("--root must be inside a local Harness workspace")
    store = harness_eval_store.EvaluationStore(state_root=state_root)
    repository_id = store.register_workspace(selected_root)
    with store.repository_lock(repository_id):
        events, errors = _read_events(store, repository_id)
    prompts = [event for event in events if event["eventType"] == "UserPromptSubmit"]
    annotations = {}
    for reference in dict.fromkeys(item['workItemRef'] for item in events if item['eventType'] == 'Annotation'):
        try:
            annotations[reference] = _latest_annotation(events, reference)
        except OperationsError as exc:
            errors.append(f"{reference}: {exc}")
    starts = [event for event in events if event["eventType"] == "SubagentStart"]
    stops = [event for event in events if event["eventType"] == "SubagentStop"]
    stopped_instances = {
        (event["workItemRef"], event["payload"]["agentInstanceRef"])
        for event in stops
    }
    dangling = [
        event["payload"]["agentInstanceRef"]
        for event in starts
        if (event["workItemRef"], event["payload"]["agentInstanceRef"])
        not in stopped_instances
    ]
    relation_counts = Counter()
    category_counts = Counter()
    outcome_counts = Counter()
    verification_counts = Counter()
    execution_counts = Counter()
    agent_selection_counts = Counter()
    work_items: list[dict[str, Any]] = []
    correction_targets: Counter[str] = Counter()
    acceptance_targets: Counter[str] = Counter()
    for prompt in prompts:
        annotation = annotations.get(prompt["workItemRef"])
        payload = annotation["payload"] if annotation else {
            "relation": "unclassified",
            "relatedWorkItemRef": None,
            "category": "unknown",
            "executionClass": "unknown",
            "agentSelection": "unknown",
            "outcome": "unknown",
            "verification": "unknown",
            "evidenceSource": "hook-observed",
        }
        relation_counts[payload["relation"]] += 1
        category_counts[payload["category"]] += 1
        outcome_counts[payload["outcome"]] += 1
        verification_counts[payload["verification"]] += 1
        execution_counts[payload["executionClass"]] += 1
        agent_selection_counts[payload["agentSelection"]] += 1
        if payload["relation"] in {"correction", "reopen"} and payload["relatedWorkItemRef"]:
            correction_targets[payload["relatedWorkItemRef"]] += 1
        if payload["relation"] == "acceptance" and payload["relatedWorkItemRef"]:
            acceptance_targets[payload["relatedWorkItemRef"]] += 1
        agents = [
            event["payload"]["agentRef"]
            for event in starts
            if event["workItemRef"] == prompt["workItemRef"]
        ]
        work_items.append(
            {
                "workItemRef": prompt["workItemRef"],
                "relation": payload["relation"],
                "relatedWorkItemRef": payload["relatedWorkItemRef"],
                "category": payload["category"],
                "executionClass": payload["executionClass"],
                "agentSelection": payload["agentSelection"],
                "outcome": payload["outcome"],
                "verification": payload["verification"],
                "evidenceSource": payload["evidenceSource"],
                "agentRefs": sorted(set(agents)),
                "correctionCount": 0,
                "userAcceptanceCount": 0,
            }
        )
    for item in work_items:
        item["correctionCount"] = correction_targets[item["workItemRef"]]
        item["userAcceptanceCount"] = acceptance_targets[item["workItemRef"]]
    problem_outcomes = sum(
        outcome_counts[value] for value in ("needs-revision", "failed", "abandoned")
    )
    questionable_agent_selections = sum(
        agent_selection_counts[value] for value in ("questionable", "inappropriate")
    )
    unknown_count = outcome_counts["unknown"]
    unclassified_count = relation_counts["unclassified"]
    if errors:
        status = "state-invalid"
    elif problem_outcomes or questionable_agent_selections or dangling:
        status = "review-recommended"
    elif not prompts or unknown_count or unclassified_count:
        status = "insufficient-evidence"
    else:
        status = "healthy"
    signals: list[str] = []
    if unknown_count:
        signals.append("outcome-evidence-missing")
    if unclassified_count:
        signals.append("work-item-relation-unclassified")
    if problem_outcomes:
        signals.append("adverse-outcome-observed")
    if questionable_agent_selections:
        signals.append("agent-selection-review-recommended")
    if dangling:
        signals.append("subagent-terminal-unobserved")
    if errors:
        signals.append("operations-state-invalid")
    if len(events) >= MAX_EVENTS_PER_REPOSITORY:
        signals.append("operations-retention-limit-reached")
    agent_counts = Counter(event["payload"]["agentRef"] for event in starts)
    session_refs = {event["sessionRef"] for event in prompts}
    ended_session_refs = {
        event["sessionRef"]
        for event in events
        if event["eventType"] == "SessionEnd"
    }
    return {
        "valid": not errors,
        "operationsSchemaVersion": OPS_EVENT_SCHEMA_VERSION,
        "harnessVersion": harness_metadata.HARNESS_VERSION,
        "repositoryId": repository_id,
        "status": status,
        "regenerationRecommended": False,
        "eventCount": len(events),
        "eventLimit": MAX_EVENTS_PER_REPOSITORY,
        "invalidEventCount": len(errors),
        "sessionCount": len(session_refs),
        "endedSessionCount": len(session_refs & ended_session_refs),
        "workItemCount": len(prompts),
        "annotatedWorkItemCount": len(annotations),
        "relationCounts": dict(sorted(relation_counts.items())),
        "categoryCounts": dict(sorted(category_counts.items())),
        "executionClassCounts": dict(sorted(execution_counts.items())),
        "agentSelectionCounts": dict(sorted(agent_selection_counts.items())),
        "outcomeCounts": dict(sorted(outcome_counts.items())),
        "verificationCounts": dict(sorted(verification_counts.items())),
        "agentUseCounts": dict(sorted(agent_counts.items())),
        "danglingAgentInstanceCount": len(set(dangling)),
        "signals": signals,
        "workItems": work_items,
        "errors": errors,
        "privacy": {
            "rawPromptStored": False,
            "rawResponseStored": False,
            "rawTranscriptStored": False,
            "rawAgentNameStored": False,
            "absolutePathStored": False,
        },
    }


def _shell_command(arguments: list[str]) -> str:
    return subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)


def hook_configuration() -> dict[str, Any]:
    command = _shell_command([sys.executable, str(Path(__file__).resolve()), "hook"])
    hooks: dict[str, list[dict[str, Any]]] = {}
    for event_type in ("UserPromptSubmit", "SubagentStart", "SubagentStop", "Stop", "SessionEnd"):
        handler: dict[str, Any] = {
            "type": "command",
            "command": command,
            "timeout": 3,
        }
        if event_type == "UserPromptSubmit":
            handler["additionalContextLimit"] = 512
        hooks[event_type] = [
            {
                "hooks": [handler]
            }
        ]
    return {
        "description": "Opt-in local Harness work-item operations evidence.",
        "hooks": hooks,
    }


def _annotation_context(result: dict[str, Any]) -> str:
    command = _shell_command(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "annotate",
            "--root",
            ".",
            "--work-item-ref",
            result["workItemRef"],
        ]
    )
    return (
        f"Harness Ops work item {result['workItemRef']} represents only this user turn, not the whole session. "
        "Before the final response, classify its relation, task category, execution class, agent-selection fit, "
        "outcome, and verification "
        "with enum-only evidence. Completion alone is not success; do not infer user acceptance; use unknown when "
        f"evidence is absent. Run `{command}` with the applicable --relation, --category, --execution-class, "
        "--agent-selection, "
        "--outcome, --verification, and --evidence-source values. Do not pass prompt or response text."
    )


def command_hook(args: argparse.Namespace) -> int:
    try:
        data = sys.stdin.buffer.read(MAX_HOOK_INPUT_BYTES + 1)
        if len(data) > MAX_HOOK_INPUT_BYTES:
            raise OperationsError("hook input exceeds the size limit")
        hook = json.loads(data.decode("utf-8"))
        if not isinstance(hook, dict):
            raise OperationsError("hook input must be an object")
        result = record_hook_event(hook)
        event_type = hook.get("hook_event_name")
        if event_type == "UserPromptSubmit" and result.get("recorded"):
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "UserPromptSubmit",
                            "additionalContext": _annotation_context(result),
                        }
                    },
                    ensure_ascii=False,
                )
            )
        elif event_type in {"SubagentStop", "Stop"}:
            print("{}")
        return 0
    except Exception:
        # Observability is fail-open: it must never block the user's Codex task.
        try:
            event_type = locals().get("hook", {}).get("hook_event_name")
            if event_type in {"UserPromptSubmit", "SubagentStart", "SubagentStop", "Stop"}:
                print(
                    json.dumps(
                        {"systemMessage": "Harness operations evidence was not recorded."}
                    )
                )
        except Exception:
            pass
        return 0


def command_hooks_template(args: argparse.Namespace) -> int:
    value = hook_configuration()
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        path = harness_state.external_location(Path(args.output))
        if path.exists():
            raise OperationsError("refusing to overwrite an existing hooks file; merge manually")
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            os.chmod(path, 0o600)
        print(json.dumps({"valid": True, "created": True, "output": str(path)}, indent=2))
    else:
        sys.stdout.write(payload)
    return 0


def command_annotate(args: argparse.Namespace) -> int:
    result = annotate(
        root=Path(args.root),
        work_item_ref=args.work_item_ref,
        relation=args.relation,
        category=args.category,
        execution_class=args.execution_class,
        agent_selection=args.agent_selection,
        outcome=args.outcome,
        verification=args.verification,
        evidence_source=args.evidence_source,
        maintenance_reason=args.maintenance_reason,
        maintenance_evidence=args.maintenance_evidence,
        maintenance_session_ref=args.maintenance_session_ref,
        maintenance_change=args.maintenance_change,
        maintenance_revision=args.maintenance_revision,
        model=args.model,
        effort=args.effort,
        runtime=args.runtime,
        routing_cause=getattr(args, 'routing_cause', None),
        related_work_item_ref=args.related_work_item_ref,
        state_root=Path(args.state_home) if args.state_home else None,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def command_audit(args: argparse.Namespace) -> int:
    result = audit(
        Path(args.root),
        state_root=Path(args.state_home) if args.state_home else None,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["valid"] else 1


def command_purge(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    selected_root = _find_harness_root(root)
    if selected_root is None:
        raise OperationsError("--root must be inside a local Harness workspace")
    store = harness_eval_store.EvaluationStore(
        state_root=Path(args.state_home) if args.state_home else None
    )
    repository_id = store.register_workspace(selected_root)
    events_root = _events_root(store, repository_id)
    removed = 0
    with store.repository_lock(repository_id):
        index_path = _index_path(store, repository_id)
        feedback_files = _feedback_files(store, repository_id)
        if feedback_files:
            from harness_routing_evidence import RoutingEvidence
            _flush_routing_feedback(RoutingEvidence(selected_root, store.root), repository_id)
        if events_root.is_dir():
            records = store.records(events_root)
            for path in records:
                path.unlink()
                removed += 1
            for path in feedback_files:
                path.unlink(missing_ok=True)
            index_path.unlink(missing_ok=True)
            try:
                events_root.rmdir()
                events_root.parent.rmdir()
            except OSError:
                pass
    print(
        json.dumps(
            {"valid": True, "repositoryId": repository_id, "removedEventCount": removed},
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    hook = subparsers.add_parser("hook", help="Read one Codex hook event from stdin")
    hook.set_defaults(handler=command_hook)

    hooks = subparsers.add_parser(
        "hooks-template", help="Print an opt-in user-level Codex hooks.json template"
    )
    hooks.add_argument("--output", help="Create a new hooks file; existing files are never replaced")
    hooks.set_defaults(handler=command_hooks_template)

    annotation = subparsers.add_parser(
        "annotate", help="Add enum-only evidence to one recorded work item"
    )
    annotation.add_argument("--root", required=True)
    annotation.add_argument("--work-item-ref")
    annotation.add_argument("--related-work-item-ref")
    annotation.add_argument("--routing-cause", choices=('unknown', 'inference', 'environment'), default='unknown')
    annotation.add_argument("--relation", choices=sorted(RELATIONS), default="unclassified")
    annotation.add_argument("--category", choices=sorted(TASK_CATEGORIES), default="unknown")
    annotation.add_argument(
        "--execution-class", choices=sorted(EXECUTION_CLASSES), default="unknown"
    )
    annotation.add_argument(
        "--agent-selection", choices=sorted(AGENT_SELECTIONS), default="unknown"
    )
    annotation.add_argument("--outcome", choices=sorted(OUTCOMES), default="unknown")
    annotation.add_argument(
        "--verification", choices=sorted(VERIFICATION_STATES), default="unknown"
    )
    annotation.add_argument(
        "--evidence-source", choices=sorted(EVIDENCE_SOURCES), default="agent-reported"
    )
    annotation.add_argument("--state-home")
    for name in ('maintenance-reason', 'maintenance-evidence', 'maintenance-session-ref', 'maintenance-change', 'maintenance-revision', 'model', 'effort', 'runtime'):
        annotation.add_argument('--' + name)
    annotation.set_defaults(handler=command_annotate)

    audit_parser = subparsers.add_parser(
        "audit", help="Summarize work-item evidence without reading transcripts"
    )
    audit_parser.add_argument("--root", required=True)
    audit_parser.add_argument("--state-home")
    audit_parser.set_defaults(handler=command_audit)

    purge = subparsers.add_parser("purge", help="Delete local operations events for one workspace")
    purge.add_argument("--root", required=True)
    purge.add_argument("--state-home")
    purge.set_defaults(handler=command_purge)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.handler(args)
    except (OSError, UnicodeError, OperationsError, harness_eval_store.StoreError, harness_state.StateError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
