#!/usr/bin/env python3
"""Produce a bounded, content-free workspace inventory for Harness."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

import harness_metadata
import harness_state


INVENTORY_IGNORED_DIRS = {
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

# Root-boundary discovery must not reuse the file-inventory exclusions above.
# Dependencies, vendor trees, and output directories can contain independent Git
# roots and therefore remain visible to this scan. Git boundaries are descriptive;
# their metadata and Harness's own installed tools/state are not project evidence.
ROOT_SCAN_EXCLUDED_DIRS = {".git", ".hg", ".svn"}

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
INSTRUCTION_SELECTION_MAX_BYTES = 1024 * 1024
TEST_MARKERS = {"test", "tests", "spec", "specs", "__tests__"}

CODE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".dart",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".jl",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".lua",
    ".php",
    ".py",
    ".r",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".sql",
    ".svelte",
    ".swift",
    ".ts",
    ".tsx",
    ".vue",
}
CONFIG_EXTENSIONS = {".cfg", ".conf", ".ini", ".json", ".toml", ".xml", ".yaml", ".yml"}
DOCUMENTATION_EXTENSIONS = {".adoc", ".md", ".mdx", ".pdf", ".rst", ".txt"}
FILE_ROLES = ("code", "config", "docs", "test", "research-artifact", "unknown")

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
    "output",
    "outputs",
    "results",
    "runs",
    "wandb",
}
ROOT_ARTIFACT_DIRS = {"data", "datasets"}


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


def _harness_exclusion_reason(root: Path, path: Path) -> str | None:
    parts = tuple(part.casefold() for part in path.relative_to(root).parts)
    if parts[-1:] == (".harness",):
        return "harness-state"
    if parts[-3:] == (".agents", "skills", "harness"):
        return "harness-generator"
    return None


def _is_link_or_reparse(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _classify_nested_repository(root: Path, relative: str, marker_type: str) -> str:
    if _git_marker_kind(root) != "none":
        try:
            completed = subprocess.run(
                ["git", "-C", str(root), "ls-files", "--stage", "--", f":(literal){relative}"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            completed = None
        if completed is not None and completed.returncode == 0:
            modes = {
                line.split(maxsplit=1)[0]
                for line in completed.stdout.splitlines()
                if line.strip()
            }
            if "160000" in modes:
                return "submodule"
    return "independent-repository" if marker_type == "directory" else "linked-repository"


def _containing_git_root(root: Path) -> Path | None:
    """Return the local Git work-tree root without inspecting remotes."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    return Path(completed.stdout.strip()).resolve()


