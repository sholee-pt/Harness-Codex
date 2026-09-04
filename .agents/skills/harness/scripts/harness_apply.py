#!/usr/bin/env python3
"""Validate and safely apply a structured Codex Harness generation plan."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import harness_metadata
import harness_state
import harness_teamplay
import harness_topology
import harness_transaction
import harness_workspace
import harness_change_discipline
import inventory

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ is required
    tomllib = None


PLAN_SCHEMA_VERSION = harness_metadata.PLAN_SCHEMA_VERSION
GENERATOR_VERSION = harness_metadata.HARNESS_VERSION
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_PREFIXES = (".codex/agents/", ".agents/skills/")
FORBIDDEN_TOKENS = (
    "TeamCreate",
    "TeamDelete",
    "team_name",
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",
)
FORBIDDEN_PERSISTENT_KEYS = {
    "currentTask",
    "runtimeExecutionPlan",
    "runtimeMessages",
    "runtimeParticipants",
    "runtimePlan",
    "runtimeRole",
    "runtimeTasks",
    "runtimeTeam",
    "taskExecution",
    "taskExecutionClass",
}


class PlanError(ValueError):
    pass


def reject_runtime_state(value: object, label: str = "plan") -> None:
    pending: list[tuple[str, object]] = [(label, value)]
    while pending:
        current_label, current = pending.pop()
        if isinstance(current, dict):
            forbidden = FORBIDDEN_PERSISTENT_KEYS.intersection(current)
            if forbidden:
                raise PlanError(
                    f"{current_label} contains runtime-only fields: "
                    + ", ".join(sorted(forbidden))
                )
            pending.extend(
                (f"{current_label}.{key}", item) for key, item in current.items()
            )
        elif isinstance(current, list):
            pending.extend(
                (f"{current_label}[{index}]", item)
                for index, item in enumerate(current)
            )


def require_object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise PlanError(f"{label} must be an object")
    return value


def require_list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise PlanError(f"{label} must be an array")
    return value


def read_frontmatter_text(text: str, label: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise PlanError(f"{label} is missing opening YAML frontmatter delimiter")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise PlanError(f"{label} is missing closing YAML frontmatter delimiter") from exc
    values: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise PlanError(f"{label} contains unsupported frontmatter: {line}")
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_plan(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanError(f"invalid plan: {exc}") from exc
    plan = require_object(data, "plan")
    if plan.get("schemaVersion") != PLAN_SCHEMA_VERSION:
        raise PlanError(f"plan schemaVersion must be {PLAN_SCHEMA_VERSION}")
    if "authoringContractVersion" in plan:
        raise PlanError(
            "plan still contains authoringContractVersion; materialize the draft before apply"
        )
    reject_runtime_state(plan)
    return plan


def validate_evidence(root: Path, value: object, label: str) -> list[dict]:
    evidence = require_list(value, label)
    if not evidence:
        raise PlanError(f"{label} must contain at least one evidence object")
    validated: list[dict] = []
    for index, item in enumerate(evidence):
        entry = require_object(item, f"{label}[{index}]")
        relative = entry.get("path")
        claim = entry.get("claim")
        expected_hash = entry.get("sha256")
        if not isinstance(relative, str):
            raise PlanError(f"{label}[{index}].path must be text")
        try:
            path = harness_state.resolve_inside(root, relative)
        except harness_state.StateError as exc:
            raise PlanError(f"invalid {label}[{index}].path: {exc}") from exc
        if not path.is_file():
            raise PlanError(f"{label}[{index}].path does not exist: {relative}")
        if not isinstance(claim, str) or not claim.strip():
            raise PlanError(f"{label}[{index}].claim must be a non-empty string")
        if not isinstance(expected_hash, str) or not HASH_RE.fullmatch(expected_hash):
            raise PlanError(f"{label}[{index}].sha256 must be a SHA-256 hash")
        actual_hash = harness_state.digest_bytes(path.read_bytes())
        if actual_hash != expected_hash:
            raise PlanError(f"{label}[{index}] changed after analysis: {relative}")
        lines = entry.get("lines")
        if lines is not None:
            line_range = require_object(lines, f"{label}[{index}].lines")
            start = line_range.get("start")
            end = line_range.get("end")
            if (
                not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(end, int)
                or isinstance(end, bool)
                or start < 1
                or end < start
            ):
                raise PlanError(
                    f"{label}[{index}].lines must contain integers with 1 <= start <= end"
                )
            try:
                line_count = len(path.read_text(encoding="utf-8").splitlines())
            except (OSError, UnicodeError) as exc:
                raise PlanError(
                    f"{label}[{index}] uses lines for a non-UTF-8 file: {relative}"
                ) from exc
            if end > line_count:
                raise PlanError(
                    f"{label}[{index}].lines ends at {end}, but {relative} has {line_count} lines"
                )
        validated.append(entry)
    return validated


def validate_project(root: Path, plan: dict) -> dict:
    project = require_object(plan.get("project"), "project")
    summary = project.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise PlanError("project.summary must be a non-empty string")
    validate_evidence(root, project.get("evidence"), "project.evidence")
    rationale = require_object(project.get("rationale"), "project.rationale")
    rationale_summary = rationale.get("summary")
    if not isinstance(rationale_summary, str) or not rationale_summary.strip():
        raise PlanError("project.rationale.summary must be a non-empty string")
    uncertainties = require_list(rationale.get("uncertainties"), "project.rationale.uncertainties")
    if not all(isinstance(item, str) for item in uncertainties):
        raise PlanError("project.rationale.uncertainties entries must be strings")
    return project


def validate_artifacts(root: Path, plan: dict) -> tuple[dict[str, str], dict[str, int]]:
    artifact_items = require_list(plan.get("artifacts"), "artifacts")
    artifacts: dict[str, str] = {}
    modes: dict[str, int] = {}
    for index, item in enumerate(artifact_items):
        artifact = require_object(item, f"artifacts[{index}]")
        relative = artifact.get("path")
        content = artifact.get("content")
        mode_value = artifact.get("mode")
        if not isinstance(relative, str) or not relative.startswith(ALLOWED_PREFIXES):
            raise PlanError(f"artifact path is outside Codex Harness output roots: {relative!r}")
        if not harness_transaction.is_allowed_target(relative):
            raise PlanError(f"artifact path is not a supported Codex Harness target: {relative!r}")
        if relative in artifacts:
            raise PlanError(f"duplicate artifact path: {relative}")
        if not isinstance(content, str):
            raise PlanError(f"artifact content must be text: {relative}")
        try:
            mode = harness_state.parse_mode(mode_value, f"artifact mode for {relative}")
        except harness_state.StateError as exc:
            raise PlanError(str(exc)) from exc
        harness_state.resolve_inside(root, relative)
        if any(token in content for token in FORBIDDEN_TOKENS):
            raise PlanError(f"artifact contains an obsolete runtime token: {relative}")
        artifacts[relative] = content
        modes[relative] = mode
    try:
        harness_state.validate_file_namespace(artifacts, label="plan artifacts")
    except harness_state.StateError as exc:
        raise PlanError(str(exc)) from exc
    return artifacts, modes


def validate_directory_workspace_writers(root_context: dict, topology: dict) -> None:
    try:
        harness_workspace.validate_directory_workspace_writers(root_context, topology)
    except harness_workspace.WorkspaceError as exc:
        raise PlanError(str(exc)) from exc


def validate_topology(root: Path, plan: dict, artifacts: dict[str, str]) -> tuple[dict, list[str]]:
    topology = require_object(plan.get("topology"), "topology")
    capability_policies = plan.get("capabilityPolicies")
    try:
        warnings = harness_topology.validate_contract(topology, capability_policies)
    except harness_topology.TopologyError as exc:
        raise PlanError(str(exc)) from exc

    validate_directory_workspace_writers(inventory.inspect_root_context(root), topology)

    for label, evidence in harness_topology.iter_evidence(topology):
        validate_evidence(root, evidence, label)

    agents = require_list(topology.get("agents"), "topology.agents")
    skills = require_list(topology.get("skills"), "topology.skills")

    known_skills: set[str] = set()
    for index, item in enumerate(skills):
        skill = require_object(item, f"topology.skills[{index}]")
        name = skill.get("name")
        relative = skill.get("path")
        if not isinstance(name, str) or not SKILL_NAME_RE.fullmatch(name):
            raise PlanError(f"invalid skill name: {name!r}")
        if name in known_skills:
            raise PlanError(f"duplicate skill name: {name}")
        known_skills.add(name)
        purpose = skill.get("purpose")
        if not isinstance(purpose, str) or not purpose.strip():
            raise PlanError(f"skill {name} purpose must be a non-empty string")
        expected = f".agents/skills/{name}/SKILL.md"
        if relative != expected:
            raise PlanError(f"skill {name} path must be {expected}")
        content = artifacts.get(expected)
        if content is None:
            raise PlanError(f"skill entry point is missing from artifacts: {expected}")
        frontmatter = read_frontmatter_text(content, expected)
        if frontmatter.get("name") != name or not frontmatter.get("description"):
            raise PlanError(f"skill frontmatter is incomplete or mismatched: {expected}")

    if "project-harness" not in known_skills:
        raise PlanError("topology must include the project-harness skill")
    project_harness = artifacts.get(".agents/skills/project-harness/SKILL.md")
    if project_harness is None:
        raise PlanError("project-harness skill artifact is missing")
    try:
        harness_change_discipline.require_exactly_once(
            project_harness,
            harness_change_discipline.PROJECT_BLOCK,
            "project-harness skill",
        )
    except ValueError as exc:
        raise PlanError(str(exc)) from exc
    try:
        harness_teamplay.require_exactly_once(
            project_harness,
            harness_teamplay.PROJECT_BLOCK,
            "project-harness skill",
        )
    except ValueError as exc:
        raise PlanError(str(exc)) from exc

    known_agents: set[str] = set()
    for index, item in enumerate(agents):
        agent = require_object(item, f"topology.agents[{index}]")
        name = agent.get("name")
        relative = agent.get("path")
        if not isinstance(name, str) or not AGENT_NAME_RE.fullmatch(name):
            raise PlanError(f"invalid Codex agent name: {name!r}")
        if name in known_agents:
            raise PlanError(f"duplicate agent name: {name}")
        known_agents.add(name)
        for field in ("responsibility", "whyDelegate"):
            value = agent.get(field)
            if not isinstance(value, str) or not value.strip():
                raise PlanError(f"agent {name} {field} must be a non-empty string")
        expected = f".codex/agents/{name}.toml"
        if relative != expected:
            raise PlanError(f"agent {name} path must be {expected}")
        content = artifacts.get(expected)
        if content is None:
            raise PlanError(f"agent definition is missing from artifacts: {expected}")
        if tomllib is None:
            raise PlanError("Python 3.11+ is required to parse Codex agent TOML")
        try:
            data = tomllib.loads(content)
        except tomllib.TOMLDecodeError as exc:
            raise PlanError(f"invalid Codex agent TOML {expected}: {exc}") from exc
        for key in ("name", "description", "developer_instructions"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise PlanError(f"Codex agent {expected} is missing {key}")
        if data["name"] != name:
            raise PlanError(f"Codex agent name mismatch in {expected}")
        try:
            harness_teamplay.require_exactly_once(
                data["developer_instructions"],
                harness_teamplay.AGENT_BLOCK,
                f"agent {name}",
            )
        except ValueError as exc:
            raise PlanError(str(exc)) from exc
        file_access = require_list(agent.get("fileAccess"), f"agent {name} fileAccess")
        is_writer = any(
            isinstance(access, dict) and access.get("mode") == "write"
            for access in file_access
        )
        if is_writer:
            try:
                harness_change_discipline.require_exactly_once(
                    data["developer_instructions"],
                    harness_change_discipline.WRITER_BLOCK,
                    f"writer agent {name}",
                )
            except ValueError as exc:
                raise PlanError(str(exc)) from exc
        linked_skills = require_list(agent.get("skills", []), f"agent {name} skills")
        for linked_skill in linked_skills:
            if linked_skill not in known_skills:
                raise PlanError(f"agent {name} references unknown skill {linked_skill!r}")
            if linked_skill not in data["developer_instructions"]:
                raise PlanError(
                    f"agent {name} must mention linked skill {linked_skill!r} in developer_instructions"
                )
    return topology, warnings


def validate_instruction(plan: dict) -> str:
    instruction = require_object(plan.get("instruction"), "instruction")
    managed_block = instruction.get("managedBlock")
    if not isinstance(managed_block, str):
        raise PlanError("instruction.managedBlock must be text")
    try:
        extracted = harness_state.extract_managed_block(managed_block)
    except harness_state.StateError as exc:
        raise PlanError(str(exc)) from exc
    if extracted.strip() != managed_block.strip():
        raise PlanError("instruction.managedBlock must contain only the managed block")
    if "$project-harness" not in managed_block:
        raise PlanError("instruction.managedBlock must explicitly reference $project-harness")
    return extracted


def evidence_paths(project: dict, topology: dict) -> set[str]:
    paths = {
        item["path"]
        for item in project["evidence"]
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    paths.update(harness_topology.evidence_paths(topology))
    return paths


def merge_managed_block(existing: str, managed_block: str) -> str:
    begin_count = existing.count(harness_state.BEGIN_MARKER)
    end_count = existing.count(harness_state.END_MARKER)
    if begin_count == 0 and end_count == 0:
        separator = "" if not existing else ("\n" if existing.endswith("\n") else "\n\n")
        return f"{existing}{separator}{managed_block.rstrip()}\n"
    if begin_count != 1 or end_count != 1:
        raise PlanError("active instruction file contains incomplete or duplicate Harness markers")
    old_block = harness_state.extract_managed_block(existing)
    start = existing.index(old_block)
    return f"{existing[:start]}{managed_block.rstrip()}{existing[start + len(old_block):]}"


def managed_entry(
    relative: str, content: str, kind: str = "file", mode: int | None = None
) -> dict:
    entry = {
        "path": relative,
        "kind": kind,
        "sha256": harness_state.digest_bytes(content.encode("utf-8")),
    }
    if kind == "file":
        if mode is None:
            raise PlanError(f"managed file mode is missing: {relative}")
        entry["mode"] = harness_state.mode_text(mode)
    return entry


def existing_manifest_state(root: Path) -> tuple[dict | None, dict[str, dict]]:
    _, manifest = harness_state.load_manifest(root)
    if manifest is None:
        return None, {}
    harness_state.validate_runtime(manifest)
    if manifest.get("schemaVersion") not in {
        harness_state.UPGRADE_SOURCE_SCHEMA_VERSION,
        harness_state.LOCAL_ONLY_UPGRADE_SOURCE_SCHEMA_VERSION,
        harness_state.CURRENT_SCHEMA_VERSION,
    }:
        raise PlanError(
            f"existing manifest must be schemaVersion {harness_state.UPGRADE_SOURCE_SCHEMA_VERSION} "
            f", {harness_state.LOCAL_ONLY_UPGRADE_SOURCE_SCHEMA_VERSION}, or "
            f"{harness_state.CURRENT_SCHEMA_VERSION} before a schema 6 upgrade"
        )
    if manifest.get("schemaVersion") == harness_state.UPGRADE_SOURCE_SCHEMA_VERSION:
        validate_project(root, manifest)
        legacy_topology = require_object(manifest.get("topology"), "existing topology")
        for kind in ("skills", "agents"):
            for index, item in enumerate(
                require_list(legacy_topology.get(kind), f"existing topology.{kind}")
            ):
                component = require_object(item, f"existing topology.{kind}[{index}]")
                validate_evidence(
                    root,
                    component.get("evidence"),
                    f"existing topology.{kind}[{index}].evidence",
                )
    entries = require_list(manifest.get("managedFiles"), "existing managedFiles")
    if not all(isinstance(entry, dict) for entry in entries):
        raise PlanError("existing managedFiles entries must be objects")
    by_path: dict[str, dict] = {}
    for entry in entries:
        relative = entry.get("path")
        if not isinstance(relative, str) or relative in by_path:
            raise PlanError(f"invalid or duplicate existing managed path: {relative!r}")
        by_path[relative] = entry
        state = harness_state.entry_status(root, entry)
        if state.get("state") != "unchanged":
            raise PlanError(f"managed file {relative!r} is {state.get('state')}; apply refused")
    return manifest, by_path


def classify_file(
    root: Path,
    relative: str,
    desired: str,
    desired_mode: int,
    managed: dict[str, dict],
) -> str:
    path = harness_state.resolve_inside(root, relative)
    if path.exists() and not path.is_file():
        raise PlanError(f"target path is not a regular file: {relative}")
    if not path.exists():
        return "create"
    if relative not in managed:
        raise PlanError(f"target path is user-owned and will not be overwritten: {relative}")
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PlanError(f"cannot read managed target {relative}: {exc}") from exc
    content_matches = current == desired
    mode_matches = harness_state.mode_matches(path, desired_mode)
    return "unchanged" if content_matches and mode_matches else "update"


def build_application(root: Path, plan: dict) -> dict:
    try:
        root_context = inventory.require_unambiguous_root(root)
    except ValueError as exc:
        raise PlanError(str(exc)) from exc
    harness_transaction.ensure_no_pending_transaction(root)
    reject_runtime_state(plan)
    project = validate_project(root, plan)
    artifacts, artifact_modes = validate_artifacts(root, plan)
    topology, topology_warnings = validate_topology(root, plan, artifacts)
    capability_policies = require_list(plan.get("capabilityPolicies"), "capabilityPolicies")
    managed_block = validate_instruction(plan)
    manifest, old_managed = existing_manifest_state(root)
    if manifest is None:
        try:
            protection_state = harness_workspace.inspect_local_protection(
                root, root_context["workspaceKind"]
            )
        except harness_workspace.WorkspaceError as exc:
            raise PlanError(str(exc)) from exc
        if protection_state["state"] not in {"absent", "not-applicable"}:
            raise PlanError(
                "local Git contains a Harness protection block without a manifest; "
                f"state={protection_state['state']}; inspect and remove it explicitly before retrying"
            )

    instruction_relative = harness_state.active_instruction_relative(root)
    planned_paths = set(artifacts) | {".harness/manifest.json"}
    overlap = sorted(evidence_paths(project, topology) & planned_paths)
    if overlap:
        raise PlanError(
            "evidence files cannot also be planned outputs: " + ", ".join(overlap)
        )
    old_instruction = manifest.get("instructionFile") if manifest else None
    if old_instruction is not None and old_instruction != instruction_relative:
        raise PlanError(
            f"active Codex instruction file changed from {old_instruction!r} to {instruction_relative!r}; "
            "resolve the instruction precedence change manually"
        )

    actions: list[dict] = []
    desired_entries: dict[str, dict] = {}
    original_hashes: dict[str, str] = {}
    original_modes: dict[str, int] = {}
    desired_modes: dict[str, int] = {}
    for relative, content in sorted(artifacts.items()):
        desired_mode = artifact_modes[relative]
        action = classify_file(root, relative, content, desired_mode, old_managed)
        actions.append({"path": relative, "action": action})
        desired_entries[relative] = managed_entry(relative, content, mode=desired_mode)
        desired_modes[relative] = desired_mode
        if action != "create":
            path = harness_state.resolve_inside(root, relative, must_exist=True)
            original_hashes[relative] = harness_state.digest_bytes(path.read_bytes())
            original_modes[relative] = harness_state.current_mode(path)

    instruction_path = harness_state.resolve_inside(root, instruction_relative)
    if instruction_path.exists() and not instruction_path.is_file():
        raise PlanError(f"instruction path is not a regular file: {instruction_relative}")
    existing_instruction = instruction_path.read_text(encoding="utf-8") if instruction_path.is_file() else ""
    has_markers = (
        harness_state.BEGIN_MARKER in existing_instruction or harness_state.END_MARKER in existing_instruction
    )
    managed_instruction = old_managed.get(instruction_relative)
    if has_markers and (
        managed_instruction is None or managed_instruction.get("kind") != "managed-block"
    ):
        raise PlanError(f"instruction block in {instruction_relative} is not owned by Harness")
    if managed_instruction is not None:
        instruction_mode = "managed-pointer"
    elif instruction_path.exists():
        instruction_mode = "explicit-skill"
    else:
        instruction_mode = "managed-pointer"

    merged_instruction: str | None = None
    if instruction_mode == "managed-pointer":
        merged_instruction = merge_managed_block(existing_instruction, managed_block)
        if not instruction_path.exists():
            instruction_action = "create"
        else:
            instruction_action = "unchanged" if merged_instruction == existing_instruction else "update"
        actions.append(
            {"path": instruction_relative, "action": instruction_action, "kind": "managed-block"}
        )
        if instruction_action != "create":
            original_hashes[instruction_relative] = harness_state.digest_bytes(
                instruction_path.read_bytes()
            )
            original_modes[instruction_relative] = harness_state.current_mode(instruction_path)
            desired_modes[instruction_relative] = original_modes[instruction_relative]
        else:
            desired_modes[instruction_relative] = harness_state.DEFAULT_FILE_MODE
        desired_entries[instruction_relative] = managed_entry(
            instruction_relative, managed_block, kind="managed-block"
        )
        planned_paths.add(instruction_relative)
    elif managed_instruction is not None:
        raise PlanError("a previously managed instruction pointer cannot be abandoned implicitly")

    late_overlap = sorted(evidence_paths(project, topology) & planned_paths)
    if late_overlap:
        raise PlanError(
            "evidence files cannot also be planned outputs: " + ", ".join(late_overlap)
        )

    removal_candidates = sorted(
        relative
        for relative, entry in old_managed.items()
        if relative not in desired_entries and entry.get("kind", "file") == "file"
    )
    for relative in removal_candidates:
        desired_entries[relative] = old_managed[relative]

    protected_paths = sorted(desired_entries)
    try:
        local_protection = harness_workspace.plan_local_protection(
            root, root_context["workspaceKind"], protected_paths
        )
    except harness_workspace.WorkspaceError as exc:
        raise PlanError(str(exc)) from exc

    workspace_manifest = {
        "scope": harness_workspace.LOCAL_SCOPE,
        "kind": root_context["workspaceKind"],
        "instructionMode": instruction_mode,
        "gitProtection": {
            "mode": local_protection["mode"],
            "patterns": local_protection["patterns"],
        },
    }

    desired_manifest = {
        "schemaVersion": harness_state.CURRENT_SCHEMA_VERSION,
        "generator": {
            "name": "Harness",
            "version": GENERATOR_VERSION,
            "runtime": harness_state.RUNTIME,
        },
        "application": {
            "mode": "journaled",
            "transactionSchemaVersion": harness_transaction.TRANSACTION_SCHEMA_VERSION,
        },
        "workspace": workspace_manifest,
        "instructionFile": instruction_relative if instruction_mode == "managed-pointer" else None,
        "project": project,
        "topology": topology,
        "capabilityPolicies": capability_policies,
        "managedFiles": sorted(desired_entries.values(), key=lambda item: item["path"]),
    }
    manifest_text = json.dumps(desired_manifest, indent=2, ensure_ascii=False) + "\n"
    manifest_path = root / ".harness" / "manifest.json"
    if not manifest_path.exists():
        manifest_action = "create"
    else:
        manifest_action = (
            "unchanged" if manifest_path.read_text(encoding="utf-8") == manifest_text else "update"
        )
    actions.append({"path": ".harness/manifest.json", "action": manifest_action})
    if manifest_action != "create":
        original_hashes[".harness/manifest.json"] = harness_state.digest_bytes(
            manifest_path.read_bytes()
        )
        original_modes[".harness/manifest.json"] = harness_state.current_mode(manifest_path)
        desired_modes[".harness/manifest.json"] = original_modes[".harness/manifest.json"]
    else:
        desired_modes[".harness/manifest.json"] = harness_state.DEFAULT_FILE_MODE

    return {
        "artifacts": artifacts,
        "artifactModes": artifact_modes,
        "instructionRelative": (
            instruction_relative if instruction_mode == "managed-pointer" else None
        ),
        "instructionPath": instruction_path,
        "instructionText": merged_instruction,
        "localProtection": local_protection,
        "protectedPaths": protected_paths,
        "manifestPath": manifest_path,
        "manifestText": manifest_text,
        "originalHashes": original_hashes,
        "originalModes": original_modes,
        "desiredModes": desired_modes,
        "managedPreconditions": list(old_managed.values()),
        "report": {
            "runtime": harness_state.RUNTIME,
            "valid": True,
            "actions": actions,
            "removalCandidates": removal_candidates,
            "warnings": topology_warnings,
            "workspace": workspace_manifest,
            "localProtection": {
                "mode": local_protection["mode"],
                "action": local_protection["action"],
                "patterns": local_protection["patterns"],
                "worktreeCount": local_protection["worktreeCount"],
            },
            "activation": (
                "managed-pointer"
                if instruction_mode == "managed-pointer"
                else "explicitly invoke $project-harness; the existing user instruction file was preserved"
            ),
        },
    }


def application_outputs(application: dict) -> dict[str, str]:
    outputs = dict(application["artifacts"])
    instruction_relative = application.get("instructionRelative")
    if instruction_relative is not None:
        outputs[instruction_relative] = application["instructionText"]
    outputs[".harness/manifest.json"] = application["manifestText"]
    try:
        harness_state.validate_file_namespace(outputs, label="application outputs")
    except harness_state.StateError as exc:
        raise PlanError(str(exc)) from exc
    return outputs


def application_actions(application: dict) -> dict[str, str]:
    report = application.get("report")
    if not isinstance(report, dict):
        raise PlanError("application must contain a report object")
    actions = report.get("actions")
    if not isinstance(actions, list):
        raise PlanError("application report must contain an action list")

    action_by_path: dict[str, str] = {}
    for item in actions:
        if not isinstance(item, dict):
            raise PlanError("application actions must be objects")
        relative = item.get("path")
        action = item.get("action")
        if not isinstance(relative, str) or relative in action_by_path:
            raise PlanError(f"invalid or duplicate application action path: {relative!r}")
        if action not in {"create", "update", "unchanged"}:
            raise PlanError(f"invalid application action for {relative!r}: {action!r}")
        action_by_path[relative] = action

    instruction_relative = application.get("instructionRelative")
    if instruction_relative is not None and not isinstance(instruction_relative, str):
        raise PlanError("application instructionRelative must be text or null")
    expected_paths = set(application["artifacts"]) | {".harness/manifest.json"}
    if instruction_relative is not None:
        expected_paths.add(instruction_relative)
    if set(action_by_path) != expected_paths:
        raise PlanError("application action paths do not match the planned outputs")
    return action_by_path


def application_modes(application: dict) -> dict[str, int]:
    modes = application.get("desiredModes")
    if not isinstance(modes, dict):
        raise PlanError("application is missing desiredModes")
    expected_paths = set(application_outputs(application))
    if set(modes) != expected_paths:
        raise PlanError("application desired mode paths do not match the planned outputs")
    for relative, mode in modes.items():
        if not isinstance(mode, int) or isinstance(mode, bool) or not 0 <= mode <= 0o777:
            raise PlanError(f"invalid desired mode for {relative}: {mode!r}")
    return modes


def apply_application(application: dict) -> dict:
    action_by_path = application_actions(application)
    desired_modes = application_modes(application)
    root = application["manifestPath"].parents[1]
    try:
        protection_result = harness_workspace.apply_local_protection(
            root, application["localProtection"], application["protectedPaths"]
        )
    except harness_workspace.WorkspaceError as exc:
        raise PlanError(str(exc)) from exc
    journal: dict | None = None
    try:
        journal = harness_transaction.prepare_transaction(
            root,
            application_outputs(application),
            action_by_path,
            application["originalHashes"],
            application["originalModes"],
            desired_modes,
            application["managedPreconditions"],
        )
        if journal is None:
            return {"state": "unchanged", "writes": 0, "cleaned": True}
        return harness_transaction.apply_transaction(root, journal)
    except Exception as apply_error:
        protection_changed = protection_result.get("action") not in {None, "unchanged"}
        manifest_was_already_current = (
            action_by_path.get(".harness/manifest.json") == "unchanged"
        )
        transaction_committed = journal is not None and journal.get("state") == "committed"
        if protection_changed and not manifest_was_already_current and not transaction_committed:
            try:
                pending = harness_state.transaction_status(root)
                if pending is None:
                    harness_workspace.rollback_local_protection(
                        root, application["localProtection"]
                    )
            except (OSError, UnicodeError, harness_state.StateError, harness_workspace.WorkspaceError) as rollback_error:
                raise PlanError(
                    "project apply failed and local Git protection could not be restored safely; "
                    f"original error: {apply_error}; protection recovery error: {rollback_error}"
                ) from apply_error
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--plan")
    parser.add_argument("--dry-run", action="store_true")
    maintenance = parser.add_mutually_exclusive_group()
    maintenance.add_argument("--recover", action="store_true")
    maintenance.add_argument("--inspect-transaction", action="store_true")
    maintenance.add_argument("--clean-orphaned-transaction", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f"workspace root is not a directory: {root}")
    maintenance_requested = (
        args.recover or args.inspect_transaction or args.clean_orphaned_transaction
    )
    if maintenance_requested:
        if args.plan or args.dry_run:
            parser.error("transaction maintenance cannot be combined with --plan or --dry-run")
    elif not args.plan:
        parser.error("--plan is required unless transaction maintenance is used")

    try:
        if args.recover:
            recovery = harness_transaction.recover_transaction(root)
            print(
                json.dumps(
                    {"runtime": harness_state.RUNTIME, "valid": True, "recovery": recovery},
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0
        if args.inspect_transaction:
            inspection = harness_transaction.inspect_transaction(root)
            print(
                json.dumps(
                    {"runtime": harness_state.RUNTIME, "valid": True, "transaction": inspection},
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0
        if args.clean_orphaned_transaction:
            cleanup = harness_transaction.clean_orphaned_workspace(root)
            print(
                json.dumps(
                    {"runtime": harness_state.RUNTIME, "valid": True, "cleanup": cleanup},
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0
        plan_path = Path(args.plan).resolve()
        if not plan_path.is_file():
            parser.error(f"plan is not a file: {plan_path}")
        application = build_application(root, load_plan(plan_path))
        report = application["report"]
        report["dryRun"] = args.dry_run
        if not args.dry_run:
            report["transaction"] = apply_application(application)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (
        OSError,
        UnicodeError,
        PlanError,
        harness_state.StateError,
        harness_transaction.TransactionError,
    ) as exc:
        print(
            json.dumps(
                {"runtime": harness_state.RUNTIME, "valid": False, "error": str(exc), "dryRun": args.dry_run},
                indent=2,
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
