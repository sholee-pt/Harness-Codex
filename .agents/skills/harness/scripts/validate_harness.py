#!/usr/bin/env python3
"""Validate a generated Codex project harness."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import harness_state
import harness_topology

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


def read_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing opening YAML frontmatter delimiter")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("missing closing YAML frontmatter delimiter") from exc
    values: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"unsupported frontmatter line: {line}")
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class Validator:
    def __init__(self, root: Path):
        self.root = root
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.manifest: dict = {}

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)

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
        if self.manifest.get("schemaVersion") != harness_state.CURRENT_SCHEMA_VERSION:
            self.error(f"schemaVersion must be {harness_state.CURRENT_SCHEMA_VERSION}")
        if "taskExecution" in self.manifest or "taskExecutionClass" in self.manifest:
            self.error("runtime task execution state must not be stored in the project manifest")
        generator = self.manifest.get("generator")
        if not isinstance(generator, dict) or not all(generator.get(key) for key in ("name", "version", "runtime")):
            self.error("generator must contain name, version, and runtime")
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
        if instruction_file not in {"AGENTS.md", "AGENTS.override.md"}:
            self.error("instructionFile must be AGENTS.md or AGENTS.override.md")
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
            if not isinstance(claim, str) or not claim.strip():
                self.error(f"{label}.claim must be non-empty text")
            if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                self.error(f"{label}.sha256 must be a SHA-256 hash")
                continue
            try:
                path = harness_state.resolve_inside(self.root, evidence_path)
            except harness_state.StateError as exc:
                self.error(f"{label}.path is invalid: {exc}")
                continue
            if not path.is_file():
                self.error(f"{label}.path does not exist: {evidence_path}")
                continue
            actual_hash = harness_state.digest_bytes(path.read_bytes())
            if actual_hash != expected_hash:
                self.error(f"{label} changed after harness generation: {evidence_path}")
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
                    line_count = len(path.read_text(encoding="utf-8").splitlines())
                except (OSError, UnicodeError):
                    self.error(f"{label}.lines requires a UTF-8 file: {evidence_path}")
                    continue
                if end > line_count:
                    self.error(f"{label}.lines exceeds {evidence_path}")

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

    def validate_root_pointer(self) -> None:
        filename = self.manifest.get("instructionFile")
        if not isinstance(filename, str):
            return
        active = harness_state.active_instruction_relative(self.root)
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

    def run(self) -> dict:
        transaction = harness_state.transaction_status(self.root)
        if transaction is not None:
            self.error(
                f"pending Harness transaction must be recovered before validation: "
                f"{transaction.get('state')}"
            )
        self.load_manifest()
        self.validate_manifest_shape()
        if self.manifest:
            self.validate_evidence_locations()
            self.validate_topology()
            self.validate_managed_files()
            self.validate_root_pointer()
            self.validate_forbidden_tokens()
        return {
            "runtime": harness_state.RUNTIME,
            "valid": not self.errors,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f"repository root is not a directory: {root}")
    report = Validator(root).run()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
