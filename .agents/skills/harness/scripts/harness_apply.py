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
import validate_harness
import harness_change_discipline
import harness_frontmatter
import harness_agent_contract
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
    try:
        return harness_frontmatter.parse(text)
    except harness_frontmatter.FrontmatterError as exc:
        raise PlanError(f"{label}: {exc}") from exc


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


def validate_evidence(root: Path, value: object, label: str, *, snapshot=None) -> list[dict]:
    own_snapshot = snapshot is None
    snapshot = snapshot if snapshot is not None else harness_state.EvidenceSnapshot()
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
            harness_state.validate_evidence_relative(relative)
            path, present = harness_state.resolve_lexical_regular_inside(
                root,
                relative,
                must_exist=True,
                label="evidence",
            )
        except harness_state.StateError as exc:
            raise PlanError(f"invalid {label}[{index}].path: {exc}") from exc
        if not present:
            raise PlanError(f"{label}[{index}].path does not exist: {relative}")
        if not isinstance(claim, str) or not claim.strip():
            raise PlanError(f"{label}[{index}].claim must be a non-empty string")
        if not isinstance(expected_hash, str) or not HASH_RE.fullmatch(expected_hash):
            raise PlanError(f"{label}[{index}].sha256 must be a SHA-256 hash")
        content, actual_hash = snapshot.read(path)
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
                line_count = snapshot.line_count(path)
            except (OSError, UnicodeError) as exc:
                raise PlanError(
                    f"{label}[{index}] uses lines for a non-UTF-8 file: {relative}"
                ) from exc
            if end > line_count:
                raise PlanError(
                    f"{label}[{index}].lines ends at {end}, but {relative} has {line_count} lines"
                )
        validated.append(entry)
    if own_snapshot:
        snapshot.verify()
    return validated


def validate_project(root: Path, plan: dict, *, snapshot=None) -> dict:
    project = require_object(plan.get("project"), "project")
    summary = project.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise PlanError("project.summary must be a non-empty string")
    validate_evidence(root, project.get("evidence"), "project.evidence", snapshot=snapshot)
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


