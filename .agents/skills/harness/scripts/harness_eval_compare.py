#!/usr/bin/env python3
"""Deterministic paired comparison helpers for Harness evaluation records."""

from __future__ import annotations

from typing import Any

import harness_eval_types as types
import harness_eval_view as evaluation_view


class ComparisonError(types.EvaluationError):
    pass


def _measured(record: dict[str, Any], key: str) -> float | None:
    item = record["measurements"].get(key)
    if not isinstance(item, dict) or item.get("state") != "measured":
        return None
    value = item.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _verification_pass_rate(record: dict[str, Any]) -> float | None:
    checks = [
        check
        for check in record["outcome"].get("verification", [])
        if isinstance(check, dict) and check.get("result") in {"passed", "failed"}
    ]
    if not checks:
        return None
    return sum(check["result"] == "passed" for check in checks) / len(checks)


def outcome_value(
    record: dict[str, Any],
    metric: str,
    *,
    correction_count: float | None = None,
) -> float | None:
    if metric == "verification-pass-rate":
        return _verification_pass_rate(record)
    if metric == "critical-failure-rate":
        return 1.0 if record["outcome"].get("criticalFailure") else 0.0
    if metric == "correction-count":
        return correction_count
    if metric == "wall-time-ms":
        return _measured(record, "wallTimeMs")
    if metric == "output-tokens":
        return _measured(record, "outputTokens")
    raise ComparisonError(f"unsupported primary outcome: {metric}")


def _direction(delta: float, expected: str, minimum_effect: float) -> str:
    if delta == 0:
        return "tie"
    if abs(delta) < minimum_effect:
        return "tie"
    if expected == "higher-is-better":
        return "beneficial" if delta > 0 else "harmful"
    return "beneficial" if delta < 0 else "harmful"


def _same_or_gap(baseline: dict[str, Any], treatment: dict[str, Any], path: tuple[str, ...], gap: str) -> list[str]:
    left: Any = baseline
    right: Any = treatment
    for key in path:
        left = left.get(key) if isinstance(left, dict) else None
        right = right.get(key) if isinstance(right, dict) else None
    return [] if left is not None and left == right else [gap]


def _confounders(gaps: list[str]) -> list[str]:
    mapped = {
        "model": "model-version",
        "reasoning-effort": "reasoning-effort",
        "verification-profile": "test-coverage",
    }
    return sorted({mapped.get(gap, "isolation-gap") for gap in gaps})


def _patch_scope_confounders(
    baseline: dict[str, Any], treatment: dict[str, Any], planned_fingerprint: str | None
) -> set[str]:
    if planned_fingerprint is None:
        return set()
    confounders: set[str] = set()
    for arm, record in (("baseline", baseline), ("treatment", treatment)):
        patch_scope = record["result"]["patchScope"]
        if patch_scope["state"] == "measured":
            if patch_scope["profileFingerprint"] != planned_fingerprint:
                raise ComparisonError(
                    "patch-scope profile does not match the plan-bound comparison profile"
                )
            if patch_scope["completeness"] != "complete":
                confounders.add("missing-measurement")
            if arm == "baseline" and (
                not patch_scope["withinDeclaredScope"]
                or patch_scope["maximumChangedPathsExceeded"]
            ):
                confounders.add("baseline-patch-scope-violation")
        else:
            confounders.add("missing-measurement")
    return confounders


