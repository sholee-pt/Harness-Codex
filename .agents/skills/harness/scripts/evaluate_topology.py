#!/usr/bin/env python3
"""Evaluate a Harness for Codex v6.3 topology against golden expectations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import harness_topology


class EvaluationError(ValueError):
    pass


def load_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvaluationError(f"{label} must be an object")
    return value


def evaluate(plan: dict, golden: dict) -> dict:
    if plan.get("schemaVersion") != 3:
        raise EvaluationError("plan schemaVersion must be 3")
    topology = plan.get("topology")
    try:
        contract_warnings = harness_topology.validate_contract(
            topology, plan.get("capabilityPolicies")
        )
    except harness_topology.TopologyError as exc:
        return {
            "valid": False,
            "validationScope": "topology-contract",
            "evidenceValidated": False,
            "classificationMatch": False,
            "coverage": 0.0,
            "errors": [str(exc)],
            "warnings": [],
        }

    classification = topology["classification"]
    boundaries = topology["boundaries"]
    agents = topology["agents"]
    errors: list[str] = []
    warnings = list(contract_warnings)

    expected_class = golden.get("expectedClass")
    if expected_class not in harness_topology.TOPOLOGY_CLASSES:
        raise EvaluationError("golden.expectedClass is unsupported")
    classification_match = classification["class"] == expected_class
    if not classification_match:
        errors.append(
            f"expected topology class {expected_class}, got {classification['class']}"
        )

    count = len(boundaries)
    minimum = golden.get("minimumMaterialBoundaries", 0)
    maximum = golden.get("maximumMaterialBoundaries")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
        raise EvaluationError("golden.minimumMaterialBoundaries must be a non-negative integer")
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < minimum
    ):
        raise EvaluationError("golden.maximumMaterialBoundaries is invalid")
    if count < minimum:
        errors.append(f"expected at least {minimum} material boundaries, got {count}")
    if maximum is not None and count > maximum:
        errors.append(f"expected at most {maximum} material boundaries, got {count}")

    maximum_agents = golden.get("maximumAgents")
    if maximum_agents is not None:
        if not isinstance(maximum_agents, int) or isinstance(maximum_agents, bool) or maximum_agents < 0:
            raise EvaluationError("golden.maximumAgents must be a non-negative integer")
        if len(agents) > maximum_agents:
            errors.append(f"expected at most {maximum_agents} agents, got {len(agents)}")

    required_areas = golden.get("requiredDecisionAreaIds", [])
    if not isinstance(required_areas, list) or not all(
        isinstance(item, str) and harness_topology.ID_RE.fullmatch(item)
        for item in required_areas
    ):
        raise EvaluationError("golden.requiredDecisionAreaIds must contain kebab-case ids")
    if len(required_areas) != len(set(required_areas)):
        raise EvaluationError("golden.requiredDecisionAreaIds must not contain duplicates")
    covered_areas = {
        area
        for boundary in boundaries
        for area in boundary.get("decisionAreaIds", [])
        if isinstance(area, str)
    }
    matched = sorted(set(required_areas) & covered_areas)
    missing = sorted(set(required_areas) - covered_areas)
    coverage = 1.0 if not required_areas else len(matched) / len(set(required_areas))
    if missing:
        errors.append("missing required decision areas: " + ", ".join(missing))

    forbidden_agents = golden.get("forbiddenAgents", [])
    if not isinstance(forbidden_agents, list) or not all(
        isinstance(item, str) for item in forbidden_agents
    ):
        raise EvaluationError("golden.forbiddenAgents must be an array of strings")
    present_agents = {item.get("name") for item in agents if isinstance(item, dict)}
    forbidden_present = sorted(set(forbidden_agents) & present_agents)
    if forbidden_present:
        errors.append("forbidden agents are present: " + ", ".join(forbidden_present))

    acceptable_patterns = golden.get("acceptableCollaborationPatterns")
    if acceptable_patterns is not None:
        if not isinstance(acceptable_patterns, list) or not all(
            isinstance(item, str) and item in harness_topology.COLLABORATION_PATTERNS
            for item in acceptable_patterns
        ):
            raise EvaluationError("golden.acceptableCollaborationPatterns is invalid")
        unexpected = sorted(
            set(topology.get("collaborationPatterns", [])) - set(acceptable_patterns)
        )
        if unexpected:
            errors.append("unexpected collaboration patterns: " + ", ".join(unexpected))

    return {
        "valid": not errors,
        "validationScope": "topology-contract",
        "evidenceValidated": False,
        "classificationMatch": classification_match,
        "coverage": round(coverage, 6),
        "matchedDecisionAreaIds": matched,
        "missingDecisionAreaIds": missing,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--golden", required=True)
    args = parser.parse_args()
    try:
        report = evaluate(
            load_object(Path(args.plan), "plan"),
            load_object(Path(args.golden), "golden expectation"),
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["valid"] else 1
    except EvaluationError as exc:
        print(
            json.dumps(
                {
                    "valid": False,
                    "validationScope": "topology-contract",
                    "evidenceValidated": False,
                    "error": str(exc),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
