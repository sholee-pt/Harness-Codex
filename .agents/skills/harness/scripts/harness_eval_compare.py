#!/usr/bin/env python3
"""Deterministic paired comparison helpers for Harness evaluation records."""

from __future__ import annotations

from typing import Any

import harness_eval_types as types


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


def compare_runs(
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
        "schemaVersion": types.COMPARISON_SCHEMA_VERSION,
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
