#!/usr/bin/env python3
"""Closed Evaluation Schema 2 and Observation Schema 1 contracts."""

from __future__ import annotations

import copy
import re
from typing import Any

import harness_eval_types as types


REFERENCE_STATES = {"measured", "unavailable", "not-applicable"}
REFERENCE_SOURCES = {
    "run-configuration-snapshot",
    "comparison-plan",
    "runtime-event",
    "user-report",
    "agent-report",
    "verification-runner",
    "git-evaluator",
    "derived",
    "none",
}
REFERENCE_FIDELITIES = {"exact", "reported", "derived", "unknown"}
REFERENCE_COMPLETENESS = {"complete", "partial", "unknown", "not-applicable"}
FACTORS = {
    "execution-class",
    "route",
    "agent-set",
    "skill-set",
    "quality-policy-set",
    "independent-review",
    "change-discipline-version",
    "project-harness-content",
    "other-bundle",
}
ATTRIBUTION_SCOPES = {"single-factor", "bundle", "none"}
ATTRIBUTION_TARGETS = {"single-factor", "bundle", "descriptive-only"}
SCOPE_CLASSES = {"single-file", "multi-file", "cross-contract", "unknown"}
OBSERVATION_SOURCES = {"user-report", "agent-report", "runtime-event", "verification-runner"}
LOGICAL_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def reference_set(
    refs: list[str] | None,
    *,
    state: str,
    source: str,
    fidelity: str,
    completeness: str,
) -> dict[str, Any]:
    value = {
        "state": state,
        "refs": refs,
        "source": source,
        "fidelity": fidelity,
        "completeness": completeness,
    }
    validate_reference_set(value)
    return value


def unavailable_references() -> dict[str, Any]:
    return reference_set(
        None,
        state="unavailable",
        source="none",
        fidelity="unknown",
        completeness="unknown",
    )


def value_observation(
    value: Any,
    *,
    state: str,
    source: str,
    fidelity: str,
    completeness: str,
) -> dict[str, Any]:
    result = {
        "state": state,
        "value": value,
        "source": source,
        "fidelity": fidelity,
        "completeness": completeness,
    }
    validate_value_observation(result)
    return result


def unavailable_value() -> dict[str, Any]:
    return value_observation(
        None,
        state="unavailable",
        source="none",
        fidelity="unknown",
        completeness="unknown",
    )


def validate_reference_set(value: Any, label: str = "reference set") -> dict[str, Any]:
    item = types._require_object(value, label)
    fields = {"state", "refs", "source", "fidelity", "completeness"}
    types._require_keys(item, fields, fields, label)
    state = types._require_enum(item["state"], REFERENCE_STATES, f"{label}.state")
    source = types._require_enum(item["source"], REFERENCE_SOURCES, f"{label}.source")
    fidelity = types._require_enum(item["fidelity"], REFERENCE_FIDELITIES, f"{label}.fidelity")
    completeness = types._require_enum(
        item["completeness"], REFERENCE_COMPLETENESS, f"{label}.completeness"
    )
    refs = item["refs"]
    if state == "measured":
        if not isinstance(refs, list) or any(
            not isinstance(ref, str) or not types.PSEUDONYM_RE.fullmatch(ref) for ref in refs
        ):
            raise types.EvaluationError(f"{label}.refs must be an array of local pseudonyms")
        if len(refs) != len(set(refs)):
            raise types.EvaluationError(f"{label}.refs must not contain duplicates")
        if source == "none" or fidelity == "unknown" or completeness not in {"complete", "partial"}:
            raise types.EvaluationError(f"{label} measured state requires known provenance")
    else:
        expected_completeness = "unknown" if state == "unavailable" else "not-applicable"
        if refs is not None or source != "none" or fidelity != "unknown" or completeness != expected_completeness:
            raise types.EvaluationError(f"{label} {state} state has inconsistent provenance")
    return item


def validate_value_observation(value: Any, label: str = "value observation") -> dict[str, Any]:
    item = types._require_object(value, label)
    fields = {"state", "value", "source", "fidelity", "completeness"}
    types._require_keys(item, fields, fields, label)
    state = types._require_enum(item["state"], REFERENCE_STATES, f"{label}.state")
    source = types._require_enum(item["source"], REFERENCE_SOURCES, f"{label}.source")
    fidelity = types._require_enum(item["fidelity"], REFERENCE_FIDELITIES, f"{label}.fidelity")
    completeness = types._require_enum(
        item["completeness"], REFERENCE_COMPLETENESS, f"{label}.completeness"
    )
    if state == "measured":
        if item["value"] is None:
            raise types.EvaluationError(f"{label}.value cannot be null when measured")
        if source == "none" or fidelity == "unknown" or completeness not in {"complete", "partial"}:
            raise types.EvaluationError(f"{label} measured state requires known provenance")
    else:
        expected_completeness = "unknown" if state == "unavailable" else "not-applicable"
        if item["value"] is not None or source != "none" or fidelity != "unknown" or completeness != expected_completeness:
            raise types.EvaluationError(f"{label} {state} state has inconsistent provenance")
    return item


