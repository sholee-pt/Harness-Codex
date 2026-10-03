#!/usr/bin/env python3
"""Compute non-persistent active evaluation views and lifecycle state."""

from __future__ import annotations

import copy
from typing import Any

import harness_eval_types as types


FIELD_AUTHORITY = {
    "observedExecution.executionClass": ["runtime-event", "user-report", "agent-report"],
    "observedExecution.route": ["runtime-event", "user-report", "agent-report"],
    "observedExecution.agents": ["runtime-event", "user-report", "agent-report"],
    "observedExecution.skills": ["runtime-event", "user-report", "agent-report"],
    "observedExecution.independentReview": ["runtime-event", "user-report", "agent-report"],
    "measurements.wallTimeMs": ["evaluator-clock", "user-report", "agent-report"],
    "measurements.processExitCode": ["process-exit", "verification-runner", "user-report", "agent-report"],
    "measurements.inputTokens": ["codex-jsonl"],
    "measurements.cachedInputTokens": ["codex-jsonl"],
    "measurements.outputTokens": ["codex-jsonl"],
    "measurements.reasoningOutputTokens": ["codex-jsonl"],
    "measurements.commandExecutions": ["codex-jsonl"],
    "measurements.mcpToolCalls": ["codex-jsonl"],
    "measurements.webSearches": ["codex-jsonl"],
    "measurements.fileChanges": ["codex-jsonl"],
    "measurements.subagentRuns": ["codex-jsonl", "user-report", "agent-report"],
    "measurements.retryCount": ["runtime-event", "user-report", "agent-report"],
}


def observation_graph(
    records: list[dict[str, Any]], *, repository_id: str, run_id: str
) -> dict[str, Any]:
    by_id: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for record in records:
        try:
            types.validate_observation_record(record)
        except types.EvaluationError as exc:
            conflicts.append({"code": "invalid-observation", "refs": [], "detail": type(exc).__name__})
            continue
        observation_id = record["observationId"]
        if observation_id in by_id:
            conflicts.append({"code": "duplicate-observation-id", "refs": [observation_id]})
            continue
        if record["repositoryId"] != repository_id or record["runId"] != run_id:
            conflicts.append({"code": "observation-scope-mismatch", "refs": [observation_id]})
            continue
        by_id[observation_id] = record

    successors: dict[str, list[str]] = {key: [] for key in by_id}
    for observation_id, record in by_id.items():
        target = record["lifecycle"]["supersedesObservationId"]
        if target is None:
            continue
        if target == observation_id:
            conflicts.append({"code": "self-supersession", "refs": [observation_id]})
        elif target not in by_id:
            conflicts.append({"code": "missing-supersession-target", "refs": [observation_id, target]})
        else:
            successors[target].append(observation_id)
            if by_id[target]["lifecycle"]["kind"] == "withdrawal":
                conflicts.append({"code": "withdrawal-superseded", "refs": [target, observation_id]})
    for target, children in successors.items():
        if len(children) > 1:
            conflicts.append({"code": "supersession-branch-conflict", "refs": [target, *sorted(children)]})

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            conflicts.append({"code": "supersession-cycle", "refs": [node]})
            return
        if node in visited:
            return
        visiting.add(node)
        target = by_id[node]["lifecycle"]["supersedesObservationId"]
        if target in by_id:
            visit(target)
        visiting.remove(node)
        visited.add(node)

    for observation_id in by_id:
        visit(observation_id)
    active = [
        record
        for observation_id, record in by_id.items()
        if not successors[observation_id] and record["lifecycle"]["kind"] != "withdrawal"
    ]
    active_ids = {record["observationId"] for record in active}
    inactive = sorted(set(by_id) - active_ids)
    return {"active": active, "inactive": inactive, "conflicts": conflicts, "byId": by_id}


