#!/usr/bin/env python3
"""Create non-binding, non-causal proposals from paired Harness evidence."""

from __future__ import annotations

import statistics
from typing import Any

import harness_eval_types as types


class ProposalError(types.EvaluationError):
    pass


def _support_strength(
    *,
    pair_count: int,
    same_direction_ratio: float,
    completeness: float,
    isolation_ratio: float,
    critical_regression: bool,
    isolation_failed: bool,
    confounders: set[str],
    effect_threshold_met: bool,
) -> str:
    if pair_count < 3 or completeness < 0.60 or isolation_failed:
        return "insufficient"
    if critical_regression:
        return "weak"
    if (
        pair_count >= 10
        and same_direction_ratio >= 0.80
        and completeness >= 0.90
        and isolation_ratio == 1.0
        and not confounders
        and effect_threshold_met
    ):
        return "strong"
    if (
        pair_count >= 5
        and same_direction_ratio >= 0.70
        and completeness >= 0.80
        and isolation_ratio >= 0.80
        and len(confounders) <= 2
    ):
        return "moderate"
    if pair_count >= 3 and same_direction_ratio >= 0.67:
        return "weak"
    return "insufficient"


def proposal_from_comparisons(
    *,
    repository_id: str,
    proposal_id: str,
    created_at: str,
    comparisons: list[dict[str, Any]],
    task_category: str = "unknown",
    complexity_level: str = "unknown",
    impact_level: str = "unknown",
) -> dict[str, Any]:
    valid: list[dict[str, Any]] = []
    for comparison in comparisons:
        types.verify_integrity(comparison)
        if comparison.get("repositoryId") != repository_id:
            continue
        if comparison.get("evidenceClass") not in {"paired-replay", "controlled-live-comparison"}:
            continue
        if comparison.get("primaryOutcome", {}).get("direction") == "unknown":
            continue
        valid.append(comparison)
    metrics = {item["primaryOutcome"]["metric"] for item in valid}
    if len(metrics) > 1:
        raise ProposalError("comparisons with different predeclared primary outcomes must be stratified")

    directions = [item["primaryOutcome"]["direction"] for item in valid]
    beneficial = directions.count("beneficial")
    harmful = directions.count("harmful")
    ties = directions.count("tie")
    non_ties = beneficial + harmful
    dominant = max(beneficial, harmful)
    ratio = dominant / non_ties if non_ties else 0.0
    deltas = [
        float(item["primaryOutcome"]["delta"])
        for item in valid
        if isinstance(item["primaryOutcome"].get("delta"), (int, float))
        and not isinstance(item["primaryOutcome"].get("delta"), bool)
    ]
    completeness = (
        sum(float(item["primaryOutcome"].get("completeness", 0.0)) for item in valid) / len(valid)
        if valid
        else 0.0
    )
    isolation_ratio = (
        sum(item.get("isolationStatus") == "complete" for item in valid) / len(valid)
        if valid
        else 0.0
    )
    confounders = {
        str(confounder)
        for item in valid
        for confounder in item.get("confounders", [])
        if confounder not in {"", "none"}
    }
    critical_regression = any(item.get("correctnessGate", {}).get("criticalRegression") for item in valid)
    isolation_failed = any(item.get("isolationStatus") == "failed" for item in valid)
    effect_threshold_met = any(
        abs(float(item["primaryOutcome"]["delta"])) >= float(item["primaryOutcome"]["minimumEffect"])
        for item in valid
        if isinstance(item["primaryOutcome"].get("delta"), (int, float))
    )
    strength = _support_strength(
        pair_count=len(valid),
        same_direction_ratio=ratio,
        completeness=completeness,
        isolation_ratio=isolation_ratio,
        critical_regression=critical_regression,
        isolation_failed=isolation_failed,
        confounders=confounders,
        effect_threshold_met=effect_threshold_met,
    )
    if beneficial > harmful and not critical_regression:
        direction = "beneficial"
    elif harmful > beneficial or critical_regression:
        direction = "harmful"
    elif valid:
        direction = "mixed"
    else:
        direction = "unknown"

    if strength == "insufficient":
        proposal_type = "experiment-suggestion" if valid else "no-change"
        status = "observed"
    elif direction == "harmful":
        proposal_type = "negative-signal"
        status = "observed"
    elif direction == "beneficial":
        proposal_type = "configuration-proposal"
        status = "proposed"
    else:
        proposal_type = "experiment-suggestion"
        status = "observed"

    evidence_classes = {item["evidenceClass"] for item in valid}
    evidence_class = (
        "controlled-live-comparison"
        if evidence_classes == {"controlled-live-comparison"}
        else "paired-replay"
        if evidence_classes
        else "observational"
    )
    record = {
        "schemaVersion": types.PROPOSAL_SCHEMA_VERSION,
        "proposalId": proposal_id,
        "repositoryId": repository_id,
        "proposalType": proposal_type,
        "condition": {
            "taskCategory": task_category,
            "complexityLevel": complexity_level,
            "impactLevel": impact_level,
        },
        "candidate": {
            "executionClass": "delegated" if direction == "beneficial" else "unknown",
            "addIndependentReview": bool(direction == "beneficial"),
        },
        "evidence": {
            "evidenceClass": evidence_class,
            "comparisonRefs": [item["comparisonId"] for item in valid],
            "pairCount": len(valid),
            "wins": beneficial,
            "losses": harmful,
            "ties": ties,
            "medianPairedDelta": statistics.median(deltas) if deltas else None,
            "direction": direction,
            "supportStrength": strength,
            "primaryOutcomeCompleteness": completeness,
            "isolationCompleteRatio": isolation_ratio,
            "criticalRegressionCount": sum(
                bool(item.get("correctnessGate", {}).get("criticalRegression")) for item in valid
            ),
            "confounders": sorted(confounders),
            "thresholds": {
                "minimumPairs": 3,
                "weakDirectionRatio": 0.67,
                "moderateDirectionRatio": 0.70,
                "strongDirectionRatio": 0.80,
            },
        },
        "language": {
            "causalClaimAllowed": False,
            "requiredSummaryCode": "association-observed-causality-unconfirmed",
        },
        "status": status,
        "autoApplicable": False,
        "createdAt": created_at,
        "integrity": {"recordSha256": None},
    }
    sealed = types.seal_record(record)
    types.validate_proposal_record(sealed)
    return sealed