def inspect_root_context(root: Path, *, max_directories: int = 5000) -> dict:
    """Inspect workspace boundaries independently from the bounded file budget."""
    root = root.resolve()
    nested_repositories: list[dict[str, str]] = []
    excluded_by_policy: list[dict[str, str]] = []
    scan_errors: list[str] = []
    directory_count = 0
    scan_truncated = False

    def record_error(error: OSError) -> None:
        filename = getattr(error, "filename", None)
        if filename:
            try:
                label = Path(filename).resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                label = "[outside-workspace]"
        else:
            label = "[unknown]"
        scan_errors.append(label)

    for current, dirs, files in os.walk(root, followlinks=False, onerror=record_error):
        current_path = Path(current)
        directory_count += 1
        if directory_count > max_directories:
            scan_truncated = True
            dirs[:] = []
            break
        nested_repository = current_path != root and (".git" in dirs or ".git" in files)
        if nested_repository:
            marker_type = "directory" if ".git" in dirs else "file"
            relative = posix_relative(current_path, root)
            nested_repositories.append(
                {
                    "path": relative,
                    "markerType": marker_type,
                    "kind": _classify_nested_repository(root, relative, marker_type),
                }
            )
        kept: list[str] = []
        for directory in sorted(dirs):
            path = current_path / directory
            reason = _harness_exclusion_reason(root, path)
            if directory.casefold() in ROOT_SCAN_EXCLUDED_DIRS:
                reason = "version-control-metadata"
            if reason is None:
                try:
                    if _is_link_or_reparse(path):
                        reason = "filesystem-link"
                except OSError as exc:
                    record_error(exc)
                    continue
            if reason is not None:
                excluded_by_policy.append(
                    {
                        "path": posix_relative(path, root),
                        "status": "excluded-by-policy",
                        "reason": reason,
                    }
                )
                continue
            kept.append(directory)
        dirs[:] = kept
    nested_repositories.sort(key=lambda item: item["path"])
    excluded_by_policy.sort(key=lambda item: item["path"])
    marker = _git_marker_kind(root)
    containing_root = _containing_git_root(root)
    contained_by_git = containing_root is not None and containing_root != root
    if scan_errors:
        scan_status = "unknown"
    elif scan_truncated:
        scan_status = "truncated"
    else:
        scan_status = "scanned"
    if contained_by_git:
        workspace_kind = "git-contained-directory"
    elif marker == "directory":
        workspace_kind = "git-repository"
    elif marker == "file":
        workspace_kind = "git-worktree"
    elif nested_repositories:
        workspace_kind = "directory-workspace"
    else:
        workspace_kind = "plain-directory"
    return {
        "schemaVersion": harness_metadata.ROOT_CONTEXT_SCHEMA_VERSION,
        "workspaceKind": workspace_kind,
        "rootGitState": "contained" if contained_by_git else marker,
        "containingGitRoot": str(containing_root) if contained_by_git else None,
        "directoryCount": directory_count,
        "scanTruncated": scan_truncated,
        "scanCompleteness": {
            "status": scan_status,
            "maxDirectories": max_directories,
            "scannedDirectories": min(directory_count, max_directories),
            "excludedByPolicy": excluded_by_policy,
            "unreadableDirectories": sorted(set(scan_errors)),
        },
        "nestedRepositories": nested_repositories,
        "rootSelectionRequired": not root.is_dir(),
    }


def require_workspace_root(root: Path) -> dict:
    """Keep the selected directory as the root, regardless of Git scan coverage."""
    if any(part.casefold() == ".git" for part in root.absolute().parts):
        raise ValueError("workspace root must not be inside Git metadata")
    root = root.resolve()
    if any(part.casefold() == ".git" for part in root.parts):
        raise ValueError("workspace root must not resolve inside Git metadata")
    if not root.is_dir():
        raise ValueError(f"workspace root is not a directory: {root}")
    return inspect_root_context(root)


def _file_role(path: Path, parts: tuple[str, ...]) -> str:
    filename = path.name
    suffix = path.suffix.lower()
    if any(part.lower() in TEST_MARKERS for part in parts) or filename.lower().startswith("test_"):
        return "test"
    if suffix in ARTIFACT_EXTENSIONS:
        return "research-artifact"
    if filename in MANIFEST_NAMES or filename in INSTRUCTION_NAMES or suffix in CONFIG_EXTENSIONS:
        return "config"
    if suffix in CODE_EXTENSIONS:
        return "code"
    if suffix in DOCUMENTATION_EXTENSIONS:
        return "docs"
    return "unknown"


