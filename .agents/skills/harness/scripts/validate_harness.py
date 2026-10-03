#!/usr/bin/env python3
"""Validate a generated Codex project harness."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable

import harness_state
import harness_transaction
import harness_teamplay
import harness_topology
import harness_workspace
import inventory
import harness_metadata
import harness_frontmatter
import harness_agent_contract
import harness_change_discipline

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ is expected
    tomllib = None


SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
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


def read_frontmatter(path: Path) -> dict[str, str]:
    return harness_frontmatter.parse(path.read_text(encoding="utf-8"))


class Validator:
    def __init__(self, root: Path):
        self.root = root
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.manifest: dict = {}
        self.validation_layers: dict[str, dict[str, str]] = {}
        self.legacy_artifacts = False
        self.upgrade_requirements: list[str] = []
        self.compatibility_state = "failed"

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def run_layer(self, name: str, purpose: str, check: Callable[[], object]) -> None:
        before = len(self.errors)
        check()
        self.validation_layers[name] = {
            "status": "passed" if len(self.errors) == before else "failed",
            "proves": purpose,
        }

    def mark_blocked(self, name: str, purpose: str) -> None:
        self.validation_layers[name] = {
            "status": "blocked",
            "proves": purpose,
        }

    def path(self, relative: str, *, must_exist: bool = True) -> Path | None:
        try:
            return harness_state.resolve_inside(self.root, relative, must_exist=must_exist)
        except harness_state.StateError as exc:
            self.error(str(exc))
            return None

    def load_manifest(self) -> None:
        try:
            _, manifest = harness_state.load_manifest(self.root)
            if manifest is None:
                self.error("missing .harness/manifest.json")
                return
            harness_state.validate_runtime(manifest)
            self.manifest = manifest
        except harness_state.StateError as exc:
            self.error(str(exc))

    def validate_manifest_shape(self) -> None:
        if not self.manifest:
            return
        if self.manifest.get("schemaVersion") not in (harness_metadata.PREVIOUS_MANIFEST_SCHEMA_VERSION, harness_state.CURRENT_SCHEMA_VERSION):
            self.error(f"schemaVersion must be {harness_state.CURRENT_SCHEMA_VERSION}")
        if "taskExecution" in self.manifest or "taskExecutionClass" in self.manifest:
            self.error("runtime task execution state must not be stored in the project manifest")
        pending: list[tuple[str, object]] = [("manifest", self.manifest)]
        while pending:
            label, value = pending.pop()
            if isinstance(value, dict):
                forbidden = FORBIDDEN_PERSISTENT_KEYS.intersection(value)
                if forbidden:
                    self.error(
                        f"{label} contains runtime-only fields: {', '.join(sorted(forbidden))}"
                    )
                pending.extend((f"{label}.{key}", item) for key, item in value.items())
            elif isinstance(value, list):
                pending.extend((f"{label}[{index}]", item) for index, item in enumerate(value))
        generator = self.manifest.get("generator")
        if not isinstance(generator, dict) or not all(generator.get(key) for key in ("name", "version", "runtime")):
            self.error("generator must contain name, version, and runtime")
        try:
            contract_state = harness_metadata.artifact_contract_state(self.manifest)
            self.compatibility_state = "passed" if contract_state == "current" else "upgrade-required"
            self.legacy_artifacts = contract_state == "legacy"
            if contract_state != "current":
                self.upgrade_requirements.append("Review an Authoring Contract 3 draft and apply Artifact Contract 2 and the project-local workspace contract through the guarded update workflow.")
        except ValueError as exc:
            self.error(str(exc))
        application = self.manifest.get("application")
        if not isinstance(application, dict):
            self.error("application must be an object")
        elif application.get("mode") != "journaled":
            self.error("application.mode must be journaled")
        elif application.get("transactionSchemaVersion") != harness_state.TRANSACTION_SCHEMA_VERSION:
            self.error(
                f"application.transactionSchemaVersion must be "
                f"{harness_state.TRANSACTION_SCHEMA_VERSION}"
            )
        workspace = self.manifest.get("workspace")
        if not isinstance(workspace, dict):
            self.error("workspace must be an object")
        else:
            if workspace.get("scope") not in (harness_workspace.LOCAL_SCOPE, harness_workspace.LEGACY_LOCAL_SCOPE):
                self.error("workspace.scope is unsupported")
            if workspace.get("instructionMode") not in ("managed-pointer", "explicit-skill"):
                self.error("workspace.instructionMode is invalid")
        project = self.manifest.get("project")
        if not isinstance(project, dict) or not isinstance(project.get("summary"), str) or not project.get("summary", "").strip():
            self.error("project.summary must be a non-empty string")
        elif not isinstance(project.get("evidence"), list) or not project["evidence"]:
            self.error("project.evidence must be a non-empty array")
        elif not isinstance(project.get("rationale"), dict):
            self.error("project.rationale must be an object")
        else:
            rationale = project["rationale"]
            if not isinstance(rationale.get("summary"), str) or not rationale["summary"].strip():
                self.error("project.rationale.summary must be a non-empty string")
            if not isinstance(rationale.get("uncertainties"), list):
                self.error("project.rationale.uncertainties must be an array")
        instruction_file = self.manifest.get("instructionFile")
        instruction_mode = workspace.get("instructionMode") if isinstance(workspace, dict) else None
        if instruction_mode == "managed-pointer":
            try:
                if not harness_state.is_instruction_relative(self.root, instruction_file):
                    self.error("managed-pointer mode requires a configured root instruction")
            except (OSError, harness_state.StateError) as exc:
                self.error(str(exc))
        elif instruction_mode == "explicit-skill" and instruction_file is not None:
            self.error("explicit-skill mode requires a null instructionFile")
        topology = self.manifest.get("topology")
        if not isinstance(topology, dict):
            self.error("topology must be an object")
            return
        for key in (
            "boundaries",
            "collaborationPatterns",
            "qualityPatternPolicies",
            "agents",
            "skills",
            "routingPolicies",
            "executionPhases",
            "handoffs",
        ):
            if not isinstance(topology.get(key), list):
                self.error(f"topology.{key} must be an array")
        if not isinstance(topology.get("classification"), dict):
            self.error("topology.classification must be an object")
        if not isinstance(self.manifest.get("capabilityPolicies"), list):
            self.error("capabilityPolicies must be an array")
        if not isinstance(self.manifest.get("managedFiles"), list):
            self.error("managedFiles must be an array")

    def validate_evidence_locations(self) -> None:
        snapshot = harness_state.EvidenceSnapshot()
        references: list[tuple[str, object]] = []
        project = self.manifest.get("project", {})
        project_evidence = project.get("evidence", []) if isinstance(project, dict) else []
        if isinstance(project_evidence, list):
            references.extend(
                (f"project.evidence[{index}]", value)
                for index, value in enumerate(project_evidence)
            )
        topology = self.manifest.get("topology", {})
        if isinstance(topology, dict):
            for label, evidence in harness_topology.iter_evidence(topology):
                if isinstance(evidence, list):
                    references.extend(
                        (f"{label}[{evidence_index}]", value)
                        for evidence_index, value in enumerate(evidence)
                    )
        for label, relative in references:
            if not isinstance(relative, dict):
                self.error(f"{label} must be an object")
                continue
            evidence_path = relative.get("path")
            claim = relative.get("claim")
            expected_hash = relative.get("sha256")
            if not isinstance(evidence_path, str):
                self.error(f"{label}.path must be text")
                continue
            try:
                harness_state.validate_evidence_relative(evidence_path)
                path, present = harness_state.resolve_lexical_regular_inside(
                    self.root,
                    evidence_path,
                    must_exist=True,
                    label="evidence",
                )
            except harness_state.StateError as exc:
                self.error(f"invalid {label}.path: {exc}")
                continue
            if not isinstance(claim, str) or not claim.strip():
                self.error(f"{label}.claim must be non-empty text")
            if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                self.error(f"{label}.sha256 must be a SHA-256 hash")
            if not present:
                self.error(f"{label}.path does not exist: {evidence_path}")
                continue
            if isinstance(expected_hash, str) and re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                try:
                    content, actual_hash = snapshot.read(path)
                    if "contentScope" in relative:
                        content = harness_state.evidence_content(self.root, relative, content)
                        actual_hash = harness_state.digest_bytes(content)
                except (OSError, harness_state.StateError) as exc:
                    self.error(f"could not read {label}.path: {exc}")
                    continue
                if actual_hash != expected_hash:
                    self.error(f"{label}.path changed after generation: {evidence_path}")
            lines = relative.get("lines")
            if lines is not None:
                if not isinstance(lines, dict):
                    self.error(f"{label}.lines must be an object")
                    continue
                start = lines.get("start")
                end = lines.get("end")
                if (
                    not isinstance(start, int)
                    or isinstance(start, bool)
                    or not isinstance(end, int)
                    or isinstance(end, bool)
                    or start < 1
                    or end < start
                ):
                    self.error(f"{label}.lines must satisfy 1 <= start <= end")
                    continue
                try:
                    if "contentScope" in relative:
                        content, _ = snapshot.read(path)
                        content = harness_state.evidence_content(self.root, relative, content)
                        line_count = len(content.decode("utf-8").splitlines())
                    else:
                        line_count = snapshot.line_count(path)
                except (OSError, UnicodeError, harness_state.StateError):
                    self.error(f"{label}.lines requires a UTF-8 file: {evidence_path}")
                    continue
                if end > line_count:
                    self.error(f"{label}.lines exceeds {evidence_path}")
        try:
            snapshot.verify()
        except OSError as exc:
            self.error(str(exc))

    def validate_skill(self, item: dict) -> str | None:
        name = item.get("name")
        relative = item.get("path")
        if not isinstance(name, str) or not SKILL_NAME_RE.fullmatch(name):
            self.error(f"invalid skill name: {name!r}")
            return None
        if not isinstance(item.get("purpose"), str) or not item["purpose"].strip():
            self.error(f"skill {name} purpose must be a non-empty string")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(
            isinstance(value, dict) for value in evidence
        ):
            self.error(f"skill {name} evidence must be a non-empty array of objects")
        if not isinstance(relative, str):
            self.error(f"skill {name} has no path")
            return name
        expected = f".agents/skills/{name}/SKILL.md"
        if relative != expected:
            self.error(f"skill {name} path must be {expected}")
        path = self.path(relative)
        if path is None:
            return name
        try:
            frontmatter = read_frontmatter(path)
        except (OSError, UnicodeError, ValueError) as exc:
            self.error(f"invalid skill {relative}: {exc}")
            return name
        if frontmatter.get("name") != name:
            self.error(f"skill name mismatch in {relative}")
        if not frontmatter.get("description"):
            self.error(f"skill description is missing in {relative}")
        return name

    def validate_codex_agent(self, name: str, path: Path, relative: str) -> dict | None:
        if tomllib is None:
            self.error("Python 3.11+ is required to validate Codex agent TOML")
            return None
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            self.error(f"invalid Codex agent {relative}: {exc}")
            return None
        for key in ("name", "description", "developer_instructions"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                self.error(f"Codex agent {relative} is missing {key}")
        if data.get("name") != name:
            self.error(f"agent name mismatch in {relative}")
        instructions = data.get("developer_instructions")
        if isinstance(instructions, str):
            try:
                harness_teamplay.require_exactly_once(
                    instructions, harness_teamplay.AGENT_BLOCK, f"agent {name}"
                )
            except ValueError as exc:
                self.error(str(exc))
        return data

    def validate_agent(self, item: dict, known_skills: set[str]) -> None:
        name = item.get("name")
        relative = item.get("path")
        if not isinstance(name, str) or not AGENT_NAME_RE.fullmatch(name):
            self.error(f"invalid agent name: {name!r}")
            return
        for field in ("responsibility", "whyDelegate"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                self.error(f"agent {name} {field} must be a non-empty string")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(
            isinstance(value, dict) for value in evidence
        ):
            self.error(f"agent {name} evidence must be a non-empty array of objects")
        if not isinstance(relative, str):
            self.error(f"agent {name} has no path")
            return
        expected = f".codex/agents/{name}.toml"
        if relative != expected:
            self.error(f"agent {name} path must be {expected}")
        path = self.path(relative)
        data = self.validate_codex_agent(name, path, relative) if path is not None else None
        if data is not None and isinstance(data.get("developer_instructions"), str):
            try:
                harness_agent_contract.validate(data["developer_instructions"], item, self.manifest["topology"], allow_missing=self.legacy_artifacts)
                if any(isinstance(access, dict) and access.get("mode") == "write" for access in item.get("fileAccess", [])):
                    harness_change_discipline.require_exactly_once(data["developer_instructions"], harness_change_discipline.WRITER_BLOCK, f"writer agent {name}")
            except (ValueError, KeyError, TypeError) as exc:
                self.error(f"agent contract {name}: {exc}")
        skills = item.get("skills", [])
        if not isinstance(skills, list):
            self.error(f"agent {name} skills must be an array")
        else:
            for skill in skills:
                if skill not in known_skills:
                    self.error(f"agent {name} references unknown skill {skill!r}")
                elif data is not None and skill not in data.get("developer_instructions", ""):
                    self.error(
                        f"agent {name} must mention linked skill {skill!r} in developer_instructions"
                    )

    def validate_topology(self) -> None:
        topology = self.manifest.get("topology", {})
        if not isinstance(topology, dict):
            return
        try:
            warnings = harness_topology.validate_contract(
                topology, self.manifest.get("capabilityPolicies")
            )
            harness_topology.validate_scope_paths(self.root, topology)
            for warning in warnings:
                self.warning(warning)
        except harness_topology.TopologyError as exc:
            self.error(str(exc))
        skill_value = topology.get("skills", [])
        agent_value = topology.get("agents", [])
        skill_items = skill_value if isinstance(skill_value, list) else []
        agent_items = agent_value if isinstance(agent_value, list) else []
        known_skills: set[str] = set()
        for item in skill_items:
            if not isinstance(item, dict):
                self.error("topology.skills entries must be objects")
                continue
            name = self.validate_skill(item)
            if name:
                if name in known_skills:
                    self.error(f"duplicate skill name: {name}")
                known_skills.add(name)
        if "project-harness" not in known_skills:
            self.error("topology must include the project-harness skill")
        else:
            project_path = self.path(".agents/skills/project-harness/SKILL.md")
            if project_path is not None:
                try:
                    project_content = project_path.read_text(encoding="utf-8")
                    harness_change_discipline.require_exactly_once(project_content, harness_change_discipline.PROJECT_BLOCK, "project-harness skill")
                    harness_teamplay.require_exactly_once(
                        project_content,
                        harness_teamplay.PROJECT_BLOCK,
                        "project-harness skill",
                    )
                except (OSError, UnicodeError, ValueError) as exc:
                    self.error(str(exc))

        known_agents: set[str] = set()
        for item in agent_items:
            if not isinstance(item, dict):
                self.error("topology.agents entries must be objects")
                continue
            name = item.get("name")
            if name in known_agents:
                self.error(f"duplicate agent name: {name}")
            elif isinstance(name, str):
                known_agents.add(name)
            self.validate_agent(item, known_skills)

    def validate_managed_files(self) -> None:
        entries = self.manifest.get("managedFiles", [])
        entry_items = entries if isinstance(entries, list) else []
        managed_path_values = [
            entry.get("path")
            for entry in entry_items if isinstance(entry, dict)
            if isinstance(entry.get("path"), str)
        ]
        try:
            harness_state.validate_file_namespace(
                managed_path_values, label="manifest managedFiles"
            )
        except harness_state.StateError as exc:
            self.error(str(exc))
        managed_paths: set[str] = set()
        for entry in entry_items:
            if not isinstance(entry, dict):
                self.error("managedFiles entries must be objects")
                continue
            relative = entry.get("path")
            if not harness_transaction.is_allowed_target(relative, root=self.root):
                self.error(f"managed path is outside project artifact ownership: {relative!r}")
            if harness_state.is_instruction_relative(self.root, relative) and entry.get("kind") != "managed-block":
                self.error(f"root instruction must retain managed-block ownership: {relative}")
            if relative in managed_paths:
                self.error(f"duplicate managed path: {relative}")
            elif isinstance(relative, str):
                managed_paths.add(relative)
            if entry.get("kind", "file") == "file":
                try:
                    harness_state.parse_mode(entry.get("mode"), f"managed mode for {relative}")
                except harness_state.StateError as exc:
                    self.error(str(exc))
            result = harness_state.entry_status(self.root, entry)
            if result.get("state") != "unchanged":
                self.error(f"managed file {relative!r} is {result.get('state')}")

        topology_value = self.manifest.get("topology", {})
        topology = topology_value if isinstance(topology_value, dict) else {}
        topology_paths = {
            item.get("path")
            for key in ("agents", "skills")
            for item in (topology.get(key, []) if isinstance(topology.get(key, []), list) else [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        for relative in sorted(topology_paths - managed_paths):
            self.error(f"topology path is not recorded as managed: {relative}")
        self.pending_retirement = sorted(harness_state.native_entrypoints(managed_paths) - topology_paths)
        for relative in self.pending_retirement:
            self.warning(f"pending-retirement: retained native entry point is no longer in topology; review explicit removal: {relative}")
            try:
                path = harness_state.resolve_inside(self.root, relative, must_exist=True)
                if relative.endswith(".toml"):
                    data = tomllib.loads(path.read_text(encoding="utf-8"))
                    if not all(isinstance(data.get(key), str) and data[key].strip() for key in ("name", "description", "developer_instructions")):
                        raise ValueError(f"invalid retained native agent: {relative}")
                else:
                    harness_frontmatter.parse(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError) as exc:
                self.error(str(exc))
        contents = {}
        dedicated_paths = {item.get("path") for item in entry_items if isinstance(item, dict) and item.get("kind", "file") == "file"}
        for relative in sorted((managed_paths & dedicated_paths) - set(self.pending_retirement)):
            if relative.endswith(".md"):
                try:
                    contents[relative] = harness_state.resolve_inside(self.root, relative, must_exist=True).read_text(encoding="utf-8")
                except (OSError, UnicodeError, ValueError) as exc:
                    self.error(str(exc))
        for error in harness_state.missing_markdown_references(self.root, contents):
            self.error(error)

    def validate_root_pointer(self) -> None:
        workspace = self.manifest.get("workspace")
        instruction_mode = workspace.get("instructionMode") if isinstance(workspace, dict) else None
        filename = self.manifest.get("instructionFile")
        try:
            active = harness_state.active_instruction_relative(self.root)
        except harness_state.StateError as exc:
            self.error(f"could not discover project instructions: {exc}")
            return
        if instruction_mode == "explicit-skill":
            if filename is not None:
                self.error("explicit-skill mode cannot declare an instructionFile")
            entries = self.manifest.get("managedFiles", [])
            pointers = (
                [
                    entry
                    for entry in entries
                    if isinstance(entry, dict) and entry.get("kind") == "managed-block"
                ]
                if isinstance(entries, list)
                else []
            )
            if pointers:
                self.error("explicit-skill mode cannot retain a managed instruction block")
            return
        if not isinstance(filename, str):
            return
        if filename != active:
            self.error(f"instructionFile {filename!r} is inactive; Codex will prefer {active!r}")
        path = self.root / filename
        if not path.exists():
            self.error(f"missing root instruction file: {filename}")
            return
        try:
            harness_state.extract_managed_block(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, harness_state.StateError) as exc:
            self.error(f"invalid managed block in {filename}: {exc}")
        entries = self.manifest.get("managedFiles", [])
        matching = (
            [entry for entry in entries if isinstance(entry, dict) and entry.get("path") == filename]
            if isinstance(entries, list)
            else []
        )
        if len(matching) != 1 or matching[0].get("kind") != "managed-block":
            self.error(f"{filename} must be recorded once as managed-block")

    def validate_forbidden_tokens(self) -> None:
        entries = self.manifest.get("managedFiles", [])
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            if entry.get("kind", "file") != "file":
                continue
            relative = entry.get("path")
            if not isinstance(relative, str):
                continue
            path = self.path(relative)
            if path is None:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for token in FORBIDDEN_TOKENS:
                if token in text:
                    self.error(f"obsolete runtime token {token!r} found in {relative}")

    def validate_workspace(self) -> None:
        context = inventory.require_workspace_root(self.root)
        workspace = self.manifest.get("workspace")
        if not isinstance(workspace, dict):
            return
        if workspace.get("scope") == harness_workspace.LEGACY_LOCAL_SCOPE and workspace.get("kind") != context.get("workspaceKind"):
            self.error(
                f"workspace kind changed from {workspace.get('kind')!r} "
                f"to {context.get('workspaceKind')!r}; re-analyze before updating"
            )
            return
        entries = self.manifest.get("managedFiles", [])
        paths = (
            [
                entry.get("path")
                for entry in entries
                if isinstance(entry, dict) and isinstance(entry.get("path"), str)
            ]
            if isinstance(entries, list)
            else []
        )
        harness_workspace.validate_manifest_protection(self.root, workspace, paths)

    def run(self) -> dict:
        def validate_transaction_state() -> None:
            transaction = harness_state.transaction_status(self.root)
            if transaction is not None:
                self.error(
                    f"pending Harness transaction must be recovered before validation: "
                    f"{transaction.get('state')}"
                )

        self.run_layer(
            "transactionSafety",
            "No interrupted Harness transaction is pending.",
            validate_transaction_state,
        )

        def validate_root_context() -> None:
            try:
                inventory.require_workspace_root(self.root)
            except ValueError as exc:
                self.error(str(exc))

        self.run_layer(
            "rootContext",
            "The selected project folder exists; Git boundaries are observational.",
            validate_root_context,
        )
        self.run_layer(
            "manifestContract",
            "The installed manifest has the supported schema and persistent-state shape.",
            lambda: (self.load_manifest(), self.validate_manifest_shape()),
        )
        if self.manifest:
            def validate_local_only() -> None:
                try:
                    self.validate_workspace()
                except (ValueError, harness_workspace.WorkspaceError) as exc:
                    self.error(str(exc))

            self.run_layer(
                "workspaceOwnership",
                "Workspace ownership matches its versioned contract; current generation does not manage Git metadata.",
                validate_local_only,
            )
            self.run_layer(
                "evidenceFreshness",
                "All declared evidence paths, hashes, and optional line ranges still match.",
                self.validate_evidence_locations,
            )
            self.run_layer(
                "topologyAndArtifacts",
                "Topology references and generated skill/agent contracts are structurally valid.",
                self.validate_topology,
            )
            self.run_layer(
                "managedOwnership",
                "Managed files, hashes, modes, namespace, and the active root pointer match.",
                lambda: (self.validate_managed_files(), self.validate_root_pointer()),
            )
            self.run_layer(
                "runtimeStateSeparation",
                "Managed files contain no prohibited persistent runtime state or obsolete primitives.",
                self.validate_forbidden_tokens,
            )
        else:
            self.mark_blocked("workspaceOwnership", "The manifest identifies project-local ownership.")
            self.mark_blocked(
                "evidenceFreshness",
                "All declared evidence paths, hashes, and optional line ranges still match.",
            )
            self.mark_blocked(
                "topologyAndArtifacts",
                "Topology references and generated skill/agent contracts are structurally valid.",
            )
            self.mark_blocked(
                "managedOwnership",
                "Managed files, hashes, modes, namespace, and the active root pointer match.",
            )
            self.mark_blocked(
                "runtimeStateSeparation",
                "Managed files contain no prohibited persistent runtime state or obsolete primitives.",
            )
        external_capabilities = {
            "customAgentDiscovery": {
                "status": "not-tested",
                "requires": "a fresh Codex session or live discovery smoke test",
            },
            "liveDelegation": {
                "status": "not-tested",
                "requires": "an opt-in live runtime observation",
            },
            "taskCorrectness": {
                "status": "not-measured",
                "requires": "project-native verification for a concrete task",
            },
            "harnessBenefitAttribution": {
                "status": "not-measured",
                "requires": "eligible isolated paired evaluation runs",
            },
        }
        installation_status = "invalid" if self.errors else "upgrade-required" if self.upgrade_requirements else "valid"
        self.validation_layers["artifactCompatibility"] = {
            "status": self.compatibility_state,
            "proves": "Current artifact-contract compatibility is separate from installation integrity.",
        }
        activation = activation_report(self.manifest, valid=installation_status == "valid")
        if installation_status == "upgrade-required":
            activation["status"] = "upgrade-required"
            activation["nextStep"] = self.upgrade_requirements[0]
        return {
            "runtime": harness_state.RUNTIME,
            "valid": installation_status == "valid",
            "installationStatus": installation_status,
            "integrityValid": not self.errors,
            "managedIntegrityValid": all(self.validation_layers.get(name, {}).get("status") == "passed" for name in (
                "transactionSafety", "rootContext", "workspaceOwnership", "managedOwnership",
            )),
            "artifactContractVersion": self.manifest.get("artifactContractVersion"),
            "requiredArtifactContractVersion": harness_metadata.ARTIFACT_CONTRACT_VERSION,
            "upgradeRequirements": self.upgrade_requirements,
            "activation": activation,
            "validationLayers": self.validation_layers,
            "summary": validation_summary(self.validation_layers),
            "externalCapabilities": external_capabilities,
            "errors": self.errors,
            "warnings": self.warnings,
            "pendingRetirement": getattr(self, "pending_retirement", []),
        }


def validation_summary(layers: dict) -> dict:
    """Describe separate evidence dimensions without changing validation gates."""
    managed = layers.get("managedOwnership", {}).get("status", "not-tested")
    evidence = layers.get("evidenceFreshness", {}).get("status", "not-tested")
    if managed == "failed":
        message = "Managed-file ownership or content checks failed. Preserve the files and review the detailed errors before updating."
    elif managed == "passed" and evidence == "failed":
        message = "Managed files match their recorded ownership; source evidence needs review. Other validation layers still determine whether work can proceed."
    elif managed == "passed" and evidence == "passed":
        message = "Managed files and source evidence match. This does not establish runtime loading or task quality."
    else:
        message = "Managed-file or source-evidence checks are incomplete. Resolve the detailed findings before relying on the installation."
    return {"managedArtifacts": managed, "sourceEvidence": evidence,
            "runtimeLoading": "not-tested", "taskQuality": "not-measured", "message": message}


def activation_report(manifest: dict, *, valid: bool) -> dict:
    """Describe the validated activation contract without claiming runtime loading."""
    if not valid:
        return {
            "status": "blocked",
            "mode": "unknown",
            "instructionFile": None,
            "invocation": None,
            "runtimeLoaded": "not-tested",
            "nextStep": "Resolve structural validation errors before testing activation.",
        }
    mode = manifest["workspace"]["instructionMode"]
    return {
        "status": "configured",
        "mode": mode,
        "instructionFile": manifest.get("instructionFile"),
        "invocation": "$project-harness",
        "runtimeLoaded": "not-tested",
        "nextStep": (
            "In a fresh task, confirm the active managed root instruction selects $project-harness."
            if mode == "managed-pointer"
            else "Invoke $project-harness explicitly in the target workspace; no managed root pointer is required."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f"workspace root is not a directory: {root}")
    report = Validator(root).run()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["valid"] else 2 if report["installationStatus"] == "upgrade-required" else 1


if __name__ == "__main__":
    sys.exit(main())