def _compare_runs_v1(
    *,
    baseline: dict[str, Any],
    treatment: dict[str, Any],
    plan: dict[str, Any],
    comparison_id: str,
    pair_id: str,
    repository_id: str,
    created_at: str,
    baseline_corrections: float | None = None,
    treatment_corrections: float | None = None,
) -> dict[str, Any]:
    types.validate_run_record(baseline)
    types.validate_run_record(treatment)
    types.validate_comparison_plan(plan)
    if baseline.get("schemaVersion") != 1 or treatment.get("schemaVersion") != 1:
        raise ComparisonError("legacy comparison plans require Schema 1 run records")
    if baseline["recordState"] != "completed" or treatment["recordState"] != "completed":
        raise ComparisonError("paired comparison requires completed records")
    if baseline["configuration"]["arm"] != "baseline":
        raise ComparisonError("baseline record arm must be baseline")
    if treatment["configuration"]["arm"] != "harness":
        raise ComparisonError("treatment record arm must be harness")
    if baseline["repository"]["repositoryId"] != repository_id or treatment["repository"]["repositoryId"] != repository_id:
        raise ComparisonError("paired records must belong to the requested repository")

    gaps: list[str] = []
    gaps.extend(_same_or_gap(baseline, treatment, ("task", "promptFingerprint"), "prompt-fingerprint"))
    gaps.extend(_same_or_gap(baseline, treatment, ("repository", "sourceSnapshotId"), "source-snapshot"))
    gaps.extend(_same_or_gap(baseline, treatment, ("runtime", "modelRef"), "model"))
    gaps.extend(_same_or_gap(baseline, treatment, ("runtime", "reasoningEffort"), "reasoning-effort"))
    gaps.extend(_same_or_gap(baseline, treatment, ("runtime", "sandbox"), "sandbox"))
    gaps.extend(
        _same_or_gap(
            baseline,
            treatment,
            ("result", "verificationProfileFingerprint"),
            "verification-profile",
        )
    )
    planned_verification = plan.get("verificationProfileFingerprint")
    if planned_verification is not None and (
        baseline["result"].get("verificationProfileFingerprint") != planned_verification
        or treatment["result"].get("verificationProfileFingerprint") != planned_verification
    ):
        gaps.append("verification-profile")
    for record, arm in ((baseline, "baseline"), (treatment, "treatment")):
        if record["comparison"].get("pairId") not in {None, pair_id}:
            gaps.append(f"{arm}-pair-id")
        if record["comparison"].get("isolationStatus") != "complete":
            gaps.append(f"{arm}-isolation")
        if not record["result"].get("processCleanupVerified"):
            gaps.append(f"{arm}-process-cleanup")
    isolation_failed = any(
        record["comparison"].get("isolationStatus") == "failed"
        for record in (baseline, treatment)
    )
    isolation_status = "failed" if isolation_failed else "complete" if not gaps else "partial"

    outcome = plan["primaryOutcome"]
    metric = outcome["metric"]
    baseline_value = outcome_value(baseline, metric, correction_count=baseline_corrections)
    treatment_value = outcome_value(treatment, metric, correction_count=treatment_corrections)
    if baseline_value is None or treatment_value is None:
        delta = None
        direction = "unknown"
        completeness = 0.0
    else:
        delta = treatment_value - baseline_value
        direction = _direction(delta, outcome["direction"], float(outcome["minimumEffect"]))
        completeness = 1.0

    baseline_rate = _verification_pass_rate(baseline)
    treatment_rate = _verification_pass_rate(treatment)
    correctness_regression = (
        baseline_rate is not None
        and treatment_rate is not None
        and treatment_rate < baseline_rate
    ) or (
        not baseline["outcome"].get("criticalFailure")
        and treatment["outcome"].get("criticalFailure")
    )
    gate_passed = plan["correctnessGate"] == "none" or not correctness_regression
    if not gate_passed and direction == "beneficial":
        direction = "harmful"

    instrumented_pair = all(
        record["capture"].get("captureMode") == "runtime-instrumented"
        for record in (baseline, treatment)
    )
    evidence_class = (
        "controlled-live-comparison"
        if isolation_status == "complete" and instrumented_pair
        else "paired-replay"
    )
    record = {
        "schemaVersion": 1,
        "comparisonId": comparison_id,
        "pairId": pair_id,
        "repositoryId": repository_id,
        "createdAt": created_at,
        "planSha256": types.digest_bytes(types.canonical_bytes(plan)),
        "baselineRunId": baseline["runId"],
        "treatmentRunId": treatment["runId"],
        "evidenceClass": evidence_class,
        "isolationStatus": isolation_status,
        "isolationGaps": sorted(set(gaps)),
        "primaryOutcome": {
            "metric": metric,
            "directionRule": outcome["direction"],
            "minimumEffect": outcome["minimumEffect"],
            "baselineValue": baseline_value,
            "treatmentValue": treatment_value,
            "delta": delta,
            "direction": direction,
            "completeness": completeness,
        },
        "correctnessGate": {
            "policy": plan["correctnessGate"],
            "passed": gate_passed,
            "criticalRegression": correctness_regression,
        },
        "confounders": _confounders(gaps),
        "causalClaimAllowed": False,
        "integrity": {"recordSha256": None},
    }
    sealed = types.seal_record(record)
    types.validate_comparison_record(sealed)
    return sealed