def build_inventory(root: Path, max_files: int, *, include_artifacts: bool = False, max_directories: int = 5000) -> dict:
    if max_files < 1 or max_directories < 1:
        raise ValueError("file and directory budgets must be positive")
    root_context = require_workspace_root(root)
    root = root.resolve()
    instruction_errors: list[str] = []
    instruction_candidates = set(INSTRUCTION_NAMES)
    active_instruction = planned_instruction = None
    try:
        instruction_candidates.update(harness_state.project_instruction_candidates(root))
        planned_instruction = harness_state.active_instruction_relative(root, max_bytes=INSTRUCTION_SELECTION_MAX_BYTES)
        _, present = harness_state.resolve_lexical_regular_inside(root, planned_instruction, label="project instruction")
        active_instruction = planned_instruction if present else None
    except (OSError, UnicodeError, harness_state.StateError) as exc:
        instruction_errors.append(str(exc))
        active_instruction = planned_instruction = None
    nested_paths = {item["path"] for item in root_context["nestedRepositories"]}
    repository_counts: Counter[str] = Counter()
    repository_roles: defaultdict[str, Counter[str]] = defaultdict(Counter)
    extensions: Counter[str] = Counter()
    top_level_counts: Counter[str] = Counter()
    boundary_counts: defaultdict[str, int] = defaultdict(int)
    boundary_roles: defaultdict[str, Counter[str]] = defaultdict(Counter)
    file_roles: Counter[str] = Counter()
    manifests: list[str] = []
    instructions: list[str] = [active_instruction] if active_instruction is not None else []
    tests: list[str] = []
    ci: list[str] = []
    excluded_artifact_directories: list[str] = []
    excluded_by_policy: list[dict[str, str]] = []
    artifact_extensions: Counter[str] = Counter()
    artifact_top_level: Counter[str] = Counter()
    sensitive_skipped = 0
    file_count = 0
    non_artifact_file_count = 0
    artifact_file_count = 0
    truncated = False
    directory_count = 0
    scan_errors: list[str] = []
    directory_limit_reached = False

    def record_error(error: OSError) -> None:
        try:
            label = Path(error.filename).resolve().relative_to(root).as_posix() if error.filename else "[unknown]"
        except (OSError, ValueError):
            label = "[outside-workspace]"
        scan_errors.append(label)

    for current, dirs, files in os.walk(root, followlinks=False, onerror=record_error):
        if directory_count >= max_directories:
            directory_limit_reached = truncated = True
            break
        directory_count += 1
        current_path = Path(current)
        kept_dirs: list[str] = []
        for directory in sorted(dirs):
            path = current_path / directory
            reason = _harness_exclusion_reason(root, path)
            if reason is not None:
                excluded_by_policy.append(
                    {"path": posix_relative(path, root), "reason": reason}
                )
                continue
            if directory.casefold() in INVENTORY_IGNORED_DIRS:
                continue
            try:
                linked = _is_link_or_reparse(path)
            except OSError as exc:
                record_error(exc)
                continue
            if linked:
                excluded_by_policy.append(
                    {"path": posix_relative(path, root), "reason": "filesystem-link"}
                )
                continue
            if not include_artifacts and _is_artifact_directory(root, current_path, directory):
                excluded_artifact_directories.append(
                    posix_relative(current_path / directory, root)
                )
                continue
            kept_dirs.append(directory)
        dirs[:] = kept_dirs

        for filename in sorted(files):
            if filename.casefold() == ".git":
                continue
            if file_count >= max_files:
                truncated = True
                break
            if filename in SENSITIVE_NAMES or filename.startswith(".env."):
                sensitive_skipped += 1
                continue

            path = current_path / filename
            try:
                linked = _is_link_or_reparse(path)
            except OSError as exc:
                record_error(exc)
                continue
            if linked:
                continue
            rel = posix_relative(path, root)
            parts = Path(rel).parts
            file_count += 1

            suffix = path.suffix.lower() or "[no-extension]"
            role = "config" if current_path == root and filename in instruction_candidates else _file_role(path, parts)
            file_roles[role] += 1
            is_artifact = role == "research-artifact"
            if is_artifact:
                artifact_file_count += 1
                artifact_extensions[suffix] += 1
                artifact_top_level[parts[0]] += 1
            else:
                non_artifact_file_count += 1
            extensions[suffix] += 1
            top_level_counts[parts[0]] += 1
            if len(parts) > 1 and not is_artifact:
                boundary_counts[parts[0]] += 1
                boundary_roles[parts[0]][role] += 1
                for depth in range(1, len(parts)):
                    ancestor = "/".join(parts[:depth])
                    if ancestor in nested_paths:
                        repository_counts[ancestor] += 1
                        repository_roles[ancestor][role] += 1

            if filename in MANIFEST_NAMES:
                manifests.append(rel)
            if filename in INSTRUCTION_NAMES or (current_path == root and filename in instruction_candidates):
                instructions.append(rel)
            if any(part.lower() in TEST_MARKERS for part in parts) or filename.lower().startswith("test_"):
                tests.append(rel)
            if any(
                pair == (".github", "workflows") for pair in zip(parts, parts[1:])
            ) or filename in {".gitlab-ci.yml", "azure-pipelines.yml"}:
                ci.append(rel)

        if truncated:
            break

    candidate_boundaries = [
        {
            "path": name,
            "fileCount": count,
            "fileRoles": {
                role: boundary_roles[name].get(role, 0)
                for role in FILE_ROLES
                if role != "research-artifact"
            },
            "analysisPriority": (
                "primary"
                if boundary_roles[name]["code"] or boundary_roles[name]["test"]
                else "review"
            ),
        }
        for name, count in sorted(boundary_counts.items(), key=lambda item: (-item[1], item[0]))
        if not name.startswith(".")
    ]
    if root_context["nestedRepositories"]:
        known_candidates = {item["path"]: item for item in candidate_boundaries}
        for nested in root_context["nestedRepositories"]:
            if nested["path"] in known_candidates:
                known_candidates[nested["path"]]["boundaryKind"] = nested["kind"]
                continue
            candidate_boundaries.append(
                {
                    "path": nested["path"],
                    "fileCount": repository_counts[nested["path"]],
                    "fileRoles": {
                        role: repository_roles[nested["path"]].get(role, 0)
                        for role in FILE_ROLES if role != "research-artifact"
                    },
                    "analysisPriority": "repository-boundary",
                    "boundaryKind": nested["kind"],
                }
            )
        candidate_boundaries.sort(key=lambda item: item["path"])

    return {
        "schemaVersion": harness_metadata.INVENTORY_SCHEMA_VERSION,
        "root": str(root),
        "rootContext": root_context,
        "workspaceKind": root_context["workspaceKind"],
        "rootGitState": root_context["rootGitState"],
        "nestedRepositories": root_context["nestedRepositories"],
        "rootSelectionRequired": root_context["rootSelectionRequired"],
        "fileCount": file_count,
        "nonArtifactFileCount": non_artifact_file_count,
        "artifactFileCount": artifact_file_count,
        "fileRoleSummary": {role: file_roles.get(role, 0) for role in FILE_ROLES},
        "truncated": truncated,
        "fileScanCompleteness": {
            "status": "unknown" if scan_errors else "truncated" if truncated else "scanned",
            "scannedDirectories": directory_count,
            "maxDirectories": max_directories,
            "directoryLimitReached": directory_limit_reached,
            "unreadablePaths": sorted(set(scan_errors)),
        },
        "sensitiveFilesSkipped": sensitive_skipped,
        "excludedByPolicy": sorted(excluded_by_policy, key=lambda item: item["path"]),
        "extensions": dict(sorted(extensions.items(), key=lambda item: (-item[1], item[0]))),
        "topLevel": dict(sorted(top_level_counts.items())),
        "manifests": sorted(manifests),
        "instructions": sorted(set(instructions)),
        "existingActiveRootInstruction": active_instruction,
        "plannedRootInstruction": planned_instruction,
        "instructionSelectionErrors": instruction_errors,
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
    parser.add_argument("--max-directories", type=int, default=5000)
    parser.add_argument(
        "--include-artifacts",
        action="store_true",
        help="include known research-output directories in the bounded scan",
    )
    args = parser.parse_args()

    if args.max_files < 1:
        parser.error("--max-files must be positive")
    if args.max_directories < 1:
        parser.error("--max-directories must be positive")

    root = Path(args.root)
    if not root.is_dir():
        parser.error(f"workspace root is not a directory: {root}")

    try:
        report = build_inventory(root, args.max_files, include_artifacts=args.include_artifacts, max_directories=args.max_directories)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
