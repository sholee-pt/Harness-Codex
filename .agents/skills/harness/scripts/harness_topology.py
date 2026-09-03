#!/usr/bin/env python3
"""Validate the machine-readable Harness for Codex v6.10 topology contract."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Iterable, Iterator

import harness_teamplay


ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")

TOPOLOGY_CLASSES = {"minimal", "modular", "coordinated"}
DEPENDENCY_SHAPES = {"independent", "static-dag", "cyclic-contract", "dynamic"}
BOUNDARY_TYPES = {
    "responsibility",
    "execution-environment",
    "contract",
    "data-flow",
    "quality-risk",
    "recurring-workflow",
}
PERSISTENCE_KINDS = {
    "stable-structure",
    "documented-recurring-workflow",
    "historically-observed",
}
SEPARATION_BENEFITS = {
    "specializedJudgment",
    "parallelizable",
    "contextIsolation",
    "reusable",
    "independentReview",
}
COLLABORATION_PATTERNS = {
    "pipeline",
    "fan-out/fan-in",
    "expert-pool",
    "producer-reviewer",
    "supervisor",
    "hierarchical-delegation",
}
QUALITY_PATTERNS = {
    "adversarial-verification",
    "judge-panel",
    "loop-until-dry",
    "multi-angle-sweep",
    "completeness-critic",
    "independent-safety-review",
}
SEMANTIC_MODES = {
    "direct-execution",
    "deterministic-orchestration",
    "persistent-collaboration",
    "one-shot-delegation",
    "hybrid",
}
EXECUTION_CLASSES = {"direct", "delegated", "coordinated"}
COORDINATION_REASONS = {
    "dynamic-allocation",
    "fan-out-fan-in",
    "cross-contract-verification",
    "reviewer-chain",
    "phase-freeze",
}
ACCESS_MODES = {"read", "write"}
RUNTIME_MAPPINGS = {"instruction-driven", "runtime-native"}
PRESERVED_CONTRACTS = {"input", "output", "verification"}
QUALITY_BUDGET_KEYS = {
    "adversarial-verification": {"maxAgents", "maxRounds"},
    "judge-panel": {"maxCandidates", "maxJudges"},
    "loop-until-dry": {"maxRounds", "zeroFindingRounds"},
    "multi-angle-sweep": {"maxAngles"},
    "completeness-critic": {"maxRounds"},
    "independent-safety-review": {"maxReviewers"},
}


class TopologyError(ValueError):
    pass


def require_object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise TopologyError(f"{label} must be an object")
    return value


def require_list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise TopologyError(f"{label} must be an array")
    return value


def require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TopologyError(f"{label} must be non-empty text")
    return value


def require_id(value: object, label: str) -> str:
    text = require_text(value, label)
    if not ID_RE.fullmatch(text):
        raise TopologyError(f"{label} must be a kebab-case identifier")
    return text


def require_string_list(value: object, label: str, *, nonempty: bool = False) -> list[str]:
    items = require_list(value, label)
    if nonempty and not items:
        raise TopologyError(f"{label} must not be empty")
    if not all(isinstance(item, str) and item.strip() for item in items):
        raise TopologyError(f"{label} entries must be non-empty strings")
    return items


def require_evidence_shape(value: object, label: str) -> list[dict]:
    items = require_list(value, label)
    if not items or not all(isinstance(item, dict) for item in items):
        raise TopologyError(f"{label} must contain at least one evidence object")
    return items


def normalize_scope(value: object, label: str) -> tuple[str, bool]:
    scope = require_text(value, label)
    is_prefix = scope.endswith("/**")
    base = scope[:-3] if is_prefix else scope
    if not base or "\\" in base or "*" in base or "?" in base:
        raise TopologyError(
            f"{label} must be a literal POSIX-relative path or a directory prefix ending in /**"
        )
    path = PurePosixPath(base)
    if (
        path.is_absolute()
        or path.as_posix() != base
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise TopologyError(f"{label} must be a normalized POSIX-relative path")
    return base, is_prefix


def scopes_overlap(first: str, second: str) -> bool:
    first_base, first_prefix = normalize_scope(first, "first scope")
    second_base, second_prefix = normalize_scope(second, "second scope")
    first_key = first_base.casefold()
    second_key = second_base.casefold()
    if first_key == second_key:
        return True
    if first_prefix and second_key.startswith(first_key + "/"):
        return True
    if second_prefix and first_key.startswith(second_key + "/"):
        return True
    return False


def scope_contains(container: str, candidate: str) -> bool:
    container_base, container_prefix = normalize_scope(container, "container scope")
    candidate_base, candidate_prefix = normalize_scope(candidate, "candidate scope")
    if container_prefix:
        return candidate_base == container_base or candidate_base.startswith(
            container_base + "/"
        )
    return not candidate_prefix and candidate_base == container_base


def scope_intersection(first: str, second: str) -> str | None:
    first_base, first_prefix = normalize_scope(first, "first scope")
    second_base, second_prefix = normalize_scope(second, "second scope")
    first_key = first_base.casefold()
    second_key = second_base.casefold()
    if first_key == second_key:
        if first_prefix and not second_prefix:
            return second
        if second_prefix and not first_prefix:
            return first
        return first
    if first_prefix and second_key.startswith(first_key + "/"):
        return second
    if second_prefix and first_key.startswith(second_key + "/"):
        return first
    return None


def scopes_equivalent(first: str, second: str) -> bool:
    first_base, first_prefix = normalize_scope(first, "first scope")
    second_base, second_prefix = normalize_scope(second, "second scope")
    return first_prefix == second_prefix and first_base.casefold() == second_base.casefold()


def _has_interaction_cycle(boundaries: list[dict]) -> bool:
    graph = {item["id"]: item.get("interactsWith", []) for item in boundaries}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> bool:
        if identifier in visiting:
            return True
        if identifier in visited:
            return False
        visiting.add(identifier)
        for related in graph[identifier]:
            if visit(related):
                return True
        visiting.remove(identifier)
        visited.add(identifier)
        return False

    return any(visit(identifier) for identifier in graph)


def _validate_string_ids(values: object, label: str, *, nonempty: bool = False) -> list[str]:
    items = require_string_list(values, label, nonempty=nonempty)
    for index, item in enumerate(items):
        if not ID_RE.fullmatch(item):
            raise TopologyError(f"{label}[{index}] must be a kebab-case identifier")
    if len(items) != len(set(items)):
        raise TopologyError(f"{label} contains duplicates")
    return items


def _validate_boundary(item: object, index: int) -> dict:
    label = f"topology.boundaries[{index}]"
    boundary = require_object(item, label)
    require_id(boundary.get("id"), f"{label}.id")
    require_text(boundary.get("name"), f"{label}.name")
    types = require_string_list(boundary.get("types"), f"{label}.types", nonempty=True)
    if any(value not in BOUNDARY_TYPES for value in types):
        raise TopologyError(f"{label}.types contains an unsupported boundary type")
    if len(types) != len(set(types)):
        raise TopologyError(f"{label}.types contains duplicates")
    require_text(boundary.get("summary"), f"{label}.summary")
    require_evidence_shape(boundary.get("evidence"), f"{label}.evidence")
    decision_ids = _validate_string_ids(
        boundary.get("decisionAreaIds"), f"{label}.decisionAreaIds", nonempty=True
    )
    if not decision_ids:
        raise TopologyError(f"{label}.decisionAreaIds must not be empty")

    inputs = require_string_list(boundary.get("inputs", []), f"{label}.inputs")
    outputs = require_string_list(boundary.get("outputs", []), f"{label}.outputs")
    contracts = require_string_list(boundary.get("contracts", []), f"{label}.contracts")
    read_scopes = require_string_list(boundary.get("readScopes", []), f"{label}.readScopes")
    write_scopes = require_string_list(boundary.get("writeScopes", []), f"{label}.writeScopes")
    if not (inputs or outputs or contracts or read_scopes or write_scopes):
        raise TopologyError(
            f"{label} must define inputs/outputs, a contract, or a read/write scope"
        )
    for kind, scopes in (("readScopes", read_scopes), ("writeScopes", write_scopes)):
        for scope_index, scope in enumerate(scopes):
            normalize_scope(scope, f"{label}.{kind}[{scope_index}]")

    require_string_list(boundary.get("verification"), f"{label}.verification", nonempty=True)
    require_text(boundary.get("failureImpact"), f"{label}.failureImpact")
    persistence = require_object(boundary.get("persistence"), f"{label}.persistence")
    if persistence.get("kind") not in PERSISTENCE_KINDS:
        raise TopologyError(f"{label}.persistence.kind is unsupported")
    require_evidence_shape(persistence.get("evidence"), f"{label}.persistence.evidence")

    benefits = require_object(boundary.get("separationBenefits"), f"{label}.separationBenefits")
    unknown_benefits = set(benefits) - SEPARATION_BENEFITS
    if unknown_benefits:
        raise TopologyError(f"{label}.separationBenefits contains unknown keys")
    if not all(isinstance(value, bool) for value in benefits.values()):
        raise TopologyError(f"{label}.separationBenefits values must be booleans")
    if not any(benefits.get(key) is True for key in SEPARATION_BENEFITS):
        raise TopologyError(f"{label} must declare at least one material separation benefit")

    for field in ("dependsOn", "interactsWith", "overlapWith"):
        _validate_string_ids(boundary.get(field, []), f"{label}.{field}")
    if boundary.get("overlapWith"):
        rationale = require_object(
            boundary.get("separationRationale"), f"{label}.separationRationale"
        )
        require_text(rationale.get("summary"), f"{label}.separationRationale.summary")
        require_string_list(
            rationale.get("distinctDecisions"),
            f"{label}.separationRationale.distinctDecisions",
            nonempty=True,
        )
        require_string_list(
            rationale.get("distinctFailureModes"),
            f"{label}.separationRationale.distinctFailureModes",
            nonempty=True,
        )
    return boundary


def _validate_dependency_graph(boundaries: list[dict]) -> None:
    known = {item["id"] for item in boundaries}
    graph: dict[str, list[str]] = {}
    for boundary in boundaries:
        identifier = boundary["id"]
        graph[identifier] = boundary.get("dependsOn", [])
        for field in ("dependsOn", "interactsWith", "overlapWith"):
            for reference in boundary.get(field, []):
                if reference not in known:
                    raise TopologyError(
                        f"boundary {identifier} references unknown {field} boundary {reference!r}"
                    )
                if reference == identifier:
                    raise TopologyError(f"boundary {identifier} cannot reference itself in {field}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in visiting:
            raise TopologyError("boundary dependsOn graph must be acyclic")
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in graph[identifier]:
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in graph:
        visit(identifier)


def _validate_classification(classification: object, boundaries: list[dict]) -> list[str]:
    value = require_object(classification, "topology.classification")
    topology_class = value.get("class")
    if topology_class not in TOPOLOGY_CLASSES:
        raise TopologyError("topology.classification.class is unsupported")
    count = value.get("materialBoundaryCount")
    if not isinstance(count, int) or isinstance(count, bool) or count != len(boundaries):
        raise TopologyError(
            "topology.classification.materialBoundaryCount must equal the post-merge boundary count"
        )
    dependency_shape = value.get("dependencyShape")
    if dependency_shape not in DEPENDENCY_SHAPES:
        raise TopologyError("topology.classification.dependencyShape is unsupported")
    recurring = value.get("recurringCoordination")
    if not isinstance(recurring, bool):
        raise TopologyError("topology.classification.recurringCoordination must be boolean")
    reasons = require_string_list(
        value.get("coordinationReasons"), "topology.classification.coordinationReasons"
    )
    if any(reason not in COORDINATION_REASONS for reason in reasons):
        raise TopologyError("topology.classification.coordinationReasons contains an unknown value")
    if len(reasons) != len(set(reasons)):
        raise TopologyError("topology.classification.coordinationReasons contains duplicates")
    require_text(value.get("rationale"), "topology.classification.rationale")
    require_string_list(value.get("uncertainties"), "topology.classification.uncertainties")

    if topology_class == "minimal" and (count > 1 or recurring):
        raise TopologyError("minimal topology requires at most one boundary and no recurring coordination")
    if topology_class == "modular" and (count < 2 or recurring or dependency_shape == "dynamic"):
        raise TopologyError(
            "modular topology requires at least two boundaries and static, non-recurring coordination"
        )
    if topology_class == "coordinated" and (count == 0 or not recurring or not reasons):
        raise TopologyError(
            "coordinated topology requires a material boundary and repository-level recurring coordination reasons"
        )
    if recurring != bool(reasons):
        raise TopologyError(
            "recurringCoordination and coordinationReasons must either both be present or both be absent"
        )
    if dependency_shape == "dynamic" and topology_class != "coordinated":
        raise TopologyError("dynamic dependency shape requires coordinated topology")
    if dependency_shape == "independent" and any(
        boundary.get("dependsOn") for boundary in boundaries
    ):
        raise TopologyError("independent dependency shape requires empty dependsOn relationships")
    if dependency_shape == "cyclic-contract" and not _has_interaction_cycle(boundaries):
        raise TopologyError(
            "cyclic-contract dependency shape requires a cycle in interactsWith relationships"
        )
    if dependency_shape == "dynamic" and "dynamic-allocation" not in reasons:
        raise TopologyError(
            "dynamic dependency shape requires the dynamic-allocation coordination reason"
        )
    if "dynamic-allocation" in reasons and dependency_shape != "dynamic":
        raise TopologyError(
            "dynamic-allocation coordination reason requires dynamic dependency shape"
        )

    known = {item["id"] for item in boundaries}
    merged = require_list(value.get("mergedCandidates"), "topology.classification.mergedCandidates")
    seen_candidates: set[str] = set()
    for index, item in enumerate(merged):
        label = f"topology.classification.mergedCandidates[{index}]"
        entry = require_object(item, label)
        sources = _validate_string_ids(entry.get("from"), f"{label}.from", nonempty=True)
        if any(source in known for source in sources):
            raise TopologyError(f"{label}.from must name removed candidates, not retained boundaries")
        if seen_candidates.intersection(sources):
            raise TopologyError(f"{label}.from repeats an already merged candidate")
        seen_candidates.update(sources)
        target = require_id(entry.get("into"), f"{label}.into")
        if target not in known:
            raise TopologyError(f"{label}.into references an unknown retained boundary")
        require_text(entry.get("reason"), f"{label}.reason")

    warnings: list[str] = []
    if topology_class == "modular" and count >= 4:
        warnings.append(
            "modular topology has four or more material boundaries; confirm that coordination remains static"
        )
    return warnings


def _validate_scope_refs(
    component: dict,
    label: str,
    known_boundaries: set[str],
    *,
    allow_project: bool,
) -> None:
    scope = component.get("scope")
    allowed = {"boundary", "cross-boundary"} | ({"project"} if allow_project else set())
    if scope not in allowed:
        raise TopologyError(f"{label}.scope is unsupported")
    refs = _validate_string_ids(component.get("boundaryRefs", []), f"{label}.boundaryRefs")
    unknown = set(refs) - known_boundaries
    if unknown:
        raise TopologyError(f"{label}.boundaryRefs references unknown boundaries")
    if scope == "boundary" and len(refs) != 1:
        raise TopologyError(f"{label} with boundary scope must reference exactly one boundary")
    if scope == "cross-boundary" and len(refs) < 2:
        raise TopologyError(f"{label} with cross-boundary scope must reference at least two boundaries")
    if scope == "project" and refs:
        raise TopologyError(f"{label} with project scope must omit boundaryRefs")


def _validate_phases(value: object) -> tuple[dict[str, int], dict[str, tuple[int, int]]]:
    phases = require_list(value, "topology.executionPhases")
    order_by_id: dict[str, int] = {}
    lane_orders: dict[str, tuple[int, int]] = {}
    for index, item in enumerate(phases):
        label = f"topology.executionPhases[{index}]"
        phase = require_object(item, label)
        identifier = require_id(phase.get("id"), f"{label}.id")
        order = phase.get("order")
        if identifier in order_by_id:
            raise TopologyError(f"duplicate execution phase id: {identifier}")
        if not isinstance(order, int) or isinstance(order, bool) or order < 0:
            raise TopologyError(f"{label}.order must be a non-negative integer")
        if order in order_by_id.values():
            raise TopologyError(f"duplicate execution phase order: {order}")
        order_by_id[identifier] = order
        phase_groups = require_list(phase.get("concurrencyGroups"), f"{label}.concurrencyGroups")
        if not phase_groups:
            raise TopologyError(f"{label}.concurrencyGroups must not be empty")
        group_orders: set[int] = set()
        for group_index, group_item in enumerate(phase_groups):
            group_label = f"{label}.concurrencyGroups[{group_index}]"
            group = require_object(group_item, group_label)
            group_id = require_id(group.get("id"), f"{group_label}.id")
            group_order = group.get("order")
            if not isinstance(group_order, int) or isinstance(group_order, bool) or group_order < 0:
                raise TopologyError(f"{group_label}.order must be a non-negative integer")
            lane_id = f"{identifier}:{group_id}"
            if lane_id in lane_orders or group_order in group_orders:
                raise TopologyError(f"{label}.concurrencyGroups contains duplicate id or order")
            group_orders.add(group_order)
            lane_orders[lane_id] = (order, group_order)
    return order_by_id, lane_orders


def _validate_components(
    topology: dict,
    boundaries_by_id: dict[str, dict],
    phase_orders: dict[str, int],
    lane_orders: dict[str, tuple[int, int]],
) -> None:
    known_boundaries = set(boundaries_by_id)
    skills = require_list(topology.get("skills"), "topology.skills")
    for index, item in enumerate(skills):
        label = f"topology.skills[{index}]"
        skill = require_object(item, label)
        name = skill.get("name")
        if name == "project-harness":
            if skill.get("scope") != "project":
                raise TopologyError("project-harness must use project scope")
            _validate_scope_refs(skill, label, known_boundaries, allow_project=True)
        else:
            _validate_scope_refs(skill, label, known_boundaries, allow_project=False)

    agents = require_list(topology.get("agents"), "topology.agents")
    agent_names: set[str] = set()
    accesses: list[tuple[str, dict]] = []
    for index, item in enumerate(agents):
        label = f"topology.agents[{index}]"
        agent = require_object(item, label)
        name = require_text(agent.get("name"), f"{label}.name")
        if name in agent_names:
            raise TopologyError(f"duplicate agent name: {name}")
        agent_names.add(name)
        _validate_scope_refs(agent, label, known_boundaries, allow_project=False)
        file_access = require_list(agent.get("fileAccess"), f"{label}.fileAccess")
        if not file_access:
            raise TopologyError(f"{label}.fileAccess must not be empty")
        for access_index, access_item in enumerate(file_access):
            access_label = f"{label}.fileAccess[{access_index}]"
            access = require_object(access_item, access_label)
            normalize_scope(access.get("scope"), f"{access_label}.scope")
            if access.get("mode") not in ACCESS_MODES:
                raise TopologyError(f"{access_label}.mode is unsupported")
            phase = require_id(access.get("phase"), f"{access_label}.phase")
            group = require_id(access.get("concurrencyGroup"), f"{access_label}.concurrencyGroup")
            if phase not in phase_orders:
                raise TopologyError(f"{access_label}.phase references an unknown phase")
            if f"{phase}:{group}" not in lane_orders:
                raise TopologyError(f"{access_label}.concurrencyGroup is not declared for its phase")
            permitted: list[str] = []
            for boundary_ref in agent.get("boundaryRefs", []):
                boundary = boundaries_by_id[boundary_ref]
                permitted.extend(boundary.get("writeScopes", []))
                if access.get("mode") == "read":
                    permitted.extend(boundary.get("readScopes", []))
            if not any(scope_contains(scope, access["scope"]) for scope in permitted):
                raise TopologyError(
                    f"{access_label}.scope is outside the referenced material-boundary scopes"
                )
            accesses.append((name, access))

    handoffs = require_list(topology.get("handoffs"), "topology.handoffs")
    handoff_pairs: list[tuple[str, str, str, str, str]] = []
    for index, item in enumerate(handoffs):
        label = f"topology.handoffs[{index}]"
        handoff = require_object(item, label)
        source = require_text(handoff.get("fromAgent"), f"{label}.fromAgent")
        target = require_text(handoff.get("toAgent"), f"{label}.toAgent")
        if source not in agent_names or target not in agent_names or source == target:
            raise TopologyError(f"{label} must reference two distinct known agents")
        scope = require_text(handoff.get("scope"), f"{label}.scope")
        normalize_scope(scope, f"{label}.scope")
        from_phase = require_id(handoff.get("fromPhase"), f"{label}.fromPhase")
        to_phase = require_id(handoff.get("toPhase"), f"{label}.toPhase")
        if from_phase not in phase_orders or to_phase not in phase_orders:
            raise TopologyError(f"{label} references an unknown phase")
        from_group = require_id(
            handoff.get("fromConcurrencyGroup"), f"{label}.fromConcurrencyGroup"
        )
        to_group = require_id(
            handoff.get("toConcurrencyGroup"), f"{label}.toConcurrencyGroup"
        )
        from_lane = f"{from_phase}:{from_group}"
        to_lane = f"{to_phase}:{to_group}"
        if from_lane not in lane_orders or to_lane not in lane_orders:
            raise TopologyError(f"{label} references an unknown concurrency lane")
        if lane_orders[from_lane] >= lane_orders[to_lane]:
            raise TopologyError(f"{label} must move from an earlier lane to a later lane")
        require_text(handoff.get("precondition"), f"{label}.precondition")
        require_text(handoff.get("verification"), f"{label}.verification")
        handoff_pairs.append((source, target, scope, from_lane, to_lane))

    for index, (first_agent, first) in enumerate(accesses):
        if first.get("mode") != "write":
            continue
        for second_agent, second in accesses[index + 1 :]:
            if second.get("mode") != "write" or first_agent == second_agent:
                continue
            if not scopes_overlap(first["scope"], second["scope"]):
                continue
            first_lane = f"{first['phase']}:{first['concurrencyGroup']}"
            second_lane = f"{second['phase']}:{second['concurrencyGroup']}"
            same_lane = first_lane == second_lane
            if same_lane:
                raise TopologyError(
                    f"concurrent writers {first_agent} and {second_agent} have overlapping scopes"
                )
            if lane_orders[first_lane] < lane_orders[second_lane]:
                source_agent, target_agent = first_agent, second_agent
                source_lane, target_lane = first_lane, second_lane
            else:
                source_agent, target_agent = second_agent, first_agent
                source_lane, target_lane = second_lane, first_lane
            shared_scope = scope_intersection(first["scope"], second["scope"])
            has_handoff = shared_scope is not None and any(
                scopes_equivalent(scope, shared_scope)
                and source == source_agent
                and target == target_agent
                and from_lane == source_lane
                and to_lane == target_lane
                for source, target, scope, from_lane, to_lane in handoff_pairs
            )
            if not has_handoff:
                raise TopologyError(
                    f"sequential writers {first_agent} and {second_agent} require a verified "
                    "handoff for their complete overlapping scope"
                )


def _validate_quality_policies(value: object, known_boundaries: set[str]) -> set[str]:
    policies = require_list(value, "topology.qualityPatternPolicies")
    known: set[str] = set()
    for index, item in enumerate(policies):
        label = f"topology.qualityPatternPolicies[{index}]"
        policy = require_object(item, label)
        identifier = require_id(policy.get("id"), f"{label}.id")
        if identifier in known:
            raise TopologyError(f"duplicate quality policy id: {identifier}")
        known.add(identifier)
        name = policy.get("name")
        if name not in QUALITY_PATTERNS:
            raise TopologyError(f"{label}.name is unsupported")
        if policy.get("justificationSource") != "repository-evidence":
            raise TopologyError(
                f"{label}.justificationSource must be repository-evidence in persistent topology"
            )
        require_evidence_shape(policy.get("evidence"), f"{label}.evidence")
        refs = _validate_string_ids(
            policy.get("boundaryRefs"), f"{label}.boundaryRefs", nonempty=True
        )
        if set(refs) - known_boundaries:
            raise TopologyError(f"{label}.boundaryRefs references unknown boundaries")
        budget = require_object(policy.get("budget"), f"{label}.budget")
        expected_budget_keys = QUALITY_BUDGET_KEYS[name]
        if set(budget) != expected_budget_keys:
            raise TopologyError(
                f"{label}.budget must contain exactly: "
                + ", ".join(sorted(expected_budget_keys))
            )
        if not all(
            isinstance(amount, int) and not isinstance(amount, bool) and amount > 0
            for amount in budget.values()
        ):
            raise TopologyError(f"{label}.budget values must be positive integers")
        if name == "loop-until-dry" and budget["zeroFindingRounds"] > budget["maxRounds"]:
            raise TopologyError(
                f"{label}.budget.zeroFindingRounds must not exceed maxRounds"
            )
        stopping = require_text(policy.get("stoppingCondition"), f"{label}.stoppingCondition")
        if stopping.strip().lower() in {"until satisfactory", "until complete", "as needed"}:
            raise TopologyError(f"{label}.stoppingCondition must be finite and testable")
        require_text(policy.get("failurePolicy"), f"{label}.failurePolicy")
    return known


def _validate_capability_policies(value: object) -> set[str]:
    policies = require_list(value, "capabilityPolicies")
    known: set[str] = set()
    for index, item in enumerate(policies):
        label = f"capabilityPolicies[{index}]"
        policy = require_object(item, label)
        identifier = require_id(policy.get("id"), f"{label}.id")
        if identifier in known:
            raise TopologyError(f"duplicate capability policy id: {identifier}")
        known.add(identifier)
        mode = policy.get("semanticMode")
        if mode not in SEMANTIC_MODES:
            raise TopologyError(f"{label}.semanticMode is unsupported")
        capabilities = require_string_list(
            policy.get("requiredCapabilities"), f"{label}.requiredCapabilities"
        )
        try:
            normalized_capabilities = [
                harness_teamplay.normalize_capability_id(capability, allow_alias=False)
                for capability in capabilities
            ]
        except harness_teamplay.TeamplayError as exc:
            raise TopologyError(f"{label}.requiredCapabilities: {exc}") from exc
        if len(normalized_capabilities) != len(set(normalized_capabilities)):
            raise TopologyError(f"{label}.requiredCapabilities contains duplicates")
        mapping = policy.get("preferredRuntimeMapping")
        if mapping not in RUNTIME_MAPPINGS:
            raise TopologyError(f"{label}.preferredRuntimeMapping is unsupported")
        require_text(policy.get("reason"), f"{label}.reason")
        probe = policy.get("probe")
        fallback = policy.get("fallback")
        if capabilities or mapping == "runtime-native":
            probe_value = require_object(probe, f"{label}.probe")
            if probe_value.get("mode") != "runtime-check":
                raise TopologyError(f"{label}.probe.mode must be runtime-check")
        elif probe is not None:
            require_object(probe, f"{label}.probe")
        if capabilities or mapping == "runtime-native":
            fallback_value = require_object(fallback, f"{label}.fallback")
            if fallback_value.get("semanticMode") not in SEMANTIC_MODES:
                raise TopologyError(f"{label}.fallback.semanticMode is unsupported")
            require_text(fallback_value.get("implementation"), f"{label}.fallback.implementation")
            preserved_items = require_string_list(
                fallback_value.get("preserves"), f"{label}.fallback.preserves", nonempty=True
            )
            preserved = set(preserved_items)
            if len(preserved_items) != len(preserved) or preserved != PRESERVED_CONTRACTS:
                raise TopologyError(
                    f"{label}.fallback.preserves must contain input, output, and verification"
                )
        elif fallback is not None:
            raise TopologyError(f"{label}.fallback is unnecessary without a runtime requirement")
    return known


def _validate_routing_policies(
    value: object,
    known_boundaries: set[str],
    collaboration_patterns: set[str],
    quality_policies: set[str],
    capability_policies: set[str],
) -> None:
    routes = require_list(value, "topology.routingPolicies")
    known: set[str] = set()
    known_categories: set[str] = set()
    for index, item in enumerate(routes):
        label = f"topology.routingPolicies[{index}]"
        route = require_object(item, label)
        identifier = require_id(route.get("id"), f"{label}.id")
        if identifier in known:
            raise TopologyError(f"duplicate routing policy id: {identifier}")
        known.add(identifier)
        require_evidence_shape(route.get("evidence"), f"{label}.evidence")
        categories = _validate_string_ids(
            route.get("taskCategories"), f"{label}.taskCategories", nonempty=True
        )
        duplicate_categories = known_categories.intersection(categories)
        if duplicate_categories:
            raise TopologyError(
                f"{label}.taskCategories repeats globally assigned categories: "
                + ", ".join(sorted(duplicate_categories))
            )
        known_categories.update(categories)
        refs = _validate_string_ids(route.get("activeBoundaryRefs"), f"{label}.activeBoundaryRefs")
        if set(refs) - known_boundaries:
            raise TopologyError(f"{label}.activeBoundaryRefs references unknown boundaries")
        execution_class = route.get("recommendedExecutionClass")
        if execution_class not in EXECUTION_CLASSES:
            raise TopologyError(f"{label}.recommendedExecutionClass is unsupported")
        patterns = set(
            require_string_list(route.get("collaborationPatterns"), f"{label}.collaborationPatterns")
        )
        if patterns - collaboration_patterns:
            raise TopologyError(f"{label}.collaborationPatterns references undeclared patterns")
        if execution_class == "direct" and patterns:
            raise TopologyError(
                f"{label} cannot recommend direct execution with collaboration patterns"
            )
        quality_refs = set(
            _validate_string_ids(route.get("qualityPolicyRefs"), f"{label}.qualityPolicyRefs")
        )
        if quality_refs - quality_policies:
            raise TopologyError(f"{label}.qualityPolicyRefs references unknown policies")
        capability_ref = require_id(route.get("capabilityPolicyRef"), f"{label}.capabilityPolicyRef")
        if capability_ref not in capability_policies:
            raise TopologyError(f"{label}.capabilityPolicyRef references an unknown policy")


def _validate_coordination_bindings(
    topology: dict,
    boundaries: list[dict],
    patterns: set[str],
    lane_orders: dict[str, tuple[int, int]],
) -> None:
    reasons = set(topology["classification"].get("coordinationReasons", []))
    if "dynamic-allocation" in reasons and not patterns.intersection(
        {"supervisor", "hierarchical-delegation"}
    ):
        raise TopologyError(
            "dynamic-allocation requires supervisor or hierarchical-delegation collaboration"
        )
    if "fan-out-fan-in" in reasons and "fan-out/fan-in" not in patterns:
        raise TopologyError(
            "fan-out-fan-in coordination reason requires the fan-out/fan-in pattern"
        )
    if "cross-contract-verification" in reasons:
        contract_boundary_ids = {
            boundary["id"]
            for boundary in boundaries
            if "contract" in boundary.get("types", [])
        }
        cross_boundary_component = any(
            isinstance(component, dict)
            and component.get("scope") == "cross-boundary"
            and len(contract_boundary_ids.intersection(component.get("boundaryRefs", []))) >= 2
            for collection in (topology.get("agents", []), topology.get("skills", []))
            for component in collection
        )
        policy_witness = any(
            isinstance(policy, dict)
            and len(
                contract_boundary_ids.intersection(
                    policy.get("activeBoundaryRefs", policy.get("boundaryRefs", []))
                )
            )
            >= 2
            for collection in (
                topology.get("routingPolicies", []),
                topology.get("qualityPatternPolicies", []),
            )
            for policy in collection
        )
        agent_contract_refs = {
            agent.get("name"): contract_boundary_ids.intersection(agent.get("boundaryRefs", []))
            for agent in topology.get("agents", [])
            if isinstance(agent, dict) and isinstance(agent.get("name"), str)
        }
        handoff_witness = any(
            isinstance(handoff, dict)
            and len(
                agent_contract_refs.get(handoff.get("fromAgent"), set())
                | agent_contract_refs.get(handoff.get("toAgent"), set())
            )
            >= 2
            for handoff in topology.get("handoffs", [])
        )
        if len(contract_boundary_ids) < 2 or not (
            cross_boundary_component or policy_witness or handoff_witness
        ):
            raise TopologyError(
                "cross-contract-verification requires a component, policy, or handoff that "
                "references at least two contract boundaries"
            )
    if "reviewer-chain" in reasons:
        phase_count = len({order[0] for order in lane_orders.values()})
        if "producer-reviewer" not in patterns or phase_count < 2:
            raise TopologyError(
                "reviewer-chain requires producer-reviewer collaboration and ordered phases"
            )
    if "phase-freeze" in reasons and (len(lane_orders) < 2 or not topology.get("handoffs")):
        raise TopologyError(
            "phase-freeze requires at least two execution lanes and a verified handoff"
        )


def iter_evidence(topology: dict) -> Iterator[tuple[str, object]]:
    boundaries = topology.get("boundaries", [])
    for index, boundary in enumerate(boundaries if isinstance(boundaries, list) else []):
        if not isinstance(boundary, dict):
            continue
        yield f"topology.boundaries[{index}].evidence", boundary.get("evidence")
        persistence = boundary.get("persistence")
        if isinstance(persistence, dict):
            yield (
                f"topology.boundaries[{index}].persistence.evidence",
                persistence.get("evidence"),
            )
    for kind in ("skills", "agents", "qualityPatternPolicies", "routingPolicies"):
        components = topology.get(kind, [])
        for index, component in enumerate(components if isinstance(components, list) else []):
            if isinstance(component, dict):
                yield f"topology.{kind}[{index}].evidence", component.get("evidence")


def evidence_paths(topology: dict) -> set[str]:
    paths: set[str] = set()
    for _, values in iter_evidence(topology):
        if not isinstance(values, list):
            continue
        paths.update(
            item["path"]
            for item in values
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        )
    return paths


def validate_contract(topology_value: object, capability_value: object) -> list[str]:
    topology = require_object(topology_value, "topology")
    if "taskExecution" in topology or "taskExecutionClass" in topology:
        raise TopologyError("runtime task execution state cannot be stored in persistent topology")
    boundaries = [
        _validate_boundary(item, index)
        for index, item in enumerate(require_list(topology.get("boundaries"), "topology.boundaries"))
    ]
    boundary_ids = [item["id"] for item in boundaries]
    if len(boundary_ids) != len(set(boundary_ids)):
        raise TopologyError("topology.boundaries contains duplicate ids")
    decision_area_owners: dict[str, str] = {}
    for boundary in boundaries:
        for decision_area_id in boundary["decisionAreaIds"]:
            previous_owner = decision_area_owners.get(decision_area_id)
            if previous_owner is not None:
                raise TopologyError(
                    f"decisionAreaId {decision_area_id!r} is assigned to multiple boundaries: "
                    f"{previous_owner!r} and {boundary['id']!r}"
                )
            decision_area_owners[decision_area_id] = boundary["id"]
    _validate_dependency_graph(boundaries)
    warnings = _validate_classification(topology.get("classification"), boundaries)
    patterns = require_string_list(
        topology.get("collaborationPatterns"), "topology.collaborationPatterns"
    )
    if any(pattern not in COLLABORATION_PATTERNS for pattern in patterns):
        raise TopologyError("topology.collaborationPatterns contains an unknown pattern")
    if len(patterns) != len(set(patterns)):
        raise TopologyError("topology.collaborationPatterns contains duplicates")

    phase_orders, lane_orders = _validate_phases(topology.get("executionPhases"))
    _validate_components(
        topology, {boundary["id"]: boundary for boundary in boundaries}, phase_orders, lane_orders
    )
    quality_policies = _validate_quality_policies(
        topology.get("qualityPatternPolicies"), set(boundary_ids)
    )
    capability_policies = _validate_capability_policies(capability_value)
    _validate_routing_policies(
        topology.get("routingPolicies"),
        set(boundary_ids),
        set(patterns),
        quality_policies,
        capability_policies,
    )
    _validate_coordination_bindings(topology, boundaries, set(patterns), lane_orders)
    return warnings