def _validate_configuration(value: Any) -> dict[str, Any]:
    configuration = types._require_object(value, "configuration")
    fields = {
        "arm",
        "declaredConfiguration",
        "expectedExecution",
        "discoveredConfiguration",
        "observedExecution",
    }
    types._require_keys(configuration, fields, fields, "configuration")
    types._require_enum(configuration["arm"], types.ARMS, "configuration.arm")

    declared = types._require_object(configuration["declaredConfiguration"], "declaredConfiguration")
    declared_fields = {
        "executionClass",
        "route",
        "agents",
        "skills",
        "qualityPolicies",
        "independentReview",
        "changeDisciplineVersion",
        "projectHarnessFingerprint",
        "bundleFingerprint",
    }
    types._require_keys(declared, declared_fields, declared_fields, "declaredConfiguration")
    validate_value_observation(declared["executionClass"], "declaredConfiguration.executionClass")
    validate_reference_set(declared["route"], "declaredConfiguration.route")
    for key in ("agents", "skills", "qualityPolicies"):
        validate_reference_set(declared[key], f"declaredConfiguration.{key}")
    for key in ("independentReview", "changeDisciplineVersion", "projectHarnessFingerprint", "bundleFingerprint"):
        validate_value_observation(declared[key], f"declaredConfiguration.{key}")

    execution_fields = {"executionClass", "route", "agents", "skills", "independentReview"}
    for section in ("expectedExecution", "observedExecution"):
        item = types._require_object(configuration[section], section)
        types._require_keys(item, execution_fields, execution_fields, section)
        validate_value_observation(item["executionClass"], f"{section}.executionClass")
        validate_reference_set(item["route"], f"{section}.route")
        validate_reference_set(item["agents"], f"{section}.agents")
        validate_reference_set(item["skills"], f"{section}.skills")
        validate_value_observation(item["independentReview"], f"{section}.independentReview")

    discovered = types._require_object(configuration["discoveredConfiguration"], "discoveredConfiguration")
    types._require_keys(discovered, {"agents", "skills"}, {"agents", "skills"}, "discoveredConfiguration")
    validate_reference_set(discovered["agents"], "discoveredConfiguration.agents")
    validate_reference_set(discovered["skills"], "discoveredConfiguration.skills")
    return configuration


def _validate_result(value: Any) -> dict[str, Any]:
    result = types._require_object(value, "result")
    fields = {
        "resultFingerprint",
        "verificationProfileFingerprint",
        "processCleanupVerified",
        "patchScope",
    }
    types._require_keys(result, fields, fields, "result")
    fingerprint = validate_value_observation(result["resultFingerprint"], "result.resultFingerprint")
    if fingerprint["state"] == "measured" and (
        not isinstance(fingerprint["value"], str) or not types.HASH_RE.fullmatch(fingerprint["value"])
    ):
        raise types.EvaluationError("result.resultFingerprint measured value must be a digest")
    verification = result["verificationProfileFingerprint"]
    if verification is not None and (not isinstance(verification, str) or not types.HASH_RE.fullmatch(verification)):
        raise types.EvaluationError("result.verificationProfileFingerprint must be null or a digest")
    if not isinstance(result["processCleanupVerified"], bool):
        raise types.EvaluationError("result.processCleanupVerified must be boolean")
    _validate_patch_scope(result["patchScope"])
    return result


def _validate_patch_scope(value: Any) -> dict[str, Any]:
    item = types._require_object(value, "result.patchScope")
    fields = {
        "state",
        "profileFingerprint",
        "changedTrackedCount",
        "untrackedCount",
        "outOfScopeCount",
        "changedPathRefs",
        "outOfScopePathRefs",
        "withinDeclaredScope",
        "maximumChangedPathsExceeded",
        "source",
        "fidelity",
        "completeness",
    }
    types._require_keys(item, fields, fields, "result.patchScope")
    state = types._require_enum(item["state"], {"measured", "unavailable"}, "patchScope.state")
    if state == "unavailable":
        for key in fields - {"state", "source", "fidelity", "completeness"}:
            if item[key] is not None:
                raise types.EvaluationError("unavailable patchScope values must be null")
        if (item["source"], item["fidelity"], item["completeness"]) != ("none", "unknown", "unknown"):
            raise types.EvaluationError("unavailable patchScope provenance is invalid")
        return item
    if item["source"] != "git-evaluator" or item["fidelity"] != "exact" or item["completeness"] not in {"complete", "partial"}:
        raise types.EvaluationError("measured patchScope provenance is invalid")
    if not isinstance(item["profileFingerprint"], str) or not types.HASH_RE.fullmatch(item["profileFingerprint"]):
        raise types.EvaluationError("patchScope.profileFingerprint must be a digest")
    for key in ("changedTrackedCount", "untrackedCount", "outOfScopeCount"):
        if isinstance(item[key], bool) or not isinstance(item[key], int) or item[key] < 0:
            raise types.EvaluationError(f"patchScope.{key} must be a non-negative integer")
    for key in ("changedPathRefs", "outOfScopePathRefs"):
        validate_reference_set(
            {
                "state": "measured",
                "refs": item[key],
                "source": "git-evaluator",
                "fidelity": "exact",
                "completeness": item["completeness"],
            },
            f"patchScope.{key}",
        )
    for key in ("withinDeclaredScope", "maximumChangedPathsExceeded"):
        if not isinstance(item[key], bool):
            raise types.EvaluationError(f"patchScope.{key} must be boolean")
    return item


