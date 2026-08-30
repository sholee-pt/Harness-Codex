#!/usr/bin/env python3
"""Validate and safely apply a structured Codex Harness generation plan."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import harness_state
import harness_transaction

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ is required
    tomllib = None


PLAN_SCHEMA_VERSION = 1
GENERATOR_VERSION = "3.1.0"
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ALLOWED_PREFIXES = (".codex/agents/", ".agents/skills/")
ALLOWED_PATTERNS = {
    "pipeline",
    "fan-out/fan-in",
    "expert-pool",
    "producer-reviewer",
    "supervisor",
    "hierarchical-delegation",
}
FORBIDDEN_TOKENS = (
    "TeamCreate",
    "TeamDelete",
    "team_name",
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",
)


class PlanError(ValueError):
    pass


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
    return plan


def validate_project(plan: dict) -> dict:
    project = require_object(plan.get("project"), "project")
    summary = project.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise PlanError("project.summary must be a non-empty string")
    evidence = require_list(project.get("evidence"), "project.evidence")
    if not all(isinstance(item, str) and item.strip() for item in evidence):
        raise PlanError("project.evidence entries must be non-empty strings")
    rationale = require_object(project.get("rationale"), "project.rationale")
    rationale_summary = rationale.get("summary")
    if not isinstance(rationale_summary, str) or not rationale_summary.strip():
        raise PlanError("project.rationale.summary must be a non-empty string")
    uncertainties = require_list(rationale.get("uncertainties"), "project.rationale.uncertainties")
    if not all(isinstance(item, str) for item in uncertainties):
        raise PlanError("project.rationale.uncertainties entries must be strings")
    return project


def evidence_warnings(root: Path, plan: dict) -> list[str]:
    """Report string evidence that does not resolve to an existing repository file."""
    references: list[tuple[str, str]] = []
    project = plan.get("project", {})
    if isinstance(project, dict):
        references.extend(
            (f"project.evidence[{index}]", value)
            for index, value in enumerate(project.get("evidence", []))
            if isinstance(value, str)
        )
    topology = plan.get("topology", {})
    if isinstance(topology, dict):
        for kind in ("skills", "agents"):
            for index, item in enumerate(topology.get(kind, [])):
                if not isinstance(item, dict):
                    continue
                name = item.get("name", index)
                references.extend(
                    (f"topology.{kind}[{name!r}].evidence[{evidence_index}]", value)
                    for evidence_index, value in enumerate(item.get("evidence", []))
                    if isinstance(value, str)
                )

    warnings: list[str] = []
    for label, relative in references:
        try:
            path = harness_state.resolve_inside(root, relative)
        except harness_state.StateError as exc:
            warnings.append(f"{label} is not a normalized repository path: {exc}")
            continue
        if not path.is_file():
            warnings.append(f"{label} does not reference an existing file: {relative}")
    return warnings


def validate_artifacts(root: Path, plan: dict) -> dict[str, str]:
    artifact_items = require_list(plan.get("artifacts"), "artifacts")
    artifacts: dict[str, str] = {}
    for index, item in enumerate(artifact_items):
        artifact = require_object(item, f"artifacts[{index}]")
        relative = artifact.get("path")
        content = artifact.get("content")
        if not isinstance(relative, str) or not relative.startswith(ALLOWED_PREFIXES):
            raise PlanError(f"artifact path is outside Codex Harness output roots: {relative!r}")
        if not harness_transaction.is_allowed_target(relative):
            raise PlanError(f"artifact path is not a supported Codex Harness target: {relative!r}")
        if relative in artifacts:
            raise PlanError(f"duplicate artifact path: {relative}")
        if not isinstance(content, str):
            raise PlanError(f"artifact content must be text: {relative}")
        harness_state.resolve_inside(root, relative)
        if any(token in content for token in FORBIDDEN_TOKENS):
            raise PlanError(f"artifact contains an obsolete runtime token: {relative}")
        artifacts[relative] = content
    return artifacts


def validate_topology(plan: dict, artifacts: dict[str, str]) -> dict:
    topology = require_object(plan.get("topology"), "topology")
    patterns = require_list(topology.get("patterns"), "topology.patterns")
    if not all(isinstance(pattern, str) and pattern in ALLOWED_PATTERNS for pattern in patterns):
        raise PlanError("topology.patterns contains an unknown collaboration pattern")
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
        evidence = require_list(skill.get("evidence"), f"skill {name} evidence")
        if not all(isinstance(value, str) and value.strip() for value in evidence):
            raise PlanError(f"skill {name} evidence entries must be non-empty strings")
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
        evidence = require_list(agent.get("evidence"), f"agent {name} evidence")
        if not all(isinstance(value, str) and value.strip() for value in evidence):
            raise PlanError(f"agent {name} evidence entries must be non-empty strings")
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
        linked_skills = require_list(agent.get("skills", []), f"agent {name} skills")
        for linked_skill in linked_skills:
            if linked_skill not in known_skills:
                raise PlanError(f"agent {name} references unknown skill {linked_skill!r}")
            if linked_skill not in data["developer_instructions"]:
                raise PlanError(
                    f"agent {name} must mention linked skill {linked_skill!r} in developer_instructions"
                )
    return topology


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


def managed_entry(relative: str, content: str, kind: str = "file") -> dict:
    return {
        "path": relative,
        "kind": kind,
        "sha256": harness_state.digest_bytes(content.encode("utf-8")),
    }


def existing_manifest_state(root: Path) -> tuple[dict | None, dict[str, dict]]:
    _, manifest = harness_state.load_manifest(root)
    if manifest is None:
        return None, {}
    harness_state.validate_runtime(manifest)
    if manifest.get("schemaVersion") != harness_state.CURRENT_SCHEMA_VERSION:
        raise PlanError(
            f"existing manifest must be migrated to schemaVersion "
            f"{harness_state.CURRENT_SCHEMA_VERSION} before apply"
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


def classify_file(root: Path, relative: str, desired: str, managed: dict[str, dict]) -> str:
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
    return "unchanged" if current == desired else "update"


def build_application(root: Path, plan: dict) -> dict:
    harness_transaction.ensure_no_pending_transaction(root)
    project = validate_project(plan)
    artifacts = validate_artifacts(root, plan)
    topology = validate_topology(plan, artifacts)
    managed_block = validate_instruction(plan)
    warnings = evidence_warnings(root, plan)
    manifest, old_managed = existing_manifest_state(root)

    instruction_relative = harness_state.active_instruction_relative(root)
    old_instruction = manifest.get("instructionFile") if manifest else None
    if old_instruction is not None and old_instruction != instruction_relative:
        raise PlanError(
            f"active Codex instruction file changed from {old_instruction!r} to {instruction_relative!r}; "
            "resolve the instruction precedence change manually"
        )

    actions: list[dict] = []
    desired_entries: dict[str, dict] = {}
    original_hashes: dict[str, str] = {}
    for relative, content in sorted(artifacts.items()):
        action = classify_file(root, relative, content, old_managed)
        actions.append({"path": relative, "action": action})
        desired_entries[relative] = managed_entry(relative, content)
        if action != "create":
            path = harness_state.resolve_inside(root, relative, must_exist=True)
            original_hashes[relative] = harness_state.digest_bytes(path.read_bytes())

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
    merged_instruction = merge_managed_block(existing_instruction, managed_block)
    if not instruction_path.exists():
        instruction_action = "create"
    else:
        instruction_action = "unchanged" if merged_instruction == existing_instruction else "update"
    actions.append({"path": instruction_relative, "action": instruction_action, "kind": "managed-block"})
    if instruction_action != "create":
        original_hashes[instruction_relative] = harness_state.digest_bytes(
            instruction_path.read_bytes()
        )
    desired_entries[instruction_relative] = managed_entry(
        instruction_relative, managed_block, kind="managed-block"
    )

    removal_candidates = sorted(
        relative
        for relative, entry in old_managed.items()
        if relative not in desired_entries and entry.get("kind", "file") == "file"
    )
    for relative in removal_candidates:
        desired_entries[relative] = old_managed[relative]

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
        "instructionFile": instruction_relative,
        "project": project,
        "topology": topology,
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

    return {
        "artifacts": artifacts,
        "instructionRelative": instruction_relative,
        "instructionPath": instruction_path,
        "instructionText": merged_instruction,
        "manifestPath": manifest_path,
        "manifestText": manifest_text,
        "originalHashes": original_hashes,
        "managedPreconditions": list(old_managed.values()),
        "report": {
            "runtime": harness_state.RUNTIME,
            "valid": True,
            "actions": actions,
            "removalCandidates": removal_candidates,
            "warnings": warnings,
        },
    }


def application_outputs(application: dict) -> dict[str, str]:
    outputs = dict(application["artifacts"])
    outputs[application["instructionRelative"]] = application["instructionText"]
    outputs[".harness/manifest.json"] = application["manifestText"]
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
    if not isinstance(instruction_relative, str):
        raise PlanError("application is missing instructionRelative")
    expected_paths = set(application["artifacts"]) | {
        instruction_relative,
        ".harness/manifest.json",
    }
    if set(action_by_path) != expected_paths:
        raise PlanError("application action paths do not match the planned outputs")
    return action_by_path


def apply_application(application: dict) -> dict:
    action_by_path = application_actions(application)
    root = application["manifestPath"].parents[1]
    journal = harness_transaction.prepare_transaction(
        root,
        application_outputs(application),
        action_by_path,
        application["originalHashes"],
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
        parser.error(f"repository root is not a directory: {root}")
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