def _observation_value(item: Any) -> Any:
    if not isinstance(item, dict) or item.get("state") != "measured":
        return None
    return item.get("value") if "value" in item else item.get("refs")


def _factor_values(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    configuration = record["configuration"]
    declared = configuration["declaredConfiguration"]
    expected = configuration["expectedExecution"]
    return {
        "execution-class": expected["executionClass"],
        "route": declared["route"],
        "agent-set": declared["agents"],
        "skill-set": declared["skills"],
        "quality-policy-set": declared["qualityPolicies"],
        "independent-review": declared["independentReview"],
        "change-discipline-version": declared["changeDisciplineVersion"],
        "project-harness-content": declared["projectHarnessFingerprint"],
    }


def _configuration_delta(
    baseline: dict[str, Any], treatment: dict[str, Any], plan: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    left = _factor_values(baseline)
    right = _factor_values(treatment)
    asymmetric_unknown = [
        factor
        for factor in sorted(left)
        if left[factor].get("state") != right[factor].get("state")
        and "unavailable" in {left[factor].get("state"), right[factor].get("state")}
    ]
    if asymmetric_unknown:
        return (
            {
                "state": "unavailable",
                "changedFactors": [],
                "addedAgentRefs": [],
                "removedAgentRefs": [],
                "addedSkillRefs": [],
                "removedSkillRefs": [],
                "deltaFingerprint": None,
                "changedFactorCount": 0,
                "attributionScope": "none",
                "protocolMatch": False,
            },
            [{
                "field": "configurationDelta",
                "code": "configuration-delta-unavailable",
                "expectedFingerprint": types.digest_bytes(types.canonical_bytes(sorted(plan["intervention"]["expectedChangedFactors"]))),
                "observedFingerprint": None,
            }],
        )
    left_values = {factor: _observation_value(item) for factor, item in left.items()}
    right_values = {factor: _observation_value(item) for factor, item in right.items()}
    changed = [
        {"factor": factor, "baseline": left_values[factor], "treatment": right_values[factor]}
        for factor in sorted(left_values)
        if left_values[factor] != right_values[factor]
    ]
    factors = {item["factor"] for item in changed}
    expected = set(plan["intervention"]["expectedChangedFactors"])
    protocol_match = factors == expected
    canonical = types.canonical_bytes(changed)
    fingerprint = types.digest_bytes(canonical) if changed else None
    baseline_agents = set(left_values.get("agent-set") or [])
    treatment_agents = set(right_values.get("agent-set") or [])
    baseline_skills = set(left_values.get("skill-set") or [])
    treatment_skills = set(right_values.get("skill-set") or [])
    scope = "none" if not changed else "single-factor" if len(changed) == 1 else "bundle"
    deviations = []
    if not protocol_match:
        deviations.append(
            {
                "field": "configurationDelta.changedFactors",
                "code": "declared-intervention-mismatch",
                "expectedFingerprint": types.digest_bytes(types.canonical_bytes(sorted(expected))),
                "observedFingerprint": types.digest_bytes(types.canonical_bytes(sorted(factors))),
            }
        )
    return (
        {
            "state": "measured",
            "changedFactors": changed,
            "addedAgentRefs": sorted(treatment_agents - baseline_agents),
            "removedAgentRefs": sorted(baseline_agents - treatment_agents),
            "addedSkillRefs": sorted(treatment_skills - baseline_skills),
            "removedSkillRefs": sorted(baseline_skills - treatment_skills),
            "deltaFingerprint": fingerprint,
            "changedFactorCount": len(changed),
            "attributionScope": scope,
            "protocolMatch": protocol_match,
        },
        deviations,
    )


def _execution_protocol_deviations(record: dict[str, Any], arm: str) -> list[dict[str, Any]]:
    expected = record["configuration"]["expectedExecution"]
    observed = record["configuration"]["observedExecution"]
    deviations: list[dict[str, Any]] = []
    for key in ("executionClass", "route", "agents", "skills", "independentReview"):
        left = expected[key]
        right = observed[key]
        if left.get("state") != "measured" or right.get("state") != "measured":
            continue
        left_value = _observation_value(left)
        right_value = _observation_value(right)
        if left_value == right_value:
            continue
        deviations.append(
            {
                "field": f"{arm}.expectedExecution.{key}",
                "code": "expected-observed-mismatch",
                "expectedFingerprint": types.digest_bytes(types.canonical_bytes(left_value)),
                "observedFingerprint": types.digest_bytes(types.canonical_bytes(right_value)),
            }
        )
    return deviations


def _compare_runs_v2(
    *,
    baseline: dict[str, Any],
    treatment: dict[str, Any],
    plan: dict[str, Any],
    comparison_id: str,
    pair_id: str,
    repository_id: str,
    created_at: str,
    baseline_corrections: float | None = None,
    treatment_corrections: float | None = None,
    baseline_view: dict[str, Any] | None = None,
    treatment_view: dict[str, Any] | None = None,
) -> dict[str, Any]:
    types.validate_run_record(baseline)
    types.validate_run_record(treatment)
    types.validate_comparison_plan(plan)
    if baseline["schemaVersion"] != 2 or treatment["schemaVersion"] != 2:
        raise ComparisonError("Schema 2 comparisons cannot mix legacy run records")
    if baseline["recordState"] != "completed" or treatment["recordState"] != "completed":
        raise ComparisonError("paired comparison requires completed records")
    if baseline["configuration"]["arm"] != "baseline" or treatment["configuration"]["arm"] != "harness":
        raise ComparisonError("paired comparison requires baseline and harness arms")
    if baseline["repository"]["repositoryId"] != repository_id or treatment["repository"]["repositoryId"] != repository_id:
        raise ComparisonError("paired records must belong to the requested repository")

    baseline_view = baseline_view or evaluation_view.derived_evaluation_view(baseline, [], [])
    treatment_view = treatment_view or evaluation_view.derived_evaluation_view(treatment, [], [])
    effective_baseline = evaluation_view.materialize_run_view(baseline, baseline_view)
    effective_treatment = evaluation_view.materialize_run_view(treatment, treatment_view)

    gaps: list[str] = []
    gaps.extend(_same_or_gap(baseline, treatment, ("task", "promptFingerprint"), "prompt-fingerprint"))
    gaps.extend(_same_or_gap(baseline, treatment, ("repository", "sourceSnapshotId"), "source-snapshot"))
    gaps.extend(_same_or_gap(baseline, treatment, ("runtime", "modelRef"), "model"))
    gaps.extend(_same_or_gap(baseline, treatment, ("runtime", "codexVersion"), "codex-version"))
    gaps.extend(_same_or_gap(baseline, treatment, ("runtime", "reasoningEffort"), "reasoning-effort"))
    gaps.extend(_same_or_gap(baseline, treatment, ("runtime", "platform"), "platform"))
    gaps.extend(_same_or_gap(baseline, treatment, ("runtime", "sandbox"), "sandbox"))
    gaps.extend(_same_or_gap(baseline, treatment, ("capture", "captureMode"), "capture-mode"))
    gaps.extend(_same_or_gap(baseline, treatment, ("result", "verificationProfileFingerprint"), "verification-profile"))
    planned_verification = plan["verificationProfileFingerprint"]
    if planned_verification is not None and any(
        record["result"]["verificationProfileFingerprint"] != planned_verification
        for record in (baseline, treatment)
    ):
        gaps.append("verification-profile")
    for record, arm in ((baseline, "baseline"), (treatment, "treatment")):
        if record["comparison"]["pairId"] not in {None, pair_id}:
            gaps.append(f"{arm}-pair-id")
        if record["comparison"]["isolationStatus"] != "complete":
            gaps.append(f"{arm}-isolation")
            gaps.extend(
                f"{arm}-{gap}"
                for gap in record["comparison"]["isolationGaps"]
                if gap.startswith("verification-")
            )
        if not record["result"]["processCleanupVerified"]:
            gaps.append(f"{arm}-process-cleanup")
    isolation_failed = any(record["comparison"]["isolationStatus"] == "failed" for record in (baseline, treatment))
    isolation_status = "failed" if isolation_failed else "complete" if not gaps else "partial"

    plan_sha256 = types.digest_bytes(types.canonical_bytes(plan))
    patch_scope_confounders = _patch_scope_confounders(
        effective_baseline,
        effective_treatment,
        plan["patchScopeProfileFingerprint"],
    )
    outcome = plan["primaryOutcome"]
    baseline_value = outcome_value(effective_baseline, outcome["metric"], correction_count=baseline_corrections)
    treatment_value = outcome_value(effective_treatment, outcome["metric"], correction_count=treatment_corrections)
    if baseline_value is None or treatment_value is None:
        delta_value = None
        direction = "unknown"
        completeness = 0.0
    else:
        delta_value = treatment_value - baseline_value
        direction = _direction(delta_value, outcome["direction"], float(outcome["minimumEffect"]))
        completeness = 1.0
    baseline_rate = _verification_pass_rate(effective_baseline)
    treatment_rate = _verification_pass_rate(effective_treatment)
    regression = (
        baseline_rate is not None and treatment_rate is not None and treatment_rate < baseline_rate
    ) or (not baseline["outcome"]["criticalFailure"] and treatment["outcome"]["criticalFailure"])
    gate_passed = plan["correctnessGate"] == "none" or not regression
    if not gate_passed and direction == "beneficial":
        direction = "harmful"

    configuration_delta, deviations = _configuration_delta(effective_baseline, effective_treatment, plan)
    deviations.extend(_execution_protocol_deviations(effective_baseline, "baseline"))
    deviations.extend(_execution_protocol_deviations(effective_treatment, "treatment"))
    if deviations:
        configuration_delta["protocolMatch"] = False
    instrumented = all(record["capture"]["captureMode"] == "runtime-instrumented" for record in (baseline, treatment))
    evidence_class = "controlled-live-comparison" if isolation_status == "complete" and instrumented else "paired-replay"
    fingerprints_complete = all(
        record["result"]["resultFingerprint"]["state"] == "measured"
        and record["result"]["resultFingerprint"]["completeness"] == "complete"
        for record in (baseline, treatment)
    )
    evaluation_stratum_fingerprint = types.digest_bytes(types.canonical_bytes({
        "repositoryId": repository_id,
        "planSha256": plan_sha256,
        "taskStratum": plan["taskStratum"],
        "primaryOutcome": plan["primaryOutcome"],
        "configurationDeltaFingerprint": configuration_delta["deltaFingerprint"],
        "runtime": [
            {
                "harnessVersion": record["runtime"]["harnessVersion"],
                "modelRef": record["runtime"]["modelRef"],
                "codexVersion": record["runtime"]["codexVersion"],
                "reasoningEffort": record["runtime"]["reasoningEffort"],
                "platform": record["runtime"]["platform"],
                "sandbox": record["runtime"]["sandbox"],
                "captureMode": record["capture"]["captureMode"],
                "verificationProfileFingerprint": record["result"]["verificationProfileFingerprint"],
            }
            for record in (baseline, treatment)
        ],
    }))
    record = {
        "schemaVersion": 2,
        "comparisonId": comparison_id,
        "pairId": pair_id,
        "repositoryId": repository_id,
        "createdAt": created_at,
        "planSha256": plan_sha256,
        "baselineRunId": baseline["runId"],
        "treatmentRunId": treatment["runId"],
        "evidenceClass": evidence_class,
        "isolationStatus": isolation_status,
        "isolationGaps": sorted(set(gaps)),
        "primaryOutcome": {
            "metric": outcome["metric"],
            "directionRule": outcome["direction"],
            "minimumEffect": outcome["minimumEffect"],
            "baselineValue": baseline_value,
            "treatmentValue": treatment_value,
            "delta": delta_value,
            "direction": direction,
            "completeness": completeness,
        },
        "correctnessGate": {
            "policy": plan["correctnessGate"],
            "passed": gate_passed,
            "criticalRegression": regression,
        },
        "confounders": sorted(set(_confounders(gaps)) | patch_scope_confounders),
        "causalClaimAllowed": False,
        "taskStratum": plan["taskStratum"],
        "configurationDelta": configuration_delta,
        "protocolDeviations": deviations,
        "resultFingerprintComplete": fingerprints_complete,
        "evaluationStratumFingerprint": evaluation_stratum_fingerprint,
        "derivedViewFingerprints": {
            "baseline": types.digest_bytes(types.canonical_bytes(baseline_view)),
            "treatment": types.digest_bytes(types.canonical_bytes(treatment_view)),
        },
        "integrity": {"recordSha256": None},
    }
    sealed = types.seal_record(record)
    types.validate_comparison_record(sealed)
    return sealed


def compare_runs(**kwargs: Any) -> dict[str, Any]:
    plan = kwargs.get("plan")
    if isinstance(plan, dict) and plan.get("schemaVersion") == 1:
        return _compare_runs_v1(**kwargs)
    return _compare_runs_v2(**kwargs)
