#!/usr/bin/env python3
"""Produce a bounded, content-free repository inventory for Harness."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    "target",
    "__pycache__",
}

SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}

MANIFEST_NAMES = {
    "package.json",
    "pnpm-workspace.yaml",
    "pyproject.toml",
    "requirements.txt",
    "poetry.lock",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Gemfile",
    "composer.json",
    "Package.swift",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Makefile",
}

INSTRUCTION_NAMES = {"AGENTS.md", "CLAUDE.md"}
TEST_MARKERS = {"test", "tests", "spec", "specs", "__tests__"}


def posix_relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def build_inventory(root: Path, max_files: int) -> dict:
    root = root.resolve()
    extensions: Counter[str] = Counter()
    top_level_counts: Counter[str] = Counter()
    boundary_counts: defaultdict[str, int] = defaultdict(int)
    manifests: list[str] = []
    instructions: list[str] = []
    tests: list[str] = []
    ci: list[str] = []
    sensitive_skipped = 0
    file_count = 0
    truncated = False

    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        current_path = Path(current)

        for filename in sorted(files):
            if file_count >= max_files:
                truncated = True
                break
            if filename in SENSITIVE_NAMES or filename.startswith(".env."):
                sensitive_skipped += 1
                continue

            path = current_path / filename
            if path.is_symlink():
                continue
            rel = posix_relative(path, root)
            parts = Path(rel).parts
            file_count += 1

            suffix = path.suffix.lower() or "[no-extension]"
            extensions[suffix] += 1
            top_level_counts[parts[0]] += 1
            if len(parts) > 1:
                boundary_counts[parts[0]] += 1

            if filename in MANIFEST_NAMES:
                manifests.append(rel)
            if filename in INSTRUCTION_NAMES:
                instructions.append(rel)
            if any(part.lower() in TEST_MARKERS for part in parts) or filename.lower().startswith("test_"):
                tests.append(rel)
            if rel.startswith(".github/workflows/") or filename in {".gitlab-ci.yml", "azure-pipelines.yml"}:
                ci.append(rel)

        if truncated:
            break

    candidate_boundaries = [
        {"path": name, "fileCount": count}
        for name, count in sorted(boundary_counts.items(), key=lambda item: (-item[1], item[0]))
        if not name.startswith(".")
    ]

    return {
        "schemaVersion": 1,
        "root": str(root),
        "fileCount": file_count,
        "truncated": truncated,
        "sensitiveFilesSkipped": sensitive_skipped,
        "extensions": dict(sorted(extensions.items(), key=lambda item: (-item[1], item[0]))),
        "topLevel": dict(sorted(top_level_counts.items())),
        "manifests": sorted(manifests),
        "instructions": sorted(instructions),
        "tests": sorted(tests)[:100],
        "ci": sorted(ci),
        "candidateBoundaries": candidate_boundaries[:50],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--max-files", type=int, default=5000)
    args = parser.parse_args()

    if args.max_files < 1:
        parser.error("--max-files must be positive")

    root = Path(args.root)
    if not root.is_dir():
        parser.error(f"repository root is not a directory: {root}")

    print(json.dumps(build_inventory(root, args.max_files), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