def annotation_state(
    records: list[dict[str, Any]], *, repository_id: str, run_id: str
) -> dict[str, Any]:
    valid: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    legacy: list[dict[str, Any]] = []
    for record in records:
        try:
            types.validate_annotation(record)
        except types.EvaluationError:
            conflicts.append({"code": "invalid-annotation", "refs": []})
            continue
        if record["runId"] != run_id or (record.get("repositoryId") not in {None, repository_id}):
            conflicts.append({"code": "annotation-scope-mismatch", "refs": [record["annotationId"]]})
            continue
        valid[record["annotationId"]] = record
        if record["schemaVersion"] == 1:
            legacy.append(record)
    if len(legacy) >= 2:
        conflicts.append({"code": "annotation-conflict", "refs": sorted(item["annotationId"] for item in legacy)})
        return {"active": None, "inactive": sorted(valid), "conflicts": conflicts, "byId": valid}

    successors: dict[str, list[str]] = {key: [] for key in valid}
    roots: list[str] = [item["annotationId"] for item in legacy]
    for annotation_id, record in valid.items():
        if record["schemaVersion"] == 1:
            continue
        target = record["supersedesAnnotationId"]
        if target is None:
            roots.append(annotation_id)
        elif target not in valid:
            conflicts.append({"code": "missing-annotation-target", "refs": [annotation_id, target]})
        else:
            successors[target].append(annotation_id)
    for target, children in successors.items():
        if len(children) > 1:
            conflicts.append({"code": "annotation-branch-conflict", "refs": [target, *sorted(children)]})
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(annotation_id: str) -> None:
        if annotation_id in visiting:
            conflicts.append({"code": "annotation-cycle", "refs": [annotation_id]})
            return
        if annotation_id in visited:
            return
        visiting.add(annotation_id)
        record = valid[annotation_id]
        target = record.get("supersedesAnnotationId") if record.get("schemaVersion") == 2 else None
        if target in valid:
            visit(target)
        visiting.remove(annotation_id)
        visited.add(annotation_id)

    for annotation_id in valid:
        visit(annotation_id)
    if len(roots) > 1:
        conflicts.append({"code": "annotation-conflict", "refs": sorted(roots)})
    active_ids = [annotation_id for annotation_id in valid if not successors[annotation_id]]
    active = valid[active_ids[0]] if len(active_ids) == 1 and not conflicts else None
    inactive = sorted(set(valid) - ({active["annotationId"]} if active else set()))
    return {"active": active, "inactive": inactive, "conflicts": conflicts, "byId": valid}


def _reported_source(record: dict[str, Any]) -> str:
    return record["provenance"]["source"]