def validate_topology(root: Path, plan: dict, artifacts: dict[str, str], *, snapshot=None) -> tuple[dict, list[str]]:
    topology = require_object(plan.get("topology"), "topology")
    capability_policies = plan.get("capabilityPolicies")
    try:
        warnings = harness_topology.validate_contract(topology, capability_policies)
        harness_topology.validate_scope_paths(root, topology)
    except harness_topology.TopologyError as exc:
        raise PlanError(str(exc)) from exc

    undeclared = harness_state.undeclared_entrypoints(artifacts, topology)
    if undeclared:
        raise PlanError("native entry points must be declared in topology: " + ", ".join(undeclared))
    reference_errors = harness_state.missing_markdown_references(root, artifacts)
    if reference_errors:
        raise PlanError("; ".join(reference_errors))

    for label, evidence in harness_topology.iter_evidence(topology):
        validate_evidence(root, evidence, label, snapshot=snapshot)

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
            harness_agent_contract.validate(data["developer_instructions"], agent, topology)
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
    # Native project instructions replace per-conversation activation prompts.
    guidance = (
        "Read `.agents/skills/project-harness/SKILL.md` before project work and follow its routing contract. "
        "Use generated skills and agents only when their responsibilities fit the task; handle simple work directly. "
        "Reuse this project harness in new and resumed Codex conversations without inserting a bootstrap user turn.\n\n"
        "At first use or after a change notice, check the needed managed component against `.harness/manifest.json`; "
        "reuse that verified revision during the conversation instead of auditing every turn. "
        "If managed files are missing, altered, or a Harness transaction is pending, report the problem and use "
        "`harness-codex doctor`; do not silently use damaged components or repair their hashes. "
        "Changed or deleted source evidence requires reading current source, not blocking ordinary work or regenerating the harness. "
        "Use `harness-codex config` when persistent responsibilities need review.\n\n"
        "Follow existing project instructions and native Codex permission, sandbox and approval settings. "
        "Editing files does not authorize commit or push; honor only explicit authorization within its stated scope. "
        "Do not change Git metadata during harness configuration.\n\n"
        "Maintenance is opt-in. Follow trusted native maintenance-hook notices and "
        "`.agents/skills/harness/references/maintenance.md` only for eligible bounded reviews. "
        "Do not review or rewrite the harness every turn or add agents merely because scope grows."
    )
    if guidance not in extracted:
        extracted = extracted.replace(harness_state.END_MARKER, guidance + "\n" + harness_state.END_MARKER)
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
        # All new bytes belong inside the delimiters. Removal can therefore
        # recover even an empty file or a user file without a final newline.
        return existing + managed_block.rstrip()
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
    if type(manifest.get("schemaVersion")) is not int or manifest.get("schemaVersion") not in {
        harness_state.UPGRADE_SOURCE_SCHEMA_VERSION,
        harness_state.LOCAL_ONLY_UPGRADE_SOURCE_SCHEMA_VERSION,
        harness_state.CURRENT_SCHEMA_VERSION,
        harness_metadata.PREVIOUS_MANIFEST_SCHEMA_VERSION,
    }:
        raise PlanError(
            f"existing manifest must be schemaVersion {harness_state.UPGRADE_SOURCE_SCHEMA_VERSION} "
            f", {harness_state.LOCAL_ONLY_UPGRADE_SOURCE_SCHEMA_VERSION}, or "
            f"6, or {harness_state.CURRENT_SCHEMA_VERSION} before a project-local upgrade"
        )
    if manifest.get("schemaVersion") in {harness_metadata.PREVIOUS_MANIFEST_SCHEMA_VERSION, harness_state.CURRENT_SCHEMA_VERSION}:
        try:
            # A valid incoming plan does not authorize replacing an unsupported
            # installed contract. Known legacy installations still use the
            # reviewed regeneration path, with all ownership checks below.
            harness_metadata.artifact_contract_state(manifest)
        except ValueError as exc:
            raise PlanError(f"existing manifest artifact compatibility: {exc}; apply refused") from exc
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
        if not harness_transaction.is_allowed_target(relative):
            raise PlanError(f"existing managed path cannot enter project artifact ownership: {relative!r}; apply refused")
        by_path[relative] = entry
        state = harness_state.entry_status(root, entry)
        if state.get("state") != "unchanged":
            raise PlanError(f"managed file {relative!r} is {state.get('state')}; apply refused")
    if manifest.get("schemaVersion") in {
        harness_metadata.PREVIOUS_MANIFEST_SCHEMA_VERSION, harness_state.CURRENT_SCHEMA_VERSION
    }:
        # Re-analysis may intentionally replace stale evidence. Installed contracts,
        # however, must remain intact before a reviewed replacement is accepted.
        validator = validate_harness.Validator(root)
        validator.manifest = manifest
        validator.validate_manifest_shape()
        validator.validate_topology()
        validator.validate_managed_files()
        validator.validate_root_pointer()
        try:
            harness_workspace.validate_manifest_protection(root, manifest.get("workspace"), by_path)
        except harness_workspace.WorkspaceError as exc:
            validator.error(str(exc))
        if validator.errors:
            raise PlanError("existing installation contract is invalid; apply refused: " + "; ".join(validator.errors))
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
    if type(plan.get("artifactContractVersion")) is not int or plan.get("artifactContractVersion") != harness_metadata.ARTIFACT_CONTRACT_VERSION:
        raise PlanError("plan requires artifactContractVersion 2; rebuild a reviewed Authoring Contract 3 draft")
    try:
        root_context = inventory.require_workspace_root(root)
    except ValueError as exc:
        raise PlanError(str(exc)) from exc
    harness_transaction.ensure_no_pending_transaction(root)
    reject_runtime_state(plan)
    snapshot = harness_state.EvidenceSnapshot()
    project = validate_project(root, plan, snapshot=snapshot)
    artifacts, artifact_modes = validate_artifacts(root, plan)
    topology, topology_warnings = validate_topology(root, plan, artifacts, snapshot=snapshot)
    snapshot.verify()
    capability_policies = require_list(plan.get("capabilityPolicies"), "capabilityPolicies")
    managed_block = validate_instruction(plan)
    manifest_path = harness_state.resolve_inside(root, ".harness/manifest.json")
    manifest_bytes = manifest_path.read_bytes() if manifest_path.exists() else None
    manifest_mode = harness_state.current_mode(manifest_path) if manifest_bytes is not None else harness_state.DEFAULT_FILE_MODE
    manifest, old_managed = existing_manifest_state(root)
    try:
        instruction_relative = harness_state.active_instruction_relative(root)
    except harness_state.StateError as exc:
        raise PlanError(f"could not discover project instructions: {exc}") from exc
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
    instruction_exists = instruction_path.is_file()
    instruction_bytes = instruction_path.read_bytes() if instruction_exists else b""
    instruction_original_mode = harness_state.current_mode(instruction_path) if instruction_exists else harness_state.DEFAULT_FILE_MODE
    existing_instruction = instruction_bytes.decode("utf-8")
    has_markers = (
        harness_state.BEGIN_MARKER in existing_instruction or harness_state.END_MARKER in existing_instruction
    )
    managed_instruction = old_managed.get(instruction_relative)
    if has_markers and (
        managed_instruction is None or managed_instruction.get("kind") != "managed-block"
    ):
        raise PlanError(f"instruction block in {instruction_relative} is not owned by Harness")
    # Configuration authorizes adding our delimited pointer; never replace the
    # user's surrounding instructions or claim ownership of their content.
    instruction_mode = "managed-pointer"

    merged_instruction: str | None = None
    if instruction_mode == "managed-pointer":
        merged_instruction = merge_managed_block(existing_instruction, managed_block)
        if not instruction_exists:
            # Preserve the established generated-only file shape. Existing user
            # files receive no bytes outside the owned block, including newline.
            merged_instruction += "\n"
            instruction_action = "create"
        else:
            instruction_action = "unchanged" if merged_instruction == existing_instruction else "update"
        actions.append(
            {"path": instruction_relative, "action": instruction_action, "kind": "managed-block"}
        )
        if instruction_action != "create":
            original_hashes[instruction_relative] = harness_state.digest_bytes(
                instruction_bytes
            )
            original_modes[instruction_relative] = instruction_original_mode
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

    workspace_manifest = {
        "scope": harness_workspace.LOCAL_SCOPE,
        "kind": root_context["workspaceKind"],
        "instructionMode": instruction_mode,
        "gitProtection": {
            "mode": "not-managed",
            "patterns": [],
        },
    }

    desired_manifest = {
        "schemaVersion": harness_state.CURRENT_SCHEMA_VERSION,
        "artifactContractVersion": harness_metadata.ARTIFACT_CONTRACT_VERSION,
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
    current_bytes = manifest_path.read_bytes() if manifest_path.exists() else None
    if current_bytes != manifest_bytes or (manifest_bytes is not None and not harness_state.mode_matches(manifest_path, manifest_mode)):
        raise PlanError("manifest changed during application planning; retry against the current installation")
    if manifest_bytes is None:
        manifest_action = "create"
    else:
        manifest_action = (
            "unchanged" if manifest_bytes.decode("utf-8") == manifest_text else "update"
        )
    actions.append({"path": ".harness/manifest.json", "action": manifest_action})
    if manifest_action != "create":
        original_hashes[".harness/manifest.json"] = harness_state.digest_bytes(
            manifest_bytes
        )
        original_modes[".harness/manifest.json"] = manifest_mode
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
        "manifestPath": manifest_path,
        "manifestText": manifest_text,
        "originalHashes": original_hashes,
        "originalModes": original_modes,
        "desiredModes": desired_modes,
        "managedPreconditions": list(old_managed.values()),
        "evidencePreconditions": {
            item["path"]: item["sha256"] for item in project["evidence"] +
            [entry for _, entries in harness_topology.iter_evidence(topology) for entry in entries]
        },
        "report": {
            "runtime": harness_state.RUNTIME,
            "valid": True,
            "actions": actions,
            "removalCandidates": removal_candidates,
            "warnings": topology_warnings,
            "workspace": workspace_manifest,
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
    root = application["manifestPath"].parents[1]
    with harness_transaction.project_lock(root):
        return _apply_application(application)


def _apply_application(application: dict) -> dict:
    action_by_path = application_actions(application)
    desired_modes = application_modes(application)
    root = application["manifestPath"].parents[1]
    for relative, expected in application["evidencePreconditions"].items():
        path = harness_state.resolve_inside(root, relative, must_exist=True)
        if harness_state.digest_bytes(path.read_bytes()) != expected:
            raise PlanError(f"source evidence changed before apply; review the current source: {relative}")
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
