#!/usr/bin/env python3
"""Materialize deterministic contracts in a draft generation plan."""

from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import harness_change_discipline
import harness_metadata
import harness_teamplay


PROJECT_PLACEHOLDER = "{{HARNESS_PROJECT_CHANGE_DISCIPLINE_V1}}"
WRITER_PLACEHOLDER = "{{HARNESS_WRITER_CHANGE_DISCIPLINE_V1}}"
PROJECT_TEAMPLAY_PLACEHOLDER = "{{HARNESS_PROJECT_TEAMPLAY_V2}}"
AGENT_TEAMPLAY_PLACEHOLDER = "{{HARNESS_AGENT_TEAMPLAY_V2}}"


class PlanBuilderError(ValueError):
    pass


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanBuilderError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise PlanBuilderError(f"{label} must be an array")
    return value


def _materialize_contract(value: str, placeholder: str, canonical: str, label: str) -> str:
    """Replace one placeholder, or preserve one already-materialized canonical block."""
    normalized_value = harness_change_discipline.normalize_line_endings(value)
    normalized_canonical = harness_change_discipline.normalize_line_endings(canonical)
    placeholder_count = value.count(placeholder)
    canonical_count = normalized_value.count(normalized_canonical)
    if placeholder_count == 1 and canonical_count == 0:
        return value.replace(placeholder, canonical)
    if placeholder_count == 0 and canonical_count == 1:
        return value
    raise PlanBuilderError(
        f"{label} must contain {placeholder} exactly once before materialization "
        "or the canonical contract exactly once afterward"
    )


def _agent_paths(topology: dict[str, Any]) -> tuple[set[str], set[str]]:
    agents: set[str] = set()
    writers: set[str] = set()
    for index, raw in enumerate(_require_list(topology.get("agents"), "topology.agents")):
        agent = _require_object(raw, f"topology.agents[{index}]")
        name = agent.get("name")
        path = agent.get("path")
        if not isinstance(name, str) or not name or not isinstance(path, str) or not path:
            raise PlanBuilderError(f"topology.agents[{index}] has an invalid name or path")
        agents.add(path)
        accesses = _require_list(agent.get("fileAccess"), f"topology.agents[{index}].fileAccess")
        if any(isinstance(item, dict) and item.get("mode") == "write" for item in accesses):
            writers.add(path)
    return agents, writers


def _normalize_capability_policies(plan: dict[str, Any]) -> None:
    policies = _require_list(plan.get("capabilityPolicies"), "capabilityPolicies")
    for index, raw in enumerate(policies):
        policy = _require_object(raw, f"capabilityPolicies[{index}]")
        capabilities = _require_list(
            policy.get("requiredCapabilities"),
            f"capabilityPolicies[{index}].requiredCapabilities",
        )
        try:
            normalized = [
                harness_teamplay.normalize_capability_id(capability)
                for capability in capabilities
            ]
        except harness_teamplay.TeamplayError as exc:
            raise PlanBuilderError(str(exc)) from exc
        if len(normalized) != len(set(normalized)):
            raise PlanBuilderError(
                f"capabilityPolicies[{index}].requiredCapabilities contains duplicates "
                "after alias normalization"
            )
        policy["requiredCapabilities"] = normalized