def _candidate_values(run: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    observed = run["configuration"]["observedExecution"]
    for key, item in observed.items():
        result[f"observedExecution.{key}"] = [{"value": item, "source": item.get("source", "none"), "ref": "run"}]
    for key, item in run["measurements"].items():
        result[f"measurements.{key}"] = [{"value": item, "source": item.get("source", "none"), "ref": "run"}]
    for check in run["outcome"]["verification"]:
        result[f"verification.{check['checkRef']}"] = [{
            "value": {
                "state": "measured",
                "value": check,
                "source": "verification-runner",
                "fidelity": "exact",
                "completeness": "complete",
            },
            "source": "verification-runner",
            "ref": "run",
        }]
    for observation in observations:
        source = _reported_source(observation)
        payload = observation["payload"]
        for key, item in payload["observedExecution"].items():
            result.setdefault(f"observedExecution.{key}", []).append(
                {"value": item, "source": source, "ref": f"observation:{observation['observationId']}"}
            )
        for key, item in payload["measurements"].items():
            result.setdefault(f"measurements.{key}", []).append(
                {"value": item, "source": source, "ref": f"observation:{observation['observationId']}"}
            )
        for check in payload["verification"]:
            result.setdefault(f"verification.{check['checkRef']}", []).append({
                "value": {
                    "state": "measured",
                    "value": check,
                    "source": source,
                    "fidelity": observation["provenance"]["fidelity"],
                    "completeness": observation["provenance"]["completeness"],
                },
                "source": source,
                "ref": f"observation:{observation['observationId']}",
            })
    return result


def _material(item: dict[str, Any]) -> Any:
    return item.get("value") if "value" in item else sorted(item["refs"]) if isinstance(item.get("refs"), list) else None


def observations_mismatch(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("state") != "measured" or right.get("state") != "measured":
        return False
    if "refs" in left and "refs" in right:
        left_refs, right_refs = set(left["refs"]), set(right["refs"])
        return (left.get("completeness") == "complete" and not right_refs <= left_refs
                or right.get("completeness") == "complete" and not left_refs <= right_refs)
    return _material(left) != _material(right)


def derived_evaluation_view(
    run: dict[str, Any], observations: list[dict[str, Any]], annotations: list[dict[str, Any]]
) -> dict[str, Any]:
    types.validate_run_record(run)
    repository_id = run["repository"]["repositoryId"]
    run_id = run["runId"]
    observation_state = observation_graph(observations, repository_id=repository_id, run_id=run_id)
    annotation_result = annotation_state(annotations, repository_id=repository_id, run_id=run_id)
    conflicts = list(observation_state["conflicts"]) + list(annotation_result["conflicts"])
    selected: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    for field, candidates in _candidate_values(run, observation_state["active"]).items():
        priorities = (
            ["verification-runner", "user-report", "agent-report"]
            if field.startswith("verification.")
            else FIELD_AUTHORITY.get(field, [])
        )
        admissible = [item for item in candidates if item["source"] in priorities and item["value"].get("state") == "measured"]
        if not admissible:
            selected[field] = None
            continue
        rank = min(priorities.index(item["source"]) for item in admissible)
        strongest = [item for item in admissible if priorities.index(item["source"]) == rank]
        if any(observations_mismatch(left["value"], right["value"])
               for index, left in enumerate(strongest) for right in strongest[index + 1:]):
            conflicts.append({"code": "observed-value-mismatch", "field": field, "refs": sorted(item["ref"] for item in strongest)})
            selected[field] = None
            continue
        chosen = next((item for item in strongest if item["value"].get("completeness") == "complete"), strongest[0])
        selected[field] = copy.deepcopy(chosen["value"])
        if "refs" in selected[field]:
            selected[field]["refs"] = sorted({ref for item in strongest for ref in item["value"]["refs"]})
        provenance[field] = {"source": chosen["source"], "ref": chosen["ref"]}
        if len(strongest) > 1:
            provenance[field]["supportingRefs"] = sorted({item["ref"] for item in strongest})

    deviations: list[dict[str, Any]] = []
    expected = run["configuration"]["expectedExecution"]
    for key in ("executionClass", "route", "agents", "skills", "independentReview"):
        expected_item = expected[key]
        observed_item = selected.get(f"observedExecution.{key}")
        if isinstance(observed_item, dict) and observations_mismatch(expected_item, observed_item):
            deviations.append({"field": key, "code": "expected-observed-mismatch"})
    active_annotation = annotation_result["active"]
    if active_annotation is not None:
        selected["userOutcome.acceptance"] = active_annotation["acceptance"]
        selected["userOutcome.correctionCount"] = active_annotation["correctionCount"]
        provenance["userOutcome"] = {"source": "user", "ref": f"annotation:{active_annotation['annotationId']}"}
    else:
        selected["userOutcome.acceptance"] = None
        selected["userOutcome.correctionCount"] = None

    eligibility_reasons: list[str] = []
    if conflicts:
        eligibility_reasons.append("active-conflict")
    if deviations:
        eligibility_reasons.append("protocol-deviation")
    if run["result"]["resultFingerprint"]["state"] != "measured":
        eligibility_reasons.append("result-fingerprint-incomplete")
    if run["comparison"]["isolationStatus"] == "failed":
        eligibility_reasons.append("isolation-failed")
    return {
        "schemaVersion": 1,
        "repositoryId": repository_id,
        "runId": run_id,
        "selectedValues": selected,
        "protocolDeviations": deviations,
        "activeConflicts": conflicts,
        "inactiveObservationRefs": observation_state["inactive"],
        "inactiveAnnotationRefs": annotation_result["inactive"],
        "provenanceSummary": provenance,
        "proposalEligible": not eligibility_reasons,
        "proposalIneligibilityReasons": sorted(set(eligibility_reasons)),
        "persisted": False,
    }


def materialize_run_view(run: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    """Overlay selected derived values on an in-memory run copy for comparison only."""
    if view.get("runId") != run.get("runId") or view.get("repositoryId") != run.get("repository", {}).get("repositoryId"):
        raise types.EvaluationError("derived view does not belong to the run")
    effective = copy.deepcopy(run)
    selected = view.get("selectedValues", {})
    for key in ("executionClass", "route", "agents", "skills", "independentReview"):
        item = selected.get(f"observedExecution.{key}")
        if isinstance(item, dict):
            effective["configuration"]["observedExecution"][key] = copy.deepcopy(item)
    for key in effective["measurements"]:
        item = selected.get(f"measurements.{key}")
        if isinstance(item, dict):
            effective["measurements"][key] = copy.deepcopy(item)
    checks = [
        copy.deepcopy(item["value"])
        for field, item in selected.items()
        if field.startswith("verification.")
        and isinstance(item, dict)
        and item.get("state") == "measured"
        and isinstance(item.get("value"), dict)
    ]
    if checks:
        effective["outcome"]["verification"] = sorted(checks, key=lambda item: item["checkRef"])
    return effective
