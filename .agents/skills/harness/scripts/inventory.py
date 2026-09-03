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
    "environment.yml",
    "environment.yaml",
    "conda-lock.yml",
    "conda-lock.yaml",
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

INSTRUCTION_NAMES = {"AGENTS.md", "AGENTS.override.md"}
TEST_MARKERS = {"test", "tests", "spec", "specs", "__tests__"}

ARTIFACT_EXTENSIONS = {
    ".bin",
    ".ckpt",
    ".feather",
    ".h5",
    ".h5ad",
    ".hdf5",
    ".npy",
    ".npz",
    ".onnx",
    ".parquet",
    ".pickle",
    ".pkl",
    ".pt",
    ".pth",
    ".safetensors",
}
HARD_ARTIFACT_DIRS = {
    "artifacts",
    "cache",
    "caches",
    "checkpoints",
    "logs",
    "outputs",
    "runs",
    "wandb",
}
ROOT_ARTIFACT_DIRS = {"data", "datasets", "output"}


def posix_relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _git_marker_kind(path: Path) -> str:
    marker = path / ".git"
    if marker.is_dir():
        return "directory"
    if marker.is_file():
        return "file"
    return "none"


def _is_artifact_directory(root: Path, current: Path, name: str) -> bool:
    lowered = name.lower()
    return lowered in HARD_ARTIFACT_DIRS or (current == root and lowered in ROOT_ARTIFACT_DIRS)


def build_inventory(root: Path, max_files: int, *, include_artifacts: bool = False) -> dict:
    root = root.resolve()
    extensions: Counter[str] = Counter()
    top_level_counts: Counter[str] = Counter()
    boundary_counts: defaultdict[str, int] = defaultdict(int)
    manifests: list[str] = []
    instructions: list[str] = []
    tests: list[str] = []
    ci: list[str] = []
    nested_repositories: list[dict[str, str]] = []
    excluded_artifact_directories: list[str] = []
    artifact_extensions: Counter[str] = Counter()
    artifact_top_level: Counter[str] = Counter()
    sensitive_skipped = 0
    file_count = 0
    source_file_count = 0
    artifact_file_count = 0
    truncated = False

    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        nested_repository = current_path != root and (".git" in dirs or ".git" in files)
        if nested_repository:
            nested_repositories.append(
                {
                    "path": posix_relative(current_path, root),
                    "markerType": "directory" if ".git" in dirs else "file",
                }
            )
            dirs[:] = []
            continue

        kept_dirs: list[str] = []
        for directory in sorted(dirs):
            if directory in IGNORED_DIRS:
                continue
            if not include_artifacts and _is_artifact_directory(root, current_path, directory):
                excluded_artifact_directories.append(
                    posix_relative(current_path / directory, root)
                )
                continue
            kept_dirs.append(directory)
        dirs[:] = kept_dirs

        for filename in sorted(files):
            if filename == ".git":
                continue
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
            is_artifact = suffix in ARTIFACT_EXTENSIONS
            if is_artifact:
                artifact_file_count += 1
                artifact_extensions[suffix] += 1
                artifact_top_level[parts[0]] += 1
            else:
                source_file_count += 1
            extensions[suffix] += 1
            top_level_counts[parts[0]] += 1
            if len(parts) > 1 and not is_artifact:
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
        "schemaVersion": 2,
        "root": str(root),
        "rootGitState": _git_marker_kind(root),
        "nestedRepositories": sorted(nested_repositories, key=lambda item: item["path"]),
        "rootSelectionRequired": bool(nested_repositories),
        "fileCount": file_count,
        "sourceFileCount": source_file_count,
        "artifactFileCount": artifact_file_count,
        "truncated": truncated,
        "sensitiveFilesSkipped": sensitive_skipped,
        "extensions": dict(sorted(extensions.items(), key=lambda item: (-item[1], item[0]))),
        "topLevel": dict(sorted(top_level_counts.items())),
        "manifests": sorted(manifests),
        "instructions": sorted(instructions),
        "activeRootInstruction": (
            "AGENTS.override.md" if "AGENTS.override.md" in instructions else "AGENTS.md"
        ),
        "tests": sorted(tests)[:100],
        "ci": sorted(ci),
        "artifactSummary": {
            "included": include_artifacts,
            "excludedDirectories": sorted(set(excluded_artifact_directories)),
            "extensions": dict(
                sorted(artifact_extensions.items(), key=lambda item: (-item[1], item[0]))
            ),
            "topLevel": dict(sorted(artifact_top_level.items())),
        },
        "candidateBoundaries": candidate_boundaries[:50],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--max-files", type=int, default=5000)
    parser.add_argument(
        "--include-artifacts",
        action="store_true",
        help="include known research-output directories in the bounded scan",
    )
    args = parser.parse_args()

    if args.max_files < 1:
        parser.error("--max-files must be positive")

    root = Path(args.root)
    if not root.is_dir():
        parser.error(f"repository root is not a directory: {root}")

    print(
        json.dumps(
            build_inventory(root, args.max_files, include_artifacts=args.include_artifacts),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
