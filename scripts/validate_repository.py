#!/usr/bin/env python3
"""Validate the Harness repository's publishable plugin and skill assets.

This deliberately avoids strict Markdown style linting. The repository has a
large amount of existing long-form/localized Markdown, so this gate focuses on
trust checks that are stable and non-invasive for incoming PRs:

- required plugin/skill files are present
- all JSON files parse and plugin manifests contain expected metadata
- YAML files and Claude/Codex skill frontmatter parse as YAML
- the Claude and Codex Harness skills have required frontmatter and valid reference paths
- tracked text files contain no unresolved merge conflict markers
- relative Markdown links/images resolve to existing local files
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

try:
    import yaml
except ImportError:  # Reported as a repository validation error in main().
    yaml = None

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FILES = [
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/requirements-validation.txt",
    ".agents/skills/harness/SKILL.md",
    "AGENTS.md",
    "skills/harness/SKILL.md",
]

REQUIRED_PLUGIN_FIELDS = [
    "name",
    "description",
    "version",
    "author",
    "homepage",
    "repository",
    "license",
]
REFERENCE_RE = re.compile(r"`(references/[^`\n]+)`")
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
TEXT_SUFFIXES = {".json", ".md", ".py", ".toml", ".yaml", ".yml"}
CONFLICT_MARKERS = (("<" * 7) + " ", "=" * 7, (">" * 7) + " ")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def load_json(path: Path, errors: list[str]) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(errors, f"{rel(path)} is invalid JSON: {exc}")
    except OSError as exc:
        fail(errors, f"{rel(path)} cannot be read: {exc}")
    return {}


def load_yaml(path: Path, errors: list[str]) -> Any:
    if yaml is None:
        fail(errors, "PyYAML is required; install .github/requirements-validation.txt")
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        fail(errors, f"{rel(path)} is invalid YAML: {exc}")
    except OSError as exc:
        fail(errors, f"{rel(path)} cannot be read: {exc}")
    return None


def validate_required_files(errors: list[str]) -> None:
    for name in REQUIRED_FILES:
        path = ROOT / name
        if not path.is_file():
            fail(errors, f"missing required file: {name}")


def validate_plugin_manifests(errors: list[str]) -> None:
    plugin_path = ROOT / ".claude-plugin" / "plugin.json"
    marketplace_path = ROOT / ".claude-plugin" / "marketplace.json"
    if not plugin_path.is_file() or not marketplace_path.is_file():
        return

    plugin = load_json(plugin_path, errors)
    marketplace = load_json(marketplace_path, errors)
    if not plugin or not marketplace:
        return

    for field in REQUIRED_PLUGIN_FIELDS:
        if not plugin.get(field):
            fail(errors, f"plugin.json missing required field: {field}")

    if plugin.get("name") != "harness":
        fail(errors, "plugin.json name must be 'harness'")

    plugins = marketplace.get("plugins")
    owner = marketplace.get("owner")
    if not isinstance(owner, dict) or not owner.get("name"):
        fail(errors, "marketplace.json owner must contain a name")

    if not isinstance(plugins, list) or not plugins:
        fail(errors, "marketplace.json must contain at least one plugin entry")
        return

    harness_entries = [entry for entry in plugins if entry.get("name") == "harness"]
    if not harness_entries:
        fail(errors, "marketplace.json missing plugin entry named 'harness'")
        return

    entry = harness_entries[0]
    if entry.get("version") != plugin.get("version"):
        fail(errors, "marketplace harness version must match plugin.json version")
    if entry.get("source") != "./":
        fail(errors, "marketplace harness source must be './'")


def validate_skill_file(skill_path: Path, errors: list[str]) -> None:
    if not skill_path.is_file():
        return

    text = skill_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        fail(errors, f"{rel(skill_path)} missing YAML frontmatter")
    else:
        frontmatter_end = text.find("\n---", 4)
        if frontmatter_end == -1:
            fail(errors, f"{rel(skill_path)} frontmatter is not closed")
        else:
            frontmatter = text[4:frontmatter_end]
            if yaml is None:
                fail(errors, "PyYAML is required; install .github/requirements-validation.txt")
            else:
                try:
                    metadata = yaml.safe_load(frontmatter)
                except yaml.YAMLError as exc:
                    fail(errors, f"{rel(skill_path)} has invalid YAML frontmatter: {exc}")
                    metadata = None
                if not isinstance(metadata, dict):
                    fail(errors, f"{rel(skill_path)} frontmatter must be a mapping")
                else:
                    for field in ("name", "description"):
                        if not isinstance(metadata.get(field), str) or not metadata[field].strip():
                            fail(errors, f"{rel(skill_path)} frontmatter missing string field: {field}")

    for ref in REFERENCE_RE.findall(text):
        target = skill_path.parent / ref
        if not target.is_file():
            fail(errors, f"{rel(skill_path)} has broken reference: {ref}")


def validate_skills(errors: list[str]) -> None:
    validate_skill_file(ROOT / "skills" / "harness" / "SKILL.md", errors)
    validate_skill_file(ROOT / ".agents" / "skills" / "harness" / "SKILL.md", errors)


def validate_all_json(errors: list[str]) -> None:
    for path in sorted(ROOT.rglob("*.json")):
        if any(part in {".git", "node_modules"} for part in path.parts):
            continue
        load_json(path, errors)


def validate_all_yaml(errors: list[str]) -> None:
    if yaml is None:
        fail(errors, "PyYAML is required; install .github/requirements-validation.txt")
        return
    for pattern in ("*.yml", "*.yaml"):
        for path in sorted(ROOT.rglob(pattern)):
            if any(part in {".git", "node_modules"} for part in path.parts):
                continue
            document = load_yaml(path, errors)
            if document is not None and not isinstance(document, dict):
                fail(errors, f"{rel(path)} YAML root must be a mapping")


def validate_conflict_markers(errors: list[str]) -> None:
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in {".git", "node_modules"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if any(line.startswith(marker) for marker in CONFLICT_MARKERS):
                fail(errors, f"merge conflict marker: {rel(path)}:{line_no}")


def should_skip_link(raw_url: str) -> bool:
    raw_url = raw_url.strip()
    if not raw_url or raw_url == "#" or raw_url.startswith("#"):
        return True
    parsed = urlparse(raw_url)
    return bool(parsed.scheme or parsed.netloc)


def validate_markdown_links(errors: list[str]) -> None:
    for md in ROOT.rglob("*.md"):
        if any(part in {".git", "node_modules"} for part in md.parts):
            continue
        text = md.read_text(encoding="utf-8")
        for raw_url in MARKDOWN_LINK_RE.findall(text):
            if should_skip_link(raw_url):
                continue
            clean = raw_url.split("#", 1)[0]
            clean = clean.split("?", 1)[0]
            clean = unquote(clean).strip()
            if not clean:
                continue
            target = (md.parent / clean).resolve()
            try:
                target.relative_to(ROOT.resolve())
            except ValueError:
                continue
            if not target.exists():
                fail(errors, f"{rel(md)} links to missing local path: {raw_url}")


def main() -> int:
    errors: list[str] = []
    validate_required_files(errors)
    validate_all_json(errors)
    validate_all_yaml(errors)
    validate_plugin_manifests(errors)
    validate_skills(errors)
    validate_conflict_markers(errors)
    validate_markdown_links(errors)

    if errors:
        print("Repository validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Repository validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