def unavailable_patch_scope() -> dict[str, Any]:
    return {
        "state": "unavailable",
        "profileFingerprint": None,
        "changedTrackedCount": None,
        "untrackedCount": None,
        "outOfScopeCount": None,
        "changedPathRefs": None,
        "outOfScopePathRefs": None,
        "withinDeclaredScope": None,
        "maximumChangedPathsExceeded": None,
        "source": "none",
        "fidelity": "unknown",
        "completeness": "unknown",
    }


def validate_run_record(value: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    record = types._require_object(value, "run record")
    if record.get("schemaVersion") != 2:
        raise types.EvaluationError("run record schemaVersion must be 2")
    legacy = copy.deepcopy(record)
    legacy["schemaVersion"] = 1
    legacy["runtime"]["harnessVersion"] = "5.5"
    arm = record.get("configuration", {}).get("arm", "unpaired")
    legacy["configuration"] = {
        "arm": arm,
        "configuredExecutionClass": "unknown",
        "configuredRouteRef": None,
        "configuredAgentRefs": [],
        "configuredSkillRefs": [],
        "qualityPolicyRefs": [],
        "observedExecution": {
            "executionClass": "unknown",
            "routeRef": None,
            "agentRefs": [],
            "skillRefs": [],
            "source": "unknown",
        },
    }
    legacy["result"] = {
        "resultFingerprint": None,
        "verificationProfileFingerprint": record.get("result", {}).get("verificationProfileFingerprint"),
        "processCleanupVerified": record.get("result", {}).get("processCleanupVerified"),
    }
    types._validate_run_record_v1(legacy, verify_hash=False)
    if record["runtime"]["harnessVersion"] != "6.0":
        raise types.EvaluationError("runtime.harnessVersion must be 6.0")
    _validate_configuration(record["configuration"])
    _validate_result(record["result"])
    if verify_hash:
        types.verify_integrity(record)
    return record


def validate_comparison_plan(value: Any) -> dict[str, Any]:
    plan = types._require_object(value, "comparison plan")
    fields = {
        "schemaVersion",
        "primaryOutcome",
        "correctnessGate",
        "secondaryOutcomes",
        "verificationProfileFingerprint",
        "intervention",
        "taskStratum",
        "patchScopeProfileFingerprint",
    }
    types._require_keys(plan, fields, fields, "comparison plan")
    if plan["schemaVersion"] != 2:
        raise types.EvaluationError("comparison plan schemaVersion must be 2")
    legacy = {key: copy.deepcopy(plan[key]) for key in (
        "primaryOutcome", "correctnessGate", "secondaryOutcomes", "verificationProfileFingerprint"
    )}
    legacy["schemaVersion"] = 1
    types._validate_comparison_plan_v1(legacy)
    intervention = types._require_object(plan["intervention"], "comparison plan intervention")
    types._require_keys(
        intervention,
        {"expectedChangedFactors", "attributionTarget"},
        {"expectedChangedFactors", "attributionTarget"},
        "comparison plan intervention",
    )
    factors = intervention["expectedChangedFactors"]
    if not isinstance(factors, list) or any(item not in FACTORS for item in factors) or len(factors) != len(set(factors)):
        raise types.EvaluationError("intervention.expectedChangedFactors must be a unique factor array")
    target = types._require_enum(intervention["attributionTarget"], ATTRIBUTION_TARGETS, "intervention.attributionTarget")
    if target == "single-factor" and len(factors) != 1:
        raise types.EvaluationError("single-factor attribution requires exactly one expected factor")
    stratum = _validate_task_stratum(plan["taskStratum"])
    if stratum["category"] == "unknown" and target != "descriptive-only":
        raise types.EvaluationError("attribution plans require a predeclared task category")
    fingerprint = plan["patchScopeProfileFingerprint"]
    if fingerprint is not None and (not isinstance(fingerprint, str) or not types.HASH_RE.fullmatch(fingerprint)):
        raise types.EvaluationError("patchScopeProfileFingerprint must be null or a digest")
    return plan


def _validate_task_stratum(value: Any, label: str = "taskStratum") -> dict[str, Any]:
    item = types._require_object(value, label)
    fields = {"category", "complexityLevel", "impactLevel", "uncertaintyLevel", "scopeClass"}
    types._require_keys(item, fields, fields, label)
    types._require_enum(item["category"], types.TASK_CATEGORIES, f"{label}.category")
    for key in ("complexityLevel", "impactLevel", "uncertaintyLevel"):
        types._require_enum(item[key], types.LEVELS, f"{label}.{key}")
    types._require_enum(item["scopeClass"], SCOPE_CLASSES, f"{label}.scopeClass")
    return item


def validate_comparison_record(value: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    record = types._require_object(value, "comparison record")
    if record.get("schemaVersion") != 2:
        raise types.EvaluationError("comparison record schemaVersion must be 2")
    additional = {
        "taskStratum",
        "configurationDelta",
        "protocolDeviations",
        "resultFingerprintComplete",
        "evaluationStratumFingerprint",
        "derivedViewFingerprints",
    }
    legacy = copy.deepcopy(record)
    for key in additional:
        legacy.pop(key, None)
    legacy["schemaVersion"] = 1
    types._validate_comparison_record_v1(legacy, verify_hash=False)
    _validate_task_stratum(record["taskStratum"])
    delta = _validate_configuration_delta(record["configurationDelta"])
    deviations = record["protocolDeviations"]
    if not isinstance(deviations, list):
        raise types.EvaluationError("protocolDeviations must be an array")
    deviation_fields = {"field", "code", "expectedFingerprint", "observedFingerprint"}
    for index, item in enumerate(deviations):
        item = types._require_object(item, f"protocolDeviations[{index}]")
        types._require_keys(item, deviation_fields, deviation_fields, f"protocolDeviations[{index}]")
        if not isinstance(item["field"], str) or not item["field"] or not isinstance(item["code"], str) or not item["code"]:
            raise types.EvaluationError("protocol deviation field and code must be non-empty")
        for key in ("expectedFingerprint", "observedFingerprint"):
            if item[key] is not None and (not isinstance(item[key], str) or not types.HASH_RE.fullmatch(item[key])):
                raise types.EvaluationError(f"protocol deviation {key} must be null or a digest")
    if delta["protocolMatch"] != (not deviations):
        raise types.EvaluationError("configurationDelta.protocolMatch must agree with protocolDeviations")
    if not isinstance(record["resultFingerprintComplete"], bool):
        raise types.EvaluationError("resultFingerprintComplete must be boolean")
    if (
        not isinstance(record["evaluationStratumFingerprint"], str)
        or not types.HASH_RE.fullmatch(record["evaluationStratumFingerprint"])
    ):
        raise types.EvaluationError("evaluationStratumFingerprint must be a digest")
    view_fingerprints = types._require_object(
        record["derivedViewFingerprints"], "derivedViewFingerprints"
    )
    types._require_keys(
        view_fingerprints,
        {"baseline", "treatment"},
        {"baseline", "treatment"},
        "derivedViewFingerprints",
    )
    for key in ("baseline", "treatment"):
        if (
            not isinstance(view_fingerprints[key], str)
            or not types.HASH_RE.fullmatch(view_fingerprints[key])
        ):
            raise types.EvaluationError(f"derivedViewFingerprints.{key} must be a digest")
    if verify_hash:
        types.verify_integrity(record)
    return record


def _validate_configuration_delta(value: Any) -> dict[str, Any]:
    delta = types._require_object(value, "configurationDelta")
    fields = {
        "state",
        "changedFactors",
        "addedAgentRefs",
        "removedAgentRefs",
        "addedSkillRefs",
        "removedSkillRefs",
        "deltaFingerprint",
        "changedFactorCount",
        "attributionScope",
        "protocolMatch",
    }
    types._require_keys(delta, fields, fields, "configurationDelta")
    state = types._require_enum(
        delta["state"], {"measured", "unavailable"}, "configurationDelta.state"
    )
    changed = delta["changedFactors"]
    if not isinstance(changed, list):
        raise types.EvaluationError("configurationDelta.changedFactors must be an array")
    seen: set[str] = set()
    for index, item in enumerate(changed):
        item = types._require_object(item, f"changedFactors[{index}]")
        types._require_keys(item, {"factor", "baseline", "treatment"}, {"factor", "baseline", "treatment"}, f"changedFactors[{index}]")
        factor = types._require_enum(item["factor"], FACTORS, f"changedFactors[{index}].factor")
        if factor in seen or item["baseline"] == item["treatment"]:
            raise types.EvaluationError("changed factors must be unique and materially different")
        seen.add(factor)
    if delta["changedFactorCount"] != len(changed):
        raise types.EvaluationError("configurationDelta.changedFactorCount is inconsistent")
    expected_scope = "none" if not changed else "single-factor" if len(changed) == 1 else "bundle"
    if delta["attributionScope"] != expected_scope:
        raise types.EvaluationError("configurationDelta.attributionScope is inconsistent")
    for key, kind in (("addedAgentRefs", "agent"), ("removedAgentRefs", "agent"), ("addedSkillRefs", "skill"), ("removedSkillRefs", "skill")):
        refs = delta[key]
        if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref.startswith(kind + ":") or not types.PSEUDONYM_RE.fullmatch(ref) for ref in refs):
            raise types.EvaluationError(f"configurationDelta.{key} contains invalid references")
    fingerprint = delta["deltaFingerprint"]
    if state == "unavailable" and (
        changed
        or delta["changedFactorCount"] != 0
        or delta["attributionScope"] != "none"
        or fingerprint is not None
        or delta["protocolMatch"] is not False
        or any(delta[key] for key in (
            "addedAgentRefs", "removedAgentRefs", "addedSkillRefs", "removedSkillRefs"
        ))
    ):
        raise types.EvaluationError("unavailable configurationDelta cannot claim a change")
    if state == "measured" and changed and (not isinstance(fingerprint, str) or not types.HASH_RE.fullmatch(fingerprint)):
        raise types.EvaluationError("changed configuration delta requires a fingerprint")
    if not changed and fingerprint is not None:
        raise types.EvaluationError("empty configuration delta fingerprint must be null")
    if not isinstance(delta["protocolMatch"], bool):
        raise types.EvaluationError("configurationDelta.protocolMatch must be boolean")
    return delta


def validate_annotation(value: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    annotation = types._require_object(value, "annotation")
    fields = {
        "schemaVersion", "annotationId", "repositoryId", "runId", "createdAt",
        "supersedesAnnotationId", "source", "acceptance", "correctionCount",
        "reopened", "freeTextStored", "integrity",
    }
    types._require_keys(annotation, fields, fields, "annotation")
    if annotation["schemaVersion"] != 2:
        raise types.EvaluationError("annotation schemaVersion must be 2")
    for key in ("annotationId", "repositoryId", "runId"):
        types._require_uuid(annotation[key], key)
    types._require_nullable_uuid(annotation["supersedesAnnotationId"], "supersedesAnnotationId")
    types._require_timestamp(annotation["createdAt"], "createdAt")
    if annotation["source"] != "user":
        raise types.EvaluationError("annotation source must be user")
    if annotation["acceptance"] not in {"accepted", "accepted-with-corrections", "rejected", "unknown"}:
        raise types.EvaluationError("annotation acceptance is invalid")
    types.validate_measurement(annotation["correctionCount"], "annotation.correctionCount")
    correction = annotation["correctionCount"]
    if correction["state"] == "measured" and (
        isinstance(correction["value"], bool)
        or not isinstance(correction["value"], int)
        or correction["value"] < 0
        or correction["unit"] != "count"
        or correction["source"] != "user-annotation"
        or correction["fidelity"] != "reported"
        or correction["completeness"] != "complete"
    ):
        raise types.EvaluationError("annotation correction count has invalid value or provenance")
    if correction["state"] != "measured" and correction != types.unavailable("count"):
        raise types.EvaluationError("unavailable annotation correction count must use canonical provenance")
    if annotation["acceptance"] == "accepted-with-corrections" and (
        correction["state"] != "measured" or correction["value"] < 1
    ):
        raise types.EvaluationError("accepted-with-corrections requires at least one correction")
    if not isinstance(annotation["reopened"], bool) or annotation["freeTextStored"] is not False:
        raise types.EvaluationError("annotation reopened/freeTextStored fields are invalid")
    if verify_hash:
        types.verify_integrity(annotation)
    return annotation


def validate_observation_record(value: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    record = types._require_object(value, "observation record")
    common = {
        "schemaVersion", "observationId", "repositoryId", "runId", "createdAt",
        "lifecycle", "provenance", "privacy", "integrity",
    }
    lifecycle = record.get("lifecycle")
    kind = lifecycle.get("kind") if isinstance(lifecycle, dict) else None
    allowed = common if kind == "withdrawal" else common | {"payload"}
    types._require_keys(record, allowed, allowed, "observation record")
    if record["schemaVersion"] != 1:
        raise types.EvaluationError("observation schemaVersion must be 1")
    for key in ("observationId", "repositoryId", "runId"):
        types._require_uuid(record[key], key)
    types._require_timestamp(record["createdAt"], "createdAt")
    lifecycle = types._require_object(record["lifecycle"], "observation lifecycle")
    types._require_keys(lifecycle, {"kind", "supersedesObservationId"}, {"kind", "supersedesObservationId"}, "observation lifecycle")
    kind = types._require_enum(lifecycle["kind"], {"supplement", "replacement", "withdrawal"}, "observation lifecycle kind")
    target = lifecycle["supersedesObservationId"]
    if kind == "supplement":
        if target is not None:
            raise types.EvaluationError("supplement cannot supersede another observation")
    else:
        types._require_uuid(target, "supersedesObservationId")
    provenance = types._require_object(record["provenance"], "observation provenance")
    types._require_keys(provenance, {"source", "fidelity", "completeness"}, {"source", "fidelity", "completeness"}, "observation provenance")
    source = types._require_enum(provenance["source"], OBSERVATION_SOURCES, "observation provenance source")
    fidelity = types._require_enum(provenance["fidelity"], {"exact", "reported", "derived"}, "observation provenance fidelity")
    types._require_enum(provenance["completeness"], REFERENCE_COMPLETENESS, "observation provenance completeness")
    if source in {"user-report", "agent-report"} and fidelity != "reported":
        raise types.EvaluationError("reported observations require reported fidelity")
    privacy = types._require_object(record["privacy"], "observation privacy")
    privacy_fields = {"rawReportStored", "freeTextStored", "rawComponentNamesStored"}
    types._require_keys(privacy, privacy_fields, privacy_fields, "observation privacy")
    if any(privacy[key] is not False for key in privacy_fields):
        raise types.EvaluationError("observation records must not retain raw report content")
    if kind != "withdrawal":
        payload = _validate_observation_payload(record["payload"])
        expected_measurement_source = {
            "user-report": "user-report",
            "agent-report": "agent-report",
            "verification-runner": "verification-runner",
        }.get(source)
        if expected_measurement_source is not None:
            for measurement in payload["measurements"].values():
                if measurement["state"] == "measured" and measurement["source"] != expected_measurement_source:
                    raise types.EvaluationError("observation measurement provenance does not match its source")
    if verify_hash:
        types.verify_integrity(record)
    return record


def _validate_observation_payload(value: Any) -> dict[str, Any]:
    payload = types._require_object(value, "observation payload")
    payload_fields = {"observedExecution", "measurements", "verification"}
    types._require_keys(payload, payload_fields, payload_fields, "observation payload")
    observed = types._require_object(payload["observedExecution"], "observation observedExecution")
    fields = {"executionClass", "route", "agents", "skills", "independentReview"}
    types._require_keys(observed, fields, fields, "observation observedExecution")
    validate_value_observation(observed["executionClass"], "observation executionClass")
    validate_reference_set(observed["route"], "observation route")
    validate_reference_set(observed["agents"], "observation agents")
    validate_reference_set(observed["skills"], "observation skills")
    validate_value_observation(observed["independentReview"], "observation independentReview")
    measurements = types._require_object(payload["measurements"], "observation measurements")
    allowed = {
        "wallTimeMs", "processExitCode", "inputTokens", "cachedInputTokens",
        "outputTokens", "reasoningOutputTokens", "commandExecutions", "mcpToolCalls",
        "webSearches", "fileChanges", "subagentRuns", "retryCount",
    }
    unknown = set(measurements) - allowed
    if unknown:
        raise types.EvaluationError("observation measurements contain unknown fields")
    for key, measurement_value in measurements.items():
        types.validate_measurement(measurement_value, f"observation measurements.{key}")
    verification = payload["verification"]
    if not isinstance(verification, list):
        raise types.EvaluationError("observation verification must be an array")
    for index, check in enumerate(verification):
        check = types._require_object(check, f"observation verification[{index}]")
        fields = {"checkRef", "kind", "result", "exitCode"}
        types._require_keys(check, fields, fields, f"observation verification[{index}]")
        if not isinstance(check["checkRef"], str) or not types.PSEUDONYM_RE.fullmatch(check["checkRef"]):
            raise types.EvaluationError("observation verification checkRef must be a pseudonym")
        types._require_enum(check["kind"], {"unit-test", "integration-test", "lint", "type-check", "schema", "custom"}, "observation verification kind")
        types._require_enum(check["result"], {"passed", "failed", "not-run", "unknown"}, "observation verification result")
        types.validate_measurement(check["exitCode"], "observation verification exitCode")
    return payload


def validate_manual_report(value: Any) -> dict[str, Any]:
    report = types._require_object(value, "manual observation report")
    fields = {"schemaVersion", "captureMode", "observedExecution", "measurements", "verification"}
    types._require_keys(report, fields, fields, "manual observation report")
    if report["schemaVersion"] != 1 or report["captureMode"] not in {"user-reported", "agent-reported"}:
        raise types.EvaluationError("manual report schemaVersion/captureMode is invalid")
    observed = types._require_object(report["observedExecution"], "manual report observedExecution")
    observed_fields = {"executionClass", "routeRef", "agentRefs", "skillRefs", "independentReview", "completeness"}
    types._require_keys(observed, observed_fields, observed_fields, "manual report observedExecution")
    if observed["executionClass"] is not None:
        types._require_enum(observed["executionClass"], types.EXECUTION_CLASSES - {"unknown"}, "manual report executionClass")
    if observed["routeRef"] is not None and (not isinstance(observed["routeRef"], str) or not LOGICAL_ID_RE.fullmatch(observed["routeRef"])):
        raise types.EvaluationError("manual report routeRef must be a logical ID or null")
    for key in ("agentRefs", "skillRefs"):
        refs = observed[key]
        if refs is not None and (not isinstance(refs, list) or any(not isinstance(ref, str) or not LOGICAL_ID_RE.fullmatch(ref) for ref in refs) or len(refs) != len(set(refs))):
            raise types.EvaluationError(f"manual report {key} must be null or unique logical IDs")
    if observed["independentReview"] is not None and not isinstance(observed["independentReview"], bool):
        raise types.EvaluationError("manual report independentReview must be boolean or null")
    types._require_enum(observed["completeness"], {"complete", "partial", "unknown"}, "manual report completeness")
    measurements = types._require_object(report["measurements"], "manual report measurements")
    source = "user-report" if report["captureMode"] == "user-reported" else "agent-report"
    for key, item in measurements.items():
        if key not in {
            "wallTimeMs", "processExitCode", "inputTokens", "cachedInputTokens", "outputTokens",
            "reasoningOutputTokens", "commandExecutions", "mcpToolCalls", "webSearches",
            "fileChanges", "subagentRuns", "retryCount",
        }:
            raise types.EvaluationError(f"manual report contains unknown measurement {key}")
        types.validate_measurement(item, f"manual report measurements.{key}")
        if item["state"] == "measured" and (item["source"] != source or item["fidelity"] != "reported"):
            raise types.EvaluationError("manual report measured values require matching reported provenance")
    if not isinstance(report["verification"], list):
        raise types.EvaluationError("manual report verification must be an array")
    for item in report["verification"]:
        if not isinstance(item, dict) or set(item) != {"id", "kind", "result", "exitCode"}:
            raise types.EvaluationError("manual report verification fields are invalid")
        if not isinstance(item["id"], str) or not LOGICAL_ID_RE.fullmatch(item["id"]):
            raise types.EvaluationError("manual report verification id must be a logical ID")
        types._require_enum(item["kind"], {"unit-test", "integration-test", "lint", "type-check", "schema", "custom"}, "manual report verification kind")
        types._require_enum(item["result"], {"passed", "failed", "not-run", "unknown"}, "manual report verification result")
        types.validate_measurement(item["exitCode"], "manual report verification exitCode")
    return report


def validate_proposal_record(value: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    record = types._require_object(value, "proposal record")
    fields = {
        "schemaVersion", "proposalId", "repositoryId", "proposalType", "taskStratum",
        "candidateDelta", "evidence", "language", "status", "autoApplicable", "createdAt", "integrity",
    }
    types._require_keys(record, fields, fields, "proposal record")
    if record["schemaVersion"] != 2:
        raise types.EvaluationError("proposal schemaVersion must be 2")
    types._require_uuid(record["proposalId"], "proposalId")
    types._require_uuid(record["repositoryId"], "repositoryId")
    types._require_timestamp(record["createdAt"], "createdAt")
    types._require_enum(record["proposalType"], {"experiment-suggestion", "configuration-proposal", "bundle-proposal", "negative-signal", "no-change"}, "proposalType")
    _validate_task_stratum(record["taskStratum"])
    candidate = types._require_object(record["candidateDelta"], "candidateDelta")
    candidate_fields = {"attributionScope", "factor", "from", "to", "bundleFingerprint", "factors"}
    types._require_keys(candidate, candidate_fields, candidate_fields, "candidateDelta")
    scope = types._require_enum(candidate["attributionScope"], ATTRIBUTION_SCOPES, "candidateDelta.attributionScope")
    if scope == "single-factor":
        types._require_enum(candidate["factor"], FACTORS, "candidateDelta.factor")
        if candidate["from"] == candidate["to"] or candidate["bundleFingerprint"] is not None or candidate["factors"] != [candidate["factor"]]:
            raise types.EvaluationError("single-factor candidateDelta is inconsistent")
    elif scope == "bundle":
        if candidate["factor"] is not None or candidate["from"] is not None or candidate["to"] is not None:
            raise types.EvaluationError("bundle candidateDelta cannot contain a scalar factor")
        if not isinstance(candidate["bundleFingerprint"], str) or not types.HASH_RE.fullmatch(candidate["bundleFingerprint"]):
            raise types.EvaluationError("bundle candidateDelta requires a fingerprint")
        if not isinstance(candidate["factors"], list) or len(candidate["factors"]) < 2 or any(item not in FACTORS for item in candidate["factors"]):
            raise types.EvaluationError("bundle candidateDelta requires at least two factors")
    else:
        if any(candidate[key] is not None for key in ("factor", "from", "to", "bundleFingerprint")) or candidate["factors"] != []:
            raise types.EvaluationError("none candidateDelta must be empty")
    evidence = types._require_object(record["evidence"], "proposal evidence")
    evidence_fields = {
        "evidenceClass", "comparisonRefs", "pairCount", "wins", "losses", "ties",
        "medianPairedDelta", "direction", "supportStrength", "attributionScope",
        "protocolMatchRatio", "isolationCompleteRatio", "primaryOutcomeCompleteness",
        "criticalRegressionCount", "confounders", "thresholds",
    }
    types._require_keys(evidence, evidence_fields, evidence_fields, "proposal evidence")
    types._require_enum(evidence["evidenceClass"], types.EVIDENCE_CLASSES, "proposal evidenceClass")
    refs = evidence["comparisonRefs"]
    if not isinstance(refs, list):
        raise types.EvaluationError("proposal comparisonRefs must be an array")
    for ref in refs:
        types._require_uuid(ref, "proposal comparisonRef")
    for key in ("pairCount", "wins", "losses", "ties", "criticalRegressionCount"):
        if isinstance(evidence[key], bool) or not isinstance(evidence[key], int) or evidence[key] < 0:
            raise types.EvaluationError(f"proposal evidence {key} must be non-negative")
    if evidence["pairCount"] != len(refs) or evidence["wins"] + evidence["losses"] + evidence["ties"] != evidence["pairCount"]:
        raise types.EvaluationError("proposal evidence counts are inconsistent")
    types._require_number_or_null(evidence["medianPairedDelta"], "medianPairedDelta")
    types._require_enum(evidence["direction"], {"beneficial", "harmful", "mixed", "unknown"}, "proposal direction")
    types._require_enum(evidence["supportStrength"], types.SUPPORT_STRENGTHS, "proposal supportStrength")
    if evidence["attributionScope"] != scope:
        raise types.EvaluationError("proposal evidence attribution scope must match candidate")
    for key in ("protocolMatchRatio", "isolationCompleteRatio", "primaryOutcomeCompleteness"):
        if isinstance(evidence[key], bool) or not isinstance(evidence[key], (int, float)) or not 0 <= evidence[key] <= 1:
            raise types.EvaluationError(f"proposal evidence {key} must be between zero and one")
    if not isinstance(evidence["confounders"], list) or any(item not in types.CONFOUNDERS for item in evidence["confounders"]):
        raise types.EvaluationError("proposal confounders are invalid")
    thresholds = types._require_object(evidence["thresholds"], "proposal thresholds")
    threshold_fields = {"minimumPairs", "weakDirectionRatio", "moderateDirectionRatio", "strongDirectionRatio"}
    types._require_keys(thresholds, threshold_fields, threshold_fields, "proposal thresholds")
    if (
        isinstance(thresholds["minimumPairs"], bool)
        or not isinstance(thresholds["minimumPairs"], int)
        or thresholds["minimumPairs"] < 1
    ):
        raise types.EvaluationError("proposal thresholds.minimumPairs must be positive")
    for key in threshold_fields - {"minimumPairs"}:
        item = thresholds[key]
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not 0 <= item <= 1:
            raise types.EvaluationError(f"proposal thresholds.{key} must be between zero and one")
    language = types._require_object(record["language"], "proposal language")
    types._require_keys(language, {"causalClaimAllowed", "requiredSummaryCode"}, {"causalClaimAllowed", "requiredSummaryCode"}, "proposal language")
    if language != {"causalClaimAllowed": False, "requiredSummaryCode": "association-observed-causality-unconfirmed"}:
        raise types.EvaluationError("proposal language must remain non-causal")
    if record["autoApplicable"] is not False or record["status"] not in {"observed", "proposed", "rejected"}:
        raise types.EvaluationError("proposal status or autoApplicable is invalid")
    if record["proposalType"] in {"configuration-proposal", "bundle-proposal"}:
        expected_scope = "single-factor" if record["proposalType"] == "configuration-proposal" else "bundle"
        if scope != expected_scope or evidence["protocolMatchRatio"] != 1.0:
            raise types.EvaluationError("configuration proposals require matching observed attribution")
    if verify_hash:
        types.verify_integrity(record)
    return record
