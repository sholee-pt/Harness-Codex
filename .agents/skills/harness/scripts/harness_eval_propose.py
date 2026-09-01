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


def _proposal_from_comparisons_v1(
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

    if direction == "harmful":
        proposal_type = "negative-signal"
        status = "observed"
    elif valid:
        proposal_type = "experiment-suggestion"
        status = "proposed" if direction == "beneficial" else "observed"
    else:
        proposal_type = "no-change"
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
        "schemaVersion": 1,
        "proposalId": proposal_id,
        "repositoryId": repository_id,
        "proposalType": proposal_type,
        "condition": {
            "taskCategory": task_category,
            "complexityLevel": complexity_level,
            "impactLevel": impact_level,
        },
        "candidate": {
            "executionClass": "unknown",
            "addIndependentReview": False,
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


def _task_stratum_key(value: dict[str, Any]) -> str:
    return types.canonical_text(value)


def _proposal_from_comparisons_v2(
    *,
    repository_id: str,
    proposal_id: str,
    created_at: str,
    comparisons: list[dict[str, Any]],
    task_category: str = "unknown",
    complexity_level: str = "unknown",
    impact_level: str = "unknown",
    ineligible_comparison_ids: set[str] | None = None,
) -> dict[str, Any]:
    relevant: list[dict[str, Any]] = []
    for comparison in comparisons:
        types.validate_comparison_record(comparison)
        if comparison.get("schemaVersion") != 2 or comparison.get("repositoryId") != repository_id:
            continue
        if comparison.get("primaryOutcome", {}).get("direction") == "unknown":
            continue
        stratum = comparison["taskStratum"]
        if task_category != "unknown" and stratum["category"] != task_category:
            continue
        if complexity_level != "unknown" and stratum["complexityLevel"] != complexity_level:
            continue
        if impact_level != "unknown" and stratum["impactLevel"] != impact_level:
            continue
        relevant.append(comparison)
    eligible = [
        item for item in relevant
        if item["comparisonId"] not in (ineligible_comparison_ids or set())
        and item["configurationDelta"]["state"] == "measured"
        and item["configurationDelta"]["protocolMatch"]
        and item["configurationDelta"]["changedFactorCount"] > 0
        and item["resultFingerprintComplete"]
        and item["isolationStatus"] != "failed"
        and not item["protocolDeviations"]
    ]
    strata = {_task_stratum_key(item["taskStratum"]) for item in eligible}
    evaluation_strata = {item["evaluationStratumFingerprint"] for item in eligible}
    delta_fingerprints = {
        item["configurationDelta"]["deltaFingerprint"] for item in eligible
    }
    metrics = {item["primaryOutcome"]["metric"] for item in eligible}
    if (
        len(strata) > 1
        or len(evaluation_strata) > 1
        or len(delta_fingerprints) > 1
        or len(metrics) > 1
    ):
        raise ProposalError(
            "Schema 2 proposal evidence must share task, runtime, outcome, and configuration-delta strata"
        )
    basis = eligible
    directions = [item["primaryOutcome"]["direction"] for item in basis]
    beneficial = directions.count("beneficial")
    harmful = directions.count("harmful")
    ties = directions.count("tie")
    non_ties = beneficial + harmful
    dominant_ratio = max(beneficial, harmful) / non_ties if non_ties else 0.0
    completeness = (
        sum(float(item["primaryOutcome"]["completeness"]) for item in basis) / len(basis)
        if basis else 0.0
    )
    isolation_ratio = (
        sum(item["isolationStatus"] == "complete" for item in basis) / len(basis)
        if basis else 0.0
    )
    confounders = {
        value for item in basis for value in item.get("confounders", []) if value in types.CONFOUNDERS
    }
    critical_regression = any(item["correctnessGate"]["criticalRegression"] for item in basis)
    isolation_failed = any(item["isolationStatus"] == "failed" for item in basis)
    effect_threshold_met = any(
        isinstance(item["primaryOutcome"]["delta"], (int, float))
        and abs(float(item["primaryOutcome"]["delta"])) >= float(item["primaryOutcome"]["minimumEffect"])
        for item in basis
    )
    strength = _support_strength(
        pair_count=len(eligible),
        same_direction_ratio=dominant_ratio,
        completeness=completeness,
        isolation_ratio=isolation_ratio,
        critical_regression=critical_regression,
        isolation_failed=isolation_failed,
        confounders=confounders,
        effect_threshold_met=effect_threshold_met,
    )
    direction = (
        "beneficial" if beneficial > harmful and not critical_regression
        else "harmful" if harmful > beneficial or critical_regression
        else "mixed" if basis
        else "unknown"
    )
    delta = eligible[0]["configurationDelta"] if eligible else None
    scope = delta["attributionScope"] if delta is not None else "none"
    if delta is not None and scope == "single-factor":
        factor = delta["changedFactors"][0]
        candidate = {
            "attributionScope": "single-factor",
            "factor": factor["factor"],
            "from": factor["baseline"],
            "to": factor["treatment"],
            "bundleFingerprint": None,
            "factors": [factor["factor"]],
        }
    elif delta is not None and scope == "bundle":
        candidate = {
            "attributionScope": "bundle",
            "factor": None,
            "from": None,
            "to": None,
            "bundleFingerprint": delta["deltaFingerprint"],
            "factors": [item["factor"] for item in delta["changedFactors"]],
        }
    else:
        candidate = {
            "attributionScope": "none",
            "factor": None,
            "from": None,
            "to": None,
            "bundleFingerprint": None,
            "factors": [],
        }
    if direction == "harmful" and basis:
        proposal_type = "negative-signal"
        status = "observed"
    elif direction == "beneficial" and delta is not None and strength != "insufficient":
        proposal_type = "configuration-proposal" if scope == "single-factor" else "bundle-proposal"
        status = "proposed"
    elif basis or relevant:
        proposal_type = "experiment-suggestion"
        status = "observed"
    else:
        proposal_type = "no-change"
        status = "observed"
    if proposal_type in {"experiment-suggestion", "no-change"}:
        candidate = {
            "attributionScope": "none",
            "factor": None,
            "from": None,
            "to": None,
            "bundleFingerprint": None,
            "factors": [],
        }
        scope = "none"
    evidence_classes = {item["evidenceClass"] for item in basis}
    evidence_class = (
        "controlled-live-comparison" if evidence_classes == {"controlled-live-comparison"}
        else "paired-replay" if evidence_classes else "observational"
    )
    default_stratum = {
        "category": task_category,
        "complexityLevel": complexity_level,
        "impactLevel": impact_level,
        "uncertaintyLevel": "unknown",
        "scopeClass": "unknown",
    }
    paired_deltas = [
        float(item["primaryOutcome"]["delta"]) for item in basis
        if isinstance(item["primaryOutcome"]["delta"], (int, float))
        and not isinstance(item["primaryOutcome"]["delta"], bool)
    ]
    record = {
        "schemaVersion": 2,
        "proposalId": proposal_id,
        "repositoryId": repository_id,
        "proposalType": proposal_type,
        "taskStratum": basis[0]["taskStratum"] if basis else default_stratum,
        "candidateDelta": candidate,
        "evidence": {
            "evidenceClass": evidence_class,
            "comparisonRefs": [item["comparisonId"] for item in basis],
            "pairCount": len(basis),
            "wins": beneficial,
            "losses": harmful,
            "ties": ties,
            "medianPairedDelta": statistics.median(paired_deltas) if paired_deltas else None,
            "direction": direction,
            "supportStrength": strength,
            "attributionScope": scope,
            "protocolMatchRatio": sum(item["configurationDelta"]["protocolMatch"] for item in basis) / len(basis) if basis else 0.0,
            "isolationCompleteRatio": isolation_ratio,
            "primaryOutcomeCompleteness": completeness,
            "criticalRegressionCount": sum(item["correctnessGate"]["criticalRegression"] for item in basis),
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


def proposal_from_comparisons(**kwargs: Any) -> dict[str, Any]:
    comparisons = kwargs.get("comparisons", [])
    if comparisons and all(item.get("schemaVersion") == 1 for item in comparisons):
        # Legacy evidence remains readable, but v6 never emits a new legacy-attribution proposal.
        return _proposal_from_comparisons_v2(**kwargs)
    return _proposal_from_comparisons_v2(**kwargs)
