#!/usr/bin/env python3
"""Validate a generated Codex or Claude project harness."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import harness_state

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ is expected
    tomllib = None


NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
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
    def __init__(self, root: Path, runtime: str):
        self.root = root
        self.runtime = runtime
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
            harness_state.validate_runtime(manifest, self.runtime)
            self.manifest = manifest
        except harness_state.StateError as exc:
            self.error(str(exc))

    def validate_manifest_shape(self) -> None:
        if not self.manifest:
            return
        if self.manifest.get("schemaVersion") != 1:
            self.error("schemaVersion must be 1")
        generator = self.manifest.get("generator")
        if not isinstance(generator, dict) or not all(generator.get(key) for key in ("name", "version", "runtime")):
            self.error("generator must contain name, version, and runtime")
        project = self.manifest.get("project")
        if not isinstance(project, dict) or not isinstance(project.get("summary"), str) or not project.get("summary", "").strip():
            self.error("project.summary must be a non-empty string")
        topology = self.manifest.get("topology")
        if not isinstance(topology, dict):
            self.error("topology must be an object")
            return
        for key in ("patterns", "agents", "skills"):
            if not isinstance(topology.get(key), list):
                self.error(f"topology.{key} must be an array")
        if not isinstance(self.manifest.get("managedFiles"), list):
            self.error("managedFiles must be an array")

    def validate_skill(self, item: dict) -> str | None:
        name = item.get("name")
        relative = item.get("path")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            self.error(f"invalid skill name: {name!r}")
            return None
        if not isinstance(relative, str):
            self.error(f"skill {name} has no path")
            return name
        prefix = ".agents/skills/" if self.runtime == "codex" else ".claude/skills/"
        expected = f"{prefix}{name}/SKILL.md"
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

    def validate_codex_agent(self, name: str, path: Path, relative: str) -> None:
        if tomllib is None:
            self.error("Python 3.11+ is required to validate Codex agent TOML")
            return
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            self.error(f"invalid Codex agent {relative}: {exc}")
            return
        for key in ("name", "description", "developer_instructions"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                self.error(f"Codex agent {relative} is missing {key}")
        if data.get("name") != name:
            self.error(f"agent name mismatch in {relative}")

    def validate_claude_agent(self, name: str, path: Path, relative: str) -> None:
        try:
            frontmatter = read_frontmatter(path)
        except (OSError, UnicodeError, ValueError) as exc:
            self.error(f"invalid Claude agent {relative}: {exc}")
            return
        if frontmatter.get("name") != name:
            self.error(f"agent name mismatch in {relative}")
        if not frontmatter.get("description"):
            self.error(f"Claude agent description is missing in {relative}")

    def validate_agent(self, item: dict, known_skills: set[str]) -> None:
        name = item.get("name")
        relative = item.get("path")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            self.error(f"invalid agent name: {name!r}")
            return
        if not isinstance(relative, str):
            self.error(f"agent {name} has no path")
            return
        expected = f".codex/agents/{name}.toml" if self.runtime == "codex" else f".claude/agents/{name}.md"
        if relative != expected:
            self.error(f"agent {name} path must be {expected}")
        path = self.path(relative)
        if path is not None:
            if self.runtime == "codex":
                self.validate_codex_agent(name, path, relative)
            else:
                self.validate_claude_agent(name, path, relative)
        skills = item.get("skills", [])
        if not isinstance(skills, list):
            self.error(f"agent {name} skills must be an array")
        else:
            for skill in skills:
                if skill not in known_skills:
                    self.error(f"agent {name} references unknown skill {skill!r}")

    def validate_topology(self) -> None:
        topology = self.manifest.get("topology", {})
        skill_items = topology.get("skills", []) if isinstance(topology, dict) else []
        agent_items = topology.get("agents", []) if isinstance(topology, dict) else []
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
        managed_paths: set[str] = set()
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                self.error("managedFiles entries must be objects")
                continue
            relative = entry.get("path")
            if relative in managed_paths:
                self.error(f"duplicate managed path: {relative}")
            elif isinstance(relative, str):
                managed_paths.add(relative)
            result = harness_state.entry_status(self.root, entry)
            if result.get("state") != "unchanged":
                self.error(f"managed file {relative!r} is {result.get('state')}")

        topology = self.manifest.get("topology", {})
        topology_paths = {
            item.get("path")
            for key in ("agents", "skills")
            for item in topology.get(key, [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        for relative in sorted(topology_paths - managed_paths):
            self.error(f"topology path is not recorded as managed: {relative}")

    def validate_root_pointer(self) -> None:
        filename = "AGENTS.md" if self.runtime == "codex" else "CLAUDE.md"
        path = self.root / filename
        if not path.exists():
            self.error(f"missing root instruction file: {filename}")
            return
        try:
            harness_state.extract_managed_block(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, harness_state.StateError) as exc:
            self.error(f"invalid managed block in {filename}: {exc}")
        matching = [entry for entry in self.manifest.get("managedFiles", []) if entry.get("path") == filename]
        if len(matching) != 1 or matching[0].get("kind") != "managed-block":
            self.error(f"{filename} must be recorded once as managed-block")

    def validate_forbidden_tokens(self) -> None:
        for entry in self.manifest.get("managedFiles", []):
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
        self.load_manifest()
        self.validate_manifest_shape()
        if self.manifest:
            self.validate_topology()
            self.validate_managed_files()
            self.validate_root_pointer()
            self.validate_forbidden_tokens()
        return {
            "runtime": self.runtime,
            "valid": not self.errors,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--runtime", choices=sorted(harness_state.SUPPORTED_RUNTIMES), required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f"repository root is not a directory: {root}")
    report = Validator(root, args.runtime).run()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