def materialize_plan(value: Any) -> dict[str, Any]:
    """Return a Schema 3 plan with canonical contracts substituted exactly once."""
    plan = copy.deepcopy(_require_object(value, "plan"))
    if plan.get("schemaVersion") != harness_metadata.PLAN_SCHEMA_VERSION:
        raise PlanBuilderError(
            f"plan schemaVersion must be {harness_metadata.PLAN_SCHEMA_VERSION}"
    )
    topology = _require_object(plan.get("topology"), "topology")
    _normalize_capability_policies(plan)
    agent_paths, writer_paths = _agent_paths(topology)
    project_path = ".agents/skills/project-harness/SKILL.md"
    expected_paths = agent_paths | {project_path}

    artifacts = _require_list(plan.get("artifacts"), "artifacts")
    by_path: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(artifacts):
        artifact = _require_object(raw, f"artifacts[{index}]")
        path = artifact.get("path")
        content = artifact.get("content")
        if not isinstance(path, str) or not path:
            raise PlanBuilderError(f"artifacts[{index}].path must be non-empty text")
        if path in by_path:
            raise PlanBuilderError(f"duplicate artifact path: {path}")
        if not isinstance(content, str):
            raise PlanBuilderError(f"artifact {path} content must be text")
        by_path[path] = artifact

    missing = expected_paths - set(by_path)
    if missing:
        raise PlanBuilderError(
            "missing deterministic contract targets: " + ", ".join(sorted(missing))
        )

    unexpected: list[str] = []
    for path, artifact in by_path.items():
        content = artifact["content"]
        if path == project_path:
            content = _materialize_contract(
                content,
                PROJECT_PLACEHOLDER,
                harness_change_discipline.PROJECT_BLOCK,
                path,
            )
            artifact["content"] = _materialize_contract(
                content,
                PROJECT_TEAMPLAY_PLACEHOLDER,
                harness_teamplay.PROJECT_BLOCK,
                path,
            )
            harness_change_discipline.require_exactly_once(
                artifact["content"], harness_change_discipline.PROJECT_BLOCK, path
            )
            harness_teamplay.require_exactly_once(
                artifact["content"], harness_teamplay.PROJECT_BLOCK, path
            )
        elif path in agent_paths:
            if path in writer_paths:
                content = _materialize_contract(
                    content,
                    WRITER_PLACEHOLDER,
                    harness_change_discipline.WRITER_BLOCK,
                    path,
                )
            artifact["content"] = _materialize_contract(
                content,
                AGENT_TEAMPLAY_PLACEHOLDER,
                harness_teamplay.AGENT_BLOCK,
                path,
            )
            if path in writer_paths:
                harness_change_discipline.require_exactly_once(
                    artifact["content"], harness_change_discipline.WRITER_BLOCK, path
                )
            harness_teamplay.require_exactly_once(
                artifact["content"], harness_teamplay.AGENT_BLOCK, path
            )
        elif any(
            placeholder in content
            for placeholder in (
                PROJECT_PLACEHOLDER,
                WRITER_PLACEHOLDER,
                PROJECT_TEAMPLAY_PLACEHOLDER,
                AGENT_TEAMPLAY_PLACEHOLDER,
            )
        ):
            unexpected.append(path)
    if unexpected:
        raise PlanBuilderError(
            "deterministic contract placeholder appears in an unsupported artifact: "
            + ", ".join(sorted(unexpected))
        )
    remaining = [
        path
        for path, artifact in by_path.items()
        if any(
            placeholder in artifact["content"]
            for placeholder in (
                PROJECT_PLACEHOLDER,
                WRITER_PLACEHOLDER,
                PROJECT_TEAMPLAY_PLACEHOLDER,
                AGENT_TEAMPLAY_PLACEHOLDER,
            )
        )
    ]
    if remaining:
        raise PlanBuilderError(
            "deterministic contract placeholder remains after materialization: "
            + ", ".join(sorted(remaining))
        )
    return plan


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Draft Schema 3 plan")
    parser.add_argument("--output", required=True, help="Materialized Schema 3 plan")
    args = parser.parse_args()
    try:
        source = Path(args.input).resolve()
        output = Path(args.output).resolve()
        plan = json.loads(source.read_text(encoding="utf-8"))
        materialized = materialize_plan(plan)
        _write_json_atomic(output, materialized)
        print(
            json.dumps(
                {
                    "schemaVersion": harness_metadata.PLAN_SCHEMA_VERSION,
                    "materialized": True,
                    "output": output.name,
                    "warnings": [],
                    "errors": [],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, PlanBuilderError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schemaVersion": harness_metadata.PLAN_SCHEMA_VERSION,
                    "materialized": False,
                    "warnings": [],
                    "errors": [str(exc)],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
