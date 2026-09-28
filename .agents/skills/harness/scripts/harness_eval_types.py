#!/usr/bin/env python3
"""Canonical types and validation for optional Harness evaluation records."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

import harness_metadata


RUN_SCHEMA_VERSION = harness_metadata.EVALUATION_SCHEMA_VERSION
ANNOTATION_SCHEMA_VERSION = harness_metadata.EVALUATION_SCHEMA_VERSION
COMPARISON_PLAN_SCHEMA_VERSION = harness_metadata.EVALUATION_SCHEMA_VERSION
COMPARISON_SCHEMA_VERSION = harness_metadata.EVALUATION_SCHEMA_VERSION
PROPOSAL_SCHEMA_VERSION = harness_metadata.EVALUATION_SCHEMA_VERSION
OBSERVATION_SCHEMA_VERSION = 1
MANUAL_REPORT_SCHEMA_VERSION = 1
PARSER_VERSION = "1"
HARNESS_VERSION = harness_metadata.HARNESS_VERSION
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
PSEUDONYM_RE = re.compile(r"^[a-z][a-z0-9-]*:[0-9a-f]{32}$")

CAPTURE_MODES = {"runtime-instrumented", "agent-reported", "manual", "mixed"}
CAPTURE_SCOPES = {"codex-exec-jsonl", "agent-report", "user-input", "mixed"}
COMPLETENESS = {"complete", "partial", "unknown"}
PARSER_COMPATIBILITY = {"supported", "degraded", "unsupported"}
MEASUREMENT_STATES = {"measured", "unavailable", "not-applicable"}
MEASUREMENT_SOURCES = {
    "codex-jsonl",
    "evaluator-clock",
    "process-exit",
    "verification-runner",
    "agent-report",
    "user-report",
    "user-annotation",
    "derived",
    "none",
}
FIDELITIES = {"exact", "reported", "derived", "unknown"}
PLATFORMS = {"linux", "windows", "macos", "unknown"}
SANDBOXES = {"read-only", "workspace-write", "danger-full-access", "unknown"}
TASK_CATEGORIES = {
    "bugfix",
    "feature",
    "refactor",
    "migration",
    "test",
    "review",
    "research",
    "documentation",
    "configuration",
    "maintenance",
    "other",
    "unknown",
}
LEVELS = {"low", "medium", "high", "unknown"}
COMPLEXITY_SIGNALS = {
    "single-file",
    "multi-file",
    "single-boundary",
    "multi-boundary",
    "cross-contract",
    "parallelizable",
    "long-running",
    "external-dependency",
    "unknown",
}
IMPACT_SIGNALS = {
    "read-only",
    "test-only",
    "documentation-only",
    "production-code",
    "schema-change",
    "data-mutation",
    "security-sensitive",
    "deployment",
    "external-side-effect",
    "unknown",
}
UNCERTAINTY_SIGNALS = {
    "clear-oracle",
    "missing-oracle",
    "ambiguous-requirement",
    "ambiguous-route",
    "capability-unknown",
    "external-state-unknown",
    "nondeterministic-dependency",
    "unknown",
}
CONFOUNDERS = {
    "model-version",
    "reasoning-effort",
    "runtime-version",
    "platform",
    "test-coverage",
    "task-difficulty",
    "network-state",
    "external-service",
    "arm-order",
    "manual-intervention",
    "missing-measurement",
    "baseline-patch-scope-violation",
    "isolation-gap",
    "unknown",
}
CLASSIFICATION_SOURCES = {"user", "fixture", "agent-reported", "derived", "unknown"}
EXECUTION_CLASSES = {"direct", "delegated", "coordinated", "unknown"}
OBSERVATION_SOURCES = {"assigned", "configured", "agent-reported", "runtime-observed", "unknown"}
ARMS = {"baseline", "harness", "unpaired"}
COMPLETION_STATES = {"completed", "failed", "interrupted", "aborted", "unknown"}
ISOLATION_STATES = {"complete", "partial", "failed", "not-applicable"}
EVIDENCE_CLASSES = {"observational", "paired-replay", "controlled-live-comparison"}
SUPPORT_STRENGTHS = {"insufficient", "weak", "moderate", "strong"}
PRIMARY_OUTCOMES = {
    "verification-pass-rate",
    "critical-failure-rate",
    "correction-count",
    "wall-time-ms",
    "output-tokens",
    "input-tokens",
    "cached-input-tokens",
    "reasoning-output-tokens",
}
DIRECTIONS = {"higher-is-better", "lower-is-better"}


class EvaluationError(ValueError):
    pass


class Clock(Protocol):
    def now_utc(self) -> datetime: ...


class IdProvider(Protocol):
    def new_uuid(self) -> uuid.UUID: ...


class SystemClock:
    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)


class RandomUuidProvider:
    def new_uuid(self) -> uuid.UUID:
        return uuid.uuid4()


@dataclass
class FixedClock:
    value: datetime

    def now_utc(self) -> datetime:
        if self.value.tzinfo is None:
            raise EvaluationError("fixed clock value must be timezone-aware")
        return self.value.astimezone(timezone.utc)


@dataclass
class SequenceUuidProvider:
    values: list[uuid.UUID]

    def new_uuid(self) -> uuid.UUID:
        if not self.values:
            raise EvaluationError("test UUID sequence is exhausted")
        return self.values.pop(0)


def timestamp_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise EvaluationError("timestamp must be timezone-aware")
    normalized = value.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def canonical_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    ) + "\n"


def canonical_bytes(value: Any) -> bytes:
    return canonical_text(value).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _integrity_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(record)
    integrity = payload.get("integrity")
    if not isinstance(integrity, dict):
        raise EvaluationError("record integrity must be an object")
    integrity["recordSha256"] = None
    return payload


def seal_record(record: dict[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(record)
    sealed.setdefault("integrity", {})["recordSha256"] = digest_bytes(
        canonical_bytes(_integrity_payload(sealed))
    )
    return sealed


def verify_integrity(record: dict[str, Any]) -> None:
    if not isinstance(record, dict):
        raise EvaluationError("evaluation record must be an object")
    integrity = record.get("integrity")
    recorded = integrity.get("recordSha256") if isinstance(integrity, dict) else None
    if not isinstance(recorded, str) or not HASH_RE.fullmatch(recorded):
        raise EvaluationError("record integrity hash must be 64 lowercase hexadecimal characters")
    expected = digest_bytes(canonical_bytes(_integrity_payload(record)))
    if recorded != expected:
        raise EvaluationError("record integrity hash does not match canonical content")


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvaluationError(f"{label} must be an object")
    return value


def _require_keys(value: dict[str, Any], allowed: Iterable[str], required: Iterable[str], label: str) -> None:
    allowed_set = set(allowed)
    required_set = set(required)
    unknown = set(value) - allowed_set
    missing = required_set - set(value)
    if unknown:
        raise EvaluationError(f"{label} contains unknown fields: {', '.join(sorted(unknown))}")
    if missing:
        raise EvaluationError(f"{label} is missing fields: {', '.join(sorted(missing))}")


def reasoning_effort(value: Any) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= 256 or not value.isprintable() or any(c.isspace() for c in value):
        raise EvaluationError("reasoning effort must be a bounded identifier")
    return value


def _require_enum(value: Any, allowed: set[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise EvaluationError(f"{label} must be one of: {', '.join(sorted(allowed))}")
    return value


def _require_uuid(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise EvaluationError(f"{label} must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise EvaluationError(f"{label} must be a UUID string") from exc
    if str(parsed) != value.lower():
        raise EvaluationError(f"{label} must use canonical lowercase UUID form")
    return value


def _require_timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EvaluationError(f"{label} must be a UTC RFC3339 timestamp ending in Z")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise EvaluationError(f"{label} must be a valid UTC RFC3339 timestamp") from exc
    return value


def measurement(
    value: int | float | None,
    *,
    unit: str,
    state: str,
    source: str,
    fidelity: str,
    completeness: str,
) -> dict[str, Any]:
    result = {
        "value": value,
        "unit": unit,
        "state": state,
        "source": source,
        "fidelity": fidelity,
        "completeness": completeness,
    }
    validate_measurement(result)
    return result


def unavailable(unit: str) -> dict[str, Any]:
    return measurement(
        None,
        unit=unit,
        state="unavailable",
        source="none",
        fidelity="unknown",
        completeness="unknown",
    )


def validate_measurement(value: Any, label: str = "measurement") -> dict[str, Any]:
    item = _require_object(value, label)
    fields = {"value", "unit", "state", "source", "fidelity", "completeness"}
    _require_keys(item, fields, fields, label)
    state = _require_enum(item["state"], MEASUREMENT_STATES, f"{label}.state")
    source = _require_enum(item["source"], MEASUREMENT_SOURCES, f"{label}.source")
    fidelity = _require_enum(item["fidelity"], FIDELITIES, f"{label}.fidelity")
    _require_enum(item["completeness"], COMPLETENESS, f"{label}.completeness")
    unit = item["unit"]
    measured_value = item["value"]
    if not isinstance(unit, str) or not unit or len(unit) > 32:
        raise EvaluationError(f"{label}.unit must be a short non-empty string")
    if state == "measured":
        if measured_value is None or isinstance(measured_value, bool) or not isinstance(measured_value, (int, float)):
            raise EvaluationError(f"{label}.value must be numeric when state is measured")
        if isinstance(measured_value, float) and not math.isfinite(measured_value):
            raise EvaluationError(f"{label}.value must be finite")
        if source == "none" or fidelity == "unknown":
            raise EvaluationError(f"{label} measured values require a source and known fidelity")
    elif measured_value is not None:
        raise EvaluationError(f"{label}.value must be null when state is {state}")
    if source in {"agent-report", "user-report", "user-annotation"} and fidelity == "exact":
        raise EvaluationError(f"{label} reported values cannot use exact fidelity")
    if state != "measured" and source != "none":
        raise EvaluationError(f"{label} unavailable values must use source none")
    return item


def _validate_comparison_plan_v1(value: Any) -> dict[str, Any]:
    plan = _require_object(value, "comparison plan")
    fields = {
        "schemaVersion",
        "primaryOutcome",
        "correctnessGate",
        "secondaryOutcomes",
        "verificationProfileFingerprint",
    }
    _require_keys(plan, fields, fields, "comparison plan")
    if plan["schemaVersion"] != 1:
        raise EvaluationError("comparison plan schemaVersion must be 1")
    outcome = _require_object(plan["primaryOutcome"], "comparison plan primaryOutcome")
    _require_keys(
        outcome,
        {"metric", "direction", "minimumEffect"},
        {"metric", "direction", "minimumEffect"},
        "comparison plan primaryOutcome",
    )
    metric = _require_enum(outcome["metric"], PRIMARY_OUTCOMES, "primaryOutcome.metric")
    direction = _require_enum(outcome["direction"], DIRECTIONS, "primaryOutcome.direction")
    expected_direction = "higher-is-better" if metric == "verification-pass-rate" else "lower-is-better"
    if metric != "cached-input-tokens" and direction != expected_direction:
        raise EvaluationError(f"primary outcome {metric} must use direction {expected_direction}")
    minimum = outcome["minimumEffect"]
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or minimum < 0 or not math.isfinite(minimum):
        raise EvaluationError("primaryOutcome.minimumEffect must be a finite non-negative number")
    if plan["correctnessGate"] not in {"no-regression", "none"}:
        raise EvaluationError("comparison plan correctnessGate must be no-regression or none")
    secondary = plan["secondaryOutcomes"]
    if not isinstance(secondary, list) or any(item not in PRIMARY_OUTCOMES for item in secondary):
        raise EvaluationError("comparison plan secondaryOutcomes must contain known outcome names")
    if len(secondary) != len(set(secondary)) or metric in secondary:
        raise EvaluationError("comparison plan outcomes must be unique")
    fingerprint = plan["verificationProfileFingerprint"]
    if fingerprint is not None and (not isinstance(fingerprint, str) or not HASH_RE.fullmatch(fingerprint)):
        raise EvaluationError("verificationProfileFingerprint must be null or a SHA-256 hash")
    return plan


def _validate_run_record_v1(value: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    record = _require_object(value, "run record")
    fields = {
        "schemaVersion",
        "runId",
        "recordState",
        "capture",
        "timestamps",
        "repository",
        "runtime",
        "task",
        "configuration",
        "measurements",
        "outcome",
        "comparison",
        "privacy",
        "result",
        "integrity",
    }
    _require_keys(record, fields, fields, "run record")
    if record["schemaVersion"] != 1:
        raise EvaluationError("run record schemaVersion must be 1")
    _require_uuid(record["runId"], "runId")
    if record["recordState"] not in {"pending", "completed"}:
        raise EvaluationError("recordState must be pending or completed")

    capture = _require_object(record["capture"], "capture")
    capture_fields = {
        "captureMode",
        "captureScope",
        "streamCompleteness",
        "terminalEventObserved",
        "parserVersion",
        "parserCompatibility",
        "malformedEventCount",
        "unknownEventCount",
        "rawEventsStored",
    }
    _require_keys(capture, capture_fields, capture_fields, "capture")
    mode = _require_enum(capture["captureMode"], CAPTURE_MODES, "capture.captureMode")
    scope = _require_enum(capture["captureScope"], CAPTURE_SCOPES, "capture.captureScope")
    completeness = _require_enum(capture["streamCompleteness"], COMPLETENESS, "capture.streamCompleteness")
    if mode == "runtime-instrumented" and scope != "codex-exec-jsonl":
        raise EvaluationError("runtime-instrumented capture requires codex-exec-jsonl scope")
    if not isinstance(capture["terminalEventObserved"], bool):
        raise EvaluationError("capture.terminalEventObserved must be boolean")
    if not capture["terminalEventObserved"] and completeness == "complete":
        raise EvaluationError("capture cannot be complete without a terminal event")
    if capture["parserVersion"] != PARSER_VERSION:
        raise EvaluationError(f"capture.parserVersion must be {PARSER_VERSION}")
    compatibility = _require_enum(
        capture["parserCompatibility"], PARSER_COMPATIBILITY, "capture.parserCompatibility"
    )
    if compatibility != "supported" and completeness == "complete":
        raise EvaluationError("degraded or unsupported parser compatibility cannot be complete")
    validate_measurement(capture["malformedEventCount"], "capture.malformedEventCount")
    validate_measurement(capture["unknownEventCount"], "capture.unknownEventCount")
    if capture["rawEventsStored"] is not False:
        raise EvaluationError("v5.5 never stores raw JSONL events")

    timestamps = _require_object(record["timestamps"], "timestamps")
    _require_keys(timestamps, {"startedAt", "endedAt"}, {"startedAt", "endedAt"}, "timestamps")
    _require_timestamp(timestamps["startedAt"], "timestamps.startedAt")
    if record["recordState"] == "completed":
        _require_timestamp(timestamps["endedAt"], "timestamps.endedAt")
    elif timestamps["endedAt"] is not None:
        raise EvaluationError("pending record endedAt must be null")

    repository = _require_object(record["repository"], "repository")
    _require_keys(
        repository,
        {"repositoryId", "sourceSnapshotId", "manifestSha256", "topologySha256"},
        {"repositoryId", "sourceSnapshotId", "manifestSha256", "topologySha256"},
        "repository",
    )
    _require_uuid(repository["repositoryId"], "repository.repositoryId")
    snapshot = repository["sourceSnapshotId"]
    if snapshot is not None and (
        not isinstance(snapshot, str)
        or not re.fullmatch(r"(?:git:[0-9a-f]{40,64}|tree:[0-9a-f]{64})", snapshot)
    ):
        raise EvaluationError("repository.sourceSnapshotId must be null or a content identifier")
    for key in ("manifestSha256", "topologySha256"):
        item = repository[key]
        if item is not None and (not isinstance(item, str) or not HASH_RE.fullmatch(item)):
            raise EvaluationError(f"repository.{key} must be null or a SHA-256 hash")

    runtime = _require_object(record["runtime"], "runtime")
    runtime_fields = {
        "harnessVersion",
        "codexVersion",
        "surface",
        "modelRef",
        "reasoningEffort",
        "platform",
        "sandbox",
        "ephemeral",
        "ignoreUserConfig",
        "ignoreRules",
    }
    _require_keys(runtime, runtime_fields, runtime_fields, "runtime")
    if runtime["harnessVersion"] not in {"5.3", "5.4", "5.5"}:
        raise EvaluationError("legacy runtime.harnessVersion must be 5.3, 5.4, or 5.5")
    codex_version = runtime["codexVersion"]
    if codex_version is not None and (
        not isinstance(codex_version, str)
        or not codex_version
        or len(codex_version) > 128
        or any(ord(character) < 32 for character in codex_version)
    ):
        raise EvaluationError("runtime.codexVersion must be null or a short single-line value")
    model_ref = runtime["modelRef"]
    if model_ref is not None and (not isinstance(model_ref, str) or not PSEUDONYM_RE.fullmatch(model_ref)):
        raise EvaluationError("runtime.modelRef must be null or a local pseudonym")
    if runtime["surface"] not in {"exec", "interactive", "manual", "unknown"}:
        raise EvaluationError("runtime.surface is invalid")
    reasoning_effort(runtime["reasoningEffort"])
    _require_enum(runtime["platform"], PLATFORMS, "runtime.platform")
    _require_enum(runtime["sandbox"], SANDBOXES, "runtime.sandbox")
    for key in ("ephemeral", "ignoreUserConfig", "ignoreRules"):
        if not isinstance(runtime[key], bool):
            raise EvaluationError(f"runtime.{key} must be boolean")

    task = _require_object(record["task"], "task")
    task_fields = {"taskInstanceId", "promptFingerprint", "category", "classificationSource", "complexity", "impact", "uncertainty"}
    _require_keys(task, task_fields, task_fields, "task")
    _require_uuid(task["taskInstanceId"], "task.taskInstanceId")
    prompt_fingerprint = task["promptFingerprint"]
    if prompt_fingerprint is not None and (
        not isinstance(prompt_fingerprint, str) or not HASH_RE.fullmatch(prompt_fingerprint)
    ):
        raise EvaluationError("task.promptFingerprint must be null or a local HMAC digest")
    _require_enum(task["category"], TASK_CATEGORIES, "task.category")
    _require_enum(task["classificationSource"], CLASSIFICATION_SOURCES, "task.classificationSource")
    signal_sets = {
        "complexity": COMPLEXITY_SIGNALS,
        "impact": IMPACT_SIGNALS,
        "uncertainty": UNCERTAINTY_SIGNALS,
    }
    for key, allowed_signals in signal_sets.items():
        classification = _require_object(task[key], f"task.{key}")
        _require_keys(classification, {"level", "signals"}, {"level", "signals"}, f"task.{key}")
        _require_enum(classification["level"], LEVELS, f"task.{key}.level")
        signals = classification["signals"]
        if not isinstance(signals, list) or not signals or any(item not in allowed_signals for item in signals):
            raise EvaluationError(f"task.{key}.signals must contain only known signals")
        if len(signals) != len(set(signals)):
            raise EvaluationError(f"task.{key}.signals must not contain duplicates")

    configuration = _require_object(record["configuration"], "configuration")
    configuration_fields = {
        "arm",
        "configuredExecutionClass",
        "configuredRouteRef",
        "configuredAgentRefs",
        "configuredSkillRefs",
        "qualityPolicyRefs",
        "observedExecution",
    }
    _require_keys(configuration, configuration_fields, configuration_fields, "configuration")
    _require_enum(configuration["arm"], ARMS, "configuration.arm")
    _require_enum(configuration["configuredExecutionClass"], EXECUTION_CLASSES, "configuration.configuredExecutionClass")
    configured_route_ref = configuration["configuredRouteRef"]
    if configured_route_ref is not None and (
        not isinstance(configured_route_ref, str) or not PSEUDONYM_RE.fullmatch(configured_route_ref)
    ):
        raise EvaluationError("configuration.configuredRouteRef must be null or a local pseudonym")
    observed = _require_object(configuration["observedExecution"], "configuration.observedExecution")
    observed_fields = {"executionClass", "routeRef", "agentRefs", "skillRefs", "source"}
    _require_keys(observed, observed_fields, observed_fields, "configuration.observedExecution")
    _require_enum(observed["executionClass"], EXECUTION_CLASSES, "observedExecution.executionClass")
    _require_enum(observed["source"], OBSERVATION_SOURCES, "observedExecution.source")
    observed_route_ref = observed["routeRef"]
    if observed_route_ref is not None and (
        not isinstance(observed_route_ref, str) or not PSEUDONYM_RE.fullmatch(observed_route_ref)
    ):
        raise EvaluationError("observedExecution.routeRef must be null or a local pseudonym")
    for container, keys in ((configuration, ("configuredAgentRefs", "configuredSkillRefs", "qualityPolicyRefs")), (observed, ("agentRefs", "skillRefs"))):
        for key in keys:
            if not isinstance(container[key], list) or not all(
                isinstance(item, str) and PSEUDONYM_RE.fullmatch(item) for item in container[key]
            ):
                raise EvaluationError(f"{key} must contain only local pseudonyms")

    measurements = _require_object(record["measurements"], "measurements")
    measurement_fields = {
        "wallTimeMs",
        "processExitCode",
        "inputTokens",
        "cachedInputTokens",
        "outputTokens",
        "reasoningOutputTokens",
        "commandExecutions",
        "mcpToolCalls",
        "webSearches",
        "fileChanges",
        "subagentRuns",
        "retryCount",
    }
    _require_keys(measurements, measurement_fields, measurement_fields, "measurements")
    for key, item in measurements.items():
        validate_measurement(item, f"measurements.{key}")

    outcome = _require_object(record["outcome"], "outcome")
    _require_keys(outcome, {"completion", "verification", "criticalFailure"}, {"completion", "verification", "criticalFailure"}, "outcome")
    _require_enum(outcome["completion"], COMPLETION_STATES, "outcome.completion")
    if not isinstance(outcome["criticalFailure"], bool) or not isinstance(outcome["verification"], list):
        raise EvaluationError("outcome verification and criticalFailure are invalid")
    for index, check in enumerate(outcome["verification"]):
        check = _require_object(check, f"outcome.verification[{index}]")
        _require_keys(check, {"checkRef", "profileFingerprint", "kind", "result", "exitCode"}, {"checkRef", "profileFingerprint", "kind", "result", "exitCode"}, f"outcome.verification[{index}]")
        if not isinstance(check["checkRef"], str) or not PSEUDONYM_RE.fullmatch(check["checkRef"]):
            raise EvaluationError(f"outcome.verification[{index}].checkRef must be a local pseudonym")
        if not isinstance(check["profileFingerprint"], str) or not HASH_RE.fullmatch(check["profileFingerprint"]):
            raise EvaluationError(f"outcome.verification[{index}].profileFingerprint must be a SHA-256 hash")
        _require_enum(check["kind"], {"unit-test", "integration-test", "lint", "type-check", "schema", "custom"}, f"outcome.verification[{index}].kind")
        _require_enum(check["result"], {"passed", "failed", "not-run", "unknown"}, f"outcome.verification[{index}].result")
        validate_measurement(check["exitCode"], f"outcome.verification[{index}].exitCode")

    comparison = _require_object(record["comparison"], "comparison")
    _require_keys(comparison, {"comparisonId", "pairId", "armOrder", "isolationStatus", "isolationGaps"}, {"comparisonId", "pairId", "armOrder", "isolationStatus", "isolationGaps"}, "comparison")
    _require_nullable_uuid(comparison["comparisonId"], "comparison.comparisonId")
    _require_nullable_uuid(comparison["pairId"], "comparison.pairId")
    _require_enum(comparison["armOrder"], {"first", "second", "unpaired"}, "comparison.armOrder")
    _require_enum(comparison["isolationStatus"], ISOLATION_STATES, "comparison.isolationStatus")
    if not isinstance(comparison["isolationGaps"], list) or not all(isinstance(item, str) for item in comparison["isolationGaps"]):
        raise EvaluationError("comparison.isolationGaps must be a string array")
    if configuration["arm"] == "unpaired" and (
        comparison["comparisonId"] is not None
        or comparison["pairId"] is not None
        or comparison["armOrder"] != "unpaired"
    ):
        raise EvaluationError("unpaired records cannot carry paired identifiers or arm order")
    if configuration["arm"] != "unpaired" and (
        comparison["comparisonId"] is None
        or comparison["pairId"] is None
        or comparison["armOrder"] == "unpaired"
    ):
        raise EvaluationError("paired records require comparisonId, pairId, and arm order")

    privacy = _require_object(record["privacy"], "privacy")
    privacy_fields = {"rawPromptStored", "rawTranscriptStored", "sourceContentStored", "absolutePathStored", "remoteUrlStored", "rawEventsStored"}
    _require_keys(privacy, privacy_fields, privacy_fields, "privacy")
    if any(privacy[key] is not False for key in privacy_fields):
        raise EvaluationError("v5.5 run records must not retain raw or identifying content")

    result = _require_object(record["result"], "result")
    _require_keys(result, {"resultFingerprint", "verificationProfileFingerprint", "processCleanupVerified"}, {"resultFingerprint", "verificationProfileFingerprint", "processCleanupVerified"}, "result")
    for key in ("resultFingerprint", "verificationProfileFingerprint"):
        if result[key] is not None and (not isinstance(result[key], str) or not HASH_RE.fullmatch(result[key])):
            raise EvaluationError(f"result.{key} must be null or a SHA-256/HMAC digest")
    if not isinstance(result["processCleanupVerified"], bool):
        raise EvaluationError("result.processCleanupVerified must be boolean")

    if verify_hash:
        verify_integrity(record)
    return record


def _validate_annotation_v1(value: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    annotation = _require_object(value, "annotation")
    fields = {"schemaVersion", "annotationId", "runId", "createdAt", "source", "acceptance", "correctionCount", "reopened", "freeTextStored", "integrity"}
    _require_keys(annotation, fields, fields, "annotation")
    if annotation["schemaVersion"] != 1:
        raise EvaluationError("annotation schemaVersion must be 1")
    _require_uuid(annotation["annotationId"], "annotationId")
    _require_uuid(annotation["runId"], "runId")
    _require_timestamp(annotation["createdAt"], "createdAt")
    if annotation["source"] != "user":
        raise EvaluationError("v5.5 annotations must use source user")
    if annotation["acceptance"] not in {"accepted", "accepted-with-corrections", "rejected", "unknown"}:
        raise EvaluationError("annotation acceptance is invalid")
    validate_measurement(annotation["correctionCount"], "annotation.correctionCount")
    correction = annotation["correctionCount"]
    if correction["state"] == "measured":
        correction_value = correction["value"]
        if (
            isinstance(correction_value, bool)
            or not isinstance(correction_value, int)
            or correction_value < 0
        ):
            raise EvaluationError("annotation.correctionCount must be a non-negative integer")
    if annotation["acceptance"] == "accepted-with-corrections" and (
        correction["state"] != "measured" or correction["value"] < 1
    ):
        raise EvaluationError("accepted-with-corrections requires a measured correction count of at least 1")
    if not isinstance(annotation["reopened"], bool) or annotation["freeTextStored"] is not False:
        raise EvaluationError("annotation reopened/freeTextStored fields are invalid")
    if verify_hash:
        verify_integrity(annotation)
    return annotation


def _require_nullable_uuid(value: Any, label: str) -> None:
    if value is not None:
        _require_uuid(value, label)


def _require_number_or_null(value: Any, label: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EvaluationError(f"{label} must be a finite number or null")


def _validate_comparison_record_v1(value: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    record = _require_object(value, "comparison record")
    required = {
        "schemaVersion",
        "comparisonId",
        "pairId",
        "repositoryId",
        "createdAt",
        "planSha256",
        "baselineRunId",
        "treatmentRunId",
        "evidenceClass",
        "isolationStatus",
        "isolationGaps",
        "primaryOutcome",
        "correctnessGate",
        "confounders",
        "causalClaimAllowed",
        "integrity",
    }
    _require_keys(record, required | {"randomizationSeed"}, required, "comparison record")
    if record["schemaVersion"] != 1:
        raise EvaluationError("comparison record schemaVersion must be 1")
    for key in ("comparisonId", "pairId", "repositoryId", "baselineRunId", "treatmentRunId"):
        _require_uuid(record[key], key)
    _require_timestamp(record["createdAt"], "createdAt")
    if not isinstance(record["planSha256"], str) or not HASH_RE.fullmatch(record["planSha256"]):
        raise EvaluationError("comparison planSha256 must be a SHA-256 hash")
    evidence_class = _require_enum(record["evidenceClass"], EVIDENCE_CLASSES, "evidenceClass")
    if evidence_class == "observational":
        raise EvaluationError("paired comparison records cannot use observational evidence")
    isolation = _require_enum(record["isolationStatus"], {"complete", "partial", "failed"}, "isolationStatus")
    if evidence_class == "controlled-live-comparison" and isolation != "complete":
        raise EvaluationError("controlled-live-comparison requires complete isolation")
    gaps = record["isolationGaps"]
    if not isinstance(gaps, list) or any(not isinstance(item, str) or not item for item in gaps):
        raise EvaluationError("isolationGaps must be a string array")

    outcome = _require_object(record["primaryOutcome"], "primaryOutcome")
    outcome_fields = {
        "metric",
        "directionRule",
        "minimumEffect",
        "baselineValue",
        "treatmentValue",
        "delta",
        "direction",
        "completeness",
    }
    _require_keys(outcome, outcome_fields, outcome_fields, "primaryOutcome")
    metric = _require_enum(outcome["metric"], PRIMARY_OUTCOMES, "primaryOutcome.metric")
    direction_rule = _require_enum(outcome["directionRule"], DIRECTIONS, "primaryOutcome.directionRule")
    expected_direction = "higher-is-better" if metric == "verification-pass-rate" else "lower-is-better"
    if metric != "cached-input-tokens" and direction_rule != expected_direction:
        raise EvaluationError(f"primary outcome {metric} must use direction {expected_direction}")
    for key in ("minimumEffect", "baselineValue", "treatmentValue", "delta", "completeness"):
        _require_number_or_null(outcome[key], f"primaryOutcome.{key}")
    if outcome["minimumEffect"] is None or outcome["minimumEffect"] < 0:
        raise EvaluationError("primaryOutcome.minimumEffect must be non-negative")
    if outcome["completeness"] is None or not 0 <= outcome["completeness"] <= 1:
        raise EvaluationError("primaryOutcome.completeness must be between 0 and 1")
    _require_enum(outcome["direction"], {"beneficial", "harmful", "tie", "unknown"}, "primaryOutcome.direction")
    if (outcome["baselineValue"] is None) != (outcome["treatmentValue"] is None):
        raise EvaluationError("primary outcome arm values must be jointly available or unavailable")
    if outcome["baselineValue"] is None and (outcome["delta"] is not None or outcome["direction"] != "unknown"):
        raise EvaluationError("unavailable primary outcomes require null delta and unknown direction")

    gate = _require_object(record["correctnessGate"], "correctnessGate")
    _require_keys(gate, {"policy", "passed", "criticalRegression", "status"}, {"policy", "passed", "criticalRegression"}, "correctnessGate")
    if gate["policy"] not in {"no-regression", "none"}:
        raise EvaluationError("correctnessGate.policy is invalid")
    if not isinstance(gate["passed"], bool) or not isinstance(gate["criticalRegression"], bool):
        raise EvaluationError("correctnessGate booleans are invalid")
    if "status" in gate and (gate["status"] not in {"passed", "failed", "unknown"} or gate["passed"] != (gate["status"] == "passed")):
        raise EvaluationError("correctnessGate status is inconsistent")
    confounders = record["confounders"]
    if not isinstance(confounders, list) or any(item not in CONFOUNDERS for item in confounders):
        raise EvaluationError("confounders must contain only known values")
    if len(confounders) != len(set(confounders)):
        raise EvaluationError("confounders must not contain duplicates")
    if record["causalClaimAllowed"] is not False:
        raise EvaluationError("v5.5 comparison records cannot allow causal claims")
    seed = record.get("randomizationSeed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or seed < 0):
        raise EvaluationError("randomizationSeed must be a non-negative integer")
    if verify_hash:
        verify_integrity(record)
    return record


def _validate_proposal_record_v1(value: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    record = _require_object(value, "proposal record")
    fields = {
        "schemaVersion",
        "proposalId",
        "repositoryId",
        "proposalType",
        "condition",
        "candidate",
        "evidence",
        "language",
        "status",
        "autoApplicable",
        "createdAt",
        "integrity",
    }
    _require_keys(record, fields, fields, "proposal record")
    if record["schemaVersion"] != 1:
        raise EvaluationError("proposal record schemaVersion must be 1")
    _require_uuid(record["proposalId"], "proposalId")
    _require_uuid(record["repositoryId"], "repositoryId")
    _require_timestamp(record["createdAt"], "createdAt")
    _require_enum(record["proposalType"], {"experiment-suggestion", "configuration-proposal", "no-change", "negative-signal"}, "proposalType")
    _require_enum(record["status"], {"observed", "proposed", "rejected"}, "status")
    if record["autoApplicable"] is not False:
        raise EvaluationError("v5.5 proposals must not be auto-applicable")

    condition = _require_object(record["condition"], "condition")
    _require_keys(condition, {"taskCategory", "complexityLevel", "impactLevel"}, {"taskCategory", "complexityLevel", "impactLevel"}, "condition")
    _require_enum(condition["taskCategory"], TASK_CATEGORIES, "condition.taskCategory")
    _require_enum(condition["complexityLevel"], LEVELS, "condition.complexityLevel")
    _require_enum(condition["impactLevel"], LEVELS, "condition.impactLevel")

    candidate = _require_object(record["candidate"], "candidate")
    _require_keys(candidate, {"executionClass", "addIndependentReview"}, {"executionClass", "addIndependentReview"}, "candidate")
    _require_enum(candidate["executionClass"], EXECUTION_CLASSES, "candidate.executionClass")
    if not isinstance(candidate["addIndependentReview"], bool):
        raise EvaluationError("candidate.addIndependentReview must be boolean")

    evidence = _require_object(record["evidence"], "evidence")
    evidence_fields = {
        "evidenceClass",
        "comparisonRefs",
        "pairCount",
        "wins",
        "losses",
        "ties",
        "medianPairedDelta",
        "direction",
        "supportStrength",
        "primaryOutcomeCompleteness",
        "isolationCompleteRatio",
        "criticalRegressionCount",
        "confounders",
        "thresholds",
    }
    _require_keys(evidence, evidence_fields, evidence_fields, "evidence")
    _require_enum(evidence["evidenceClass"], EVIDENCE_CLASSES, "evidence.evidenceClass")
    refs = evidence["comparisonRefs"]
    if not isinstance(refs, list):
        raise EvaluationError("evidence.comparisonRefs must be an array")
    for index, item in enumerate(refs):
        _require_uuid(item, f"evidence.comparisonRefs[{index}]")
    for key in ("pairCount", "wins", "losses", "ties", "criticalRegressionCount"):
        item = evidence[key]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise EvaluationError(f"evidence.{key} must be a non-negative integer")
    if evidence["pairCount"] != len(refs) or evidence["wins"] + evidence["losses"] + evidence["ties"] != evidence["pairCount"]:
        raise EvaluationError("proposal evidence counts are inconsistent")
    _require_number_or_null(evidence["medianPairedDelta"], "evidence.medianPairedDelta")
    _require_enum(evidence["direction"], {"beneficial", "harmful", "mixed", "unknown"}, "evidence.direction")
    _require_enum(evidence["supportStrength"], SUPPORT_STRENGTHS, "evidence.supportStrength")
    for key in ("primaryOutcomeCompleteness", "isolationCompleteRatio"):
        value = evidence[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise EvaluationError(f"evidence.{key} must be between 0 and 1")
    confounders = evidence["confounders"]
    if not isinstance(confounders, list) or any(item not in CONFOUNDERS for item in confounders):
        raise EvaluationError("evidence.confounders must contain only known values")
    thresholds = _require_object(evidence["thresholds"], "evidence.thresholds")
    threshold_fields = {"minimumPairs", "weakDirectionRatio", "moderateDirectionRatio", "strongDirectionRatio"}
    _require_keys(thresholds, threshold_fields, threshold_fields, "evidence.thresholds")
    if isinstance(thresholds["minimumPairs"], bool) or not isinstance(thresholds["minimumPairs"], int) or thresholds["minimumPairs"] < 1:
        raise EvaluationError("evidence.thresholds.minimumPairs must be a positive integer")
    for key in threshold_fields - {"minimumPairs"}:
        item = thresholds[key]
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not 0 <= item <= 1:
            raise EvaluationError(f"evidence.thresholds.{key} must be between 0 and 1")

    language = _require_object(record["language"], "language")
    _require_keys(language, {"causalClaimAllowed", "requiredSummaryCode"}, {"causalClaimAllowed", "requiredSummaryCode"}, "language")
    if language["causalClaimAllowed"] is not False or language["requiredSummaryCode"] != "association-observed-causality-unconfirmed":
        raise EvaluationError("proposal language must retain the non-causal v5.5 contract")
    if verify_hash:
        verify_integrity(record)
    return record


def validate_comparison_plan(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("schemaVersion") == 1:
        return _validate_comparison_plan_v1(value)
    import harness_eval_schema2

    return harness_eval_schema2.validate_comparison_plan(value)


def validate_run_record(value: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("schemaVersion") == 1:
        return _validate_run_record_v1(value, verify_hash=verify_hash)
    import harness_eval_schema2

    return harness_eval_schema2.validate_run_record(value, verify_hash=verify_hash)


def validate_annotation(value: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("schemaVersion") == 1:
        return _validate_annotation_v1(value, verify_hash=verify_hash)
    import harness_eval_schema2

    return harness_eval_schema2.validate_annotation(value, verify_hash=verify_hash)


def validate_comparison_record(value: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("schemaVersion") == 1:
        return _validate_comparison_record_v1(value, verify_hash=verify_hash)
    import harness_eval_schema2

    return harness_eval_schema2.validate_comparison_record(value, verify_hash=verify_hash)


def validate_proposal_record(value: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("schemaVersion") == 1:
        return _validate_proposal_record_v1(value, verify_hash=verify_hash)
    import harness_eval_schema2

    return harness_eval_schema2.validate_proposal_record(value, verify_hash=verify_hash)


def validate_observation_record(value: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    import harness_eval_schema2

    return harness_eval_schema2.validate_observation_record(value, verify_hash=verify_hash)


def validate_manual_report(value: Any) -> dict[str, Any]:
    import harness_eval_schema2

    return harness_eval_schema2.validate_manual_report(value)


def load_json(path: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"cannot read JSON from {path}: {exc}") from exc
