#!/usr/bin/env python3
"""Project-local ownership plus legacy/isolated-evaluation Git exclusion helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterable

import harness_state


LOCAL_SCOPE = "project-local"
LEGACY_LOCAL_SCOPE = "local-only"
BEGIN_MARKER = "# harness:local-only:begin"
END_MARKER = "# harness:local-only:end"
GIT_WORKSPACE_KINDS = {"git-repository", "git-worktree"}
WORKSPACE_KINDS = GIT_WORKSPACE_KINDS | {"plain-directory", "directory-workspace", "git-contained-directory"}
GITIGNORE_LITERAL_ESCAPES = frozenset("*?[]#! ")


class WorkspaceError(ValueError):
    pass


def _run_git(root: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a bounded local Git query. Remote-oriented commands are never accepted."""
    if not arguments or arguments[0] in {"fetch", "pull", "push", "remote", "ls-remote"}:
        raise WorkspaceError("remote Git operations are prohibited by local-only mode")
    try:
        return subprocess.run(
            ["git", "-C", str(root.resolve()), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkspaceError(f"local Git inspection failed: {exc}") from exc


def _require_git_root(root: Path) -> tuple[Path, Path]:
    top = _run_git(root, ["rev-parse", "--show-toplevel"])
    git_dir = _run_git(root, ["rev-parse", "--absolute-git-dir"])
    if top.returncode != 0 or git_dir.returncode != 0:
        raise WorkspaceError("the selected Git workspace is not readable by local Git")
    top_path = Path(top.stdout.strip()).resolve()
    if top_path != root.resolve():
        raise WorkspaceError("the selected workspace is not the local Git work-tree root")
    return top_path, Path(git_dir.stdout.strip()).resolve()


def tracked_paths(root: Path, relatives: Iterable[str]) -> list[str]:
    values = sorted(set(relatives))
    if not values:
        return []
    _require_git_root(root)
    literal_paths = [f":(literal){value}" for value in values]
    result = _run_git(root, ["ls-files", "--cached", "-z", "--", *literal_paths])
    if result.returncode != 0:
        raise WorkspaceError("local Git could not classify tracked Harness targets")
    return sorted(value.replace("\\", "/") for value in result.stdout.split("\0") if value)


def _exclude_file(root: Path) -> Path:
    _top, git_dir = _require_git_root(root)
    result = _run_git(root, ["rev-parse", "--git-path", "info/exclude"])
    if result.returncode != 0 or not result.stdout.strip():
        raise WorkspaceError("local Git did not expose an info/exclude path")
    raw = Path(result.stdout.strip())
    path = raw.resolve() if raw.is_absolute() else (root.resolve() / raw).resolve()
    common = _run_git(root, ["rev-parse", "--git-common-dir"])
    common_raw = Path(common.stdout.strip()) if common.returncode == 0 and common.stdout.strip() else git_dir
    common_dir = common_raw.resolve() if common_raw.is_absolute() else (root.resolve() / common_raw).resolve()
    if path != git_dir / "info" / "exclude" and path != common_dir / "info" / "exclude":
        raise WorkspaceError("local Git info/exclude resolved outside the selected Git metadata")
    return path


def registered_worktrees(root: Path) -> list[str]:
    """Return every locally registered worktree without consulting a remote."""
    _require_git_root(root)
    result = _run_git(root, ["worktree", "list", "--porcelain", "-z"])
    if result.returncode != 0:
        raise WorkspaceError("local Git could not enumerate registered worktrees")
    worktrees = [
        field.removeprefix("worktree ")
        for field in result.stdout.split("\0")
        if field.startswith("worktree ") and field.removeprefix("worktree ")
    ]
    if not worktrees:
        raise WorkspaceError("local Git reported no registered worktree for the selected root")
    return worktrees


def require_exclusive_info_exclude(root: Path) -> int:
    worktrees = registered_worktrees(root)
    if len(worktrees) != 1:
        raise WorkspaceError(
            "local Git info/exclude is shared across registered worktrees; "
            f"found {len(worktrees)} worktrees, so local-only protection is refused; "
            "remove or prune unused worktrees before retrying"
        )
    return len(worktrees)


def _read_text_exact(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceError("local Git info/exclude must be valid UTF-8") from exc


def _normalize_pattern(relative: str) -> str:
    if relative == ".harness/":
        return "/.harness/"
    try:
        key = harness_state.portable_path_key(relative)
    except harness_state.StateError as exc:
        raise WorkspaceError(str(exc)) from exc
    if not key:
        raise WorkspaceError("local exclusion path cannot be empty")
    portable = PurePosixPath(relative).as_posix()
    escaped = "".join(
        f"\\{character}" if character in GITIGNORE_LITERAL_ESCAPES else character
        for character in portable
    )
    return f"/{escaped}"


def local_patterns(relatives: Iterable[str]) -> list[str]:
    return sorted({_normalize_pattern(value) for value in [*relatives, ".harness/"]})


def _managed_block(patterns: list[str]) -> str:
    return "\n".join([BEGIN_MARKER, *patterns, END_MARKER])


def _merge_block(existing: str, patterns: list[str]) -> str:
    begin_count = existing.count(BEGIN_MARKER)
    end_count = existing.count(END_MARKER)
    block = _managed_block(patterns)
    if begin_count == 0 and end_count == 0:
        separator = "" if not existing else ("" if existing.endswith("\n") else "\n")
        return f"{existing}{separator}{block}\n"
    if begin_count != 1 or end_count != 1:
        raise WorkspaceError("local Git exclude contains incomplete or duplicate Harness markers")
    start = existing.index(BEGIN_MARKER)
    end = existing.index(END_MARKER, start) + len(END_MARKER)
    return f"{existing[:start]}{block}{existing[end:]}"


def plan_local_protection(root: Path, workspace_kind: str, relatives: Iterable[str]) -> dict:
    managed_relatives = tuple(relatives)
    patterns = local_patterns(managed_relatives)
    if workspace_kind not in GIT_WORKSPACE_KINDS:
        return {
            "mode": "not-applicable",
            "patterns": [],
            "action": "unchanged",
            "path": None,
            "originalSha256": None,
            "originalExists": False,
            "originalMode": None,
            "originalText": None,
            "desiredText": None,
            "worktreeCount": 0,
        }
    worktree_count = require_exclusive_info_exclude(root)
    tracked = tracked_paths(root, [*managed_relatives, ".harness"])
    if tracked:
        raise WorkspaceError(
            "local-only mode refuses already tracked Harness targets: " + ", ".join(tracked)
        )
    path = _exclude_file(root)
    if path.exists() and not path.is_file():
        raise WorkspaceError("local Git info/exclude is not a regular file")
    existed = path.is_file()
    existing = _read_text_exact(path) if existed else ""
    desired = _merge_block(existing, patterns)
    return {
        "mode": "git-info-exclude",
        "patterns": patterns,
        "action": "unchanged" if desired == existing else ("update" if path.exists() else "create"),
        "path": path,
        "originalSha256": harness_state.digest_bytes(existing.encode("utf-8")) if existed else None,
        "originalExists": existed,
        "originalMode": harness_state.current_mode(path) if existed else None,
        "originalText": existing,
        "desiredText": desired,
        "worktreeCount": worktree_count,
    }


def apply_local_protection(root: Path, protection: dict, relatives: Iterable[str]) -> dict:
    if protection.get("mode") == "not-applicable":
        return {"mode": "not-applicable", "action": "unchanged"}
    if protection.get("mode") != "git-info-exclude":
        raise WorkspaceError("unsupported local-only protection mode")
    require_exclusive_info_exclude(root)
    tracked = tracked_paths(root, [*relatives, ".harness"])
    if tracked:
        raise WorkspaceError(
            "Harness targets became tracked before apply: " + ", ".join(tracked)
        )
    path = protection.get("path")
    desired = protection.get("desiredText")
    if not isinstance(path, Path) or not isinstance(desired, str):
        raise WorkspaceError("local-only protection plan is incomplete")
    if path.resolve() != _exclude_file(root):
        raise WorkspaceError("local-only protection path changed after dry-run")
    exists = path.is_file()
    existing = _read_text_exact(path) if exists else ""
    actual_hash = harness_state.digest_bytes(existing.encode("utf-8")) if exists else None
    if actual_hash != protection.get("originalSha256"):
        raise WorkspaceError("local Git info/exclude changed after dry-run")
    if existing == desired:
        return {"mode": "git-info-exclude", "action": "unchanged"}
    harness_state.atomic_write_text(
        path,
        desired,
        mode=harness_state.current_mode(path) if exists else harness_state.DEFAULT_FILE_MODE,
    )
    return {"mode": "git-info-exclude", "action": protection.get("action")}


def validate_manifest_protection(root: Path, workspace: object, managed_paths: Iterable[str]) -> None:
    if not isinstance(workspace, dict) or set(workspace) != {
        "scope",
        "kind",
        "instructionMode",
        "gitProtection",
    }:
        raise WorkspaceError("manifest workspace contract is incomplete")
    if workspace.get("scope") not in (LOCAL_SCOPE, LEGACY_LOCAL_SCOPE):
        raise WorkspaceError("manifest workspace scope is unsupported")
    if not isinstance(workspace.get("kind"), str) or workspace["kind"] not in WORKSPACE_KINDS:
        raise WorkspaceError("manifest workspace kind is unsupported")
    protection = workspace.get("gitProtection")
    if not isinstance(protection, dict) or set(protection) != {"mode", "patterns"}:
        raise WorkspaceError("manifest gitProtection contract is incomplete")
    if workspace.get("scope") == LOCAL_SCOPE:
        if protection != {"mode": "not-managed", "patterns": []}:
            raise WorkspaceError("project-local workspaces must use not-managed Git protection")
        return
    managed_relatives = tuple(managed_paths)
    expected_patterns = local_patterns(managed_relatives)
    if workspace.get("kind") in GIT_WORKSPACE_KINDS:
        require_exclusive_info_exclude(root)
        if protection.get("mode") != "git-info-exclude" or protection.get("patterns") != expected_patterns:
            raise WorkspaceError("manifest Git exclusion patterns do not match managed paths")
        if tracked_paths(root, [*managed_relatives, ".harness"]):
            raise WorkspaceError("one or more managed Harness files are tracked by Git")
        path = _exclude_file(root)
        if not path.is_file():
            raise WorkspaceError("local Git info/exclude is missing")
        text = _read_text_exact(path)
        if _merge_block(text, expected_patterns) != text:
            raise WorkspaceError("local Git info/exclude does not contain the manifest patterns")
    elif protection != {"mode": "not-applicable", "patterns": []}:
        raise WorkspaceError("non-Git workspaces must use not-applicable Git protection")
