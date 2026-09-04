#!/usr/bin/env python3
"""Enforce Harness local-only workspace and local Git exclusion contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterable

import harness_state


LOCAL_SCOPE = "local-only"
BEGIN_MARKER = "# harness:local-only:begin"
END_MARKER = "# harness:local-only:end"
GIT_WORKSPACE_KINDS = {"git-repository", "git-worktree"}
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
    result = _run_git(root, ["ls-files", "--cached", "--", *literal_paths])
    if result.returncode != 0:
        raise WorkspaceError("local Git could not classify tracked Harness targets")
    return sorted(line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip())


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


def require_exclusive_info_exclude(root: Path) -> None:
    worktrees = registered_worktrees(root)
    if len(worktrees) != 1:
        raise WorkspaceError(
            "local Git info/exclude is shared across registered worktrees; "
            f"found {len(worktrees)} worktrees, so local-only protection is refused; "
            "remove or prune unused worktrees before retrying"
        )


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


def validate_directory_workspace_writers(root_context: object, topology: object) -> None:
    """Keep an outer directory workspace from writing across independent Git histories."""
    if not isinstance(root_context, dict) or root_context.get("workspaceKind") != "directory-workspace":
        return
    if not isinstance(topology, dict):
        return
    nested_value = root_context.get("nestedRepositories", [])
    nested_paths = [
        item["path"]
        for item in nested_value
        if isinstance(item, dict)
        and item.get("kind") in {"independent-repository", "linked-repository"}
        and isinstance(item.get("path"), str)
    ] if isinstance(nested_value, list) else []
    for agent in topology.get("agents", []):
        if not isinstance(agent, dict):
            continue
        for access in agent.get("fileAccess", []):
            if not isinstance(access, dict) or access.get("mode") != "write":
                continue
            scope = access.get("scope")
            if not isinstance(scope, str):
                continue
            base = scope[:-3] if scope.endswith("/**") else scope
            crossed = [
                nested
                for nested in nested_paths
                if scope == nested
                or scope.startswith(f"{nested}/")
                or (scope.endswith("/**") and (not base or nested == base or nested.startswith(f"{base}/")))
            ]
            if crossed:
                raise WorkspaceError(
                    f"agent {agent.get('name')!r} write scope {scope!r} crosses independent "
                    f"directory-workspace Git boundaries: {', '.join(crossed)}; "
                    "select one repository root for code-changing work"
                )


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
        }
    require_exclusive_info_exclude(root)
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


def rollback_local_protection(root: Path, protection: dict) -> dict:
    """Compensate a synchronous failed apply without overwriting external edits."""
    if protection.get("mode") == "not-applicable" or protection.get("action") == "unchanged":
        return {"mode": protection.get("mode"), "action": "unchanged"}
    if protection.get("mode") != "git-info-exclude":
        raise WorkspaceError("unsupported local-only protection rollback mode")
    require_exclusive_info_exclude(root)
    path = protection.get("path")
    desired = protection.get("desiredText")
    original = protection.get("originalText")
    original_exists = protection.get("originalExists")
    original_mode = protection.get("originalMode")
    if (
        not isinstance(path, Path)
        or not isinstance(desired, str)
        or not isinstance(original, str)
        or not isinstance(original_exists, bool)
        or (original_exists and not isinstance(original_mode, int))
    ):
        raise WorkspaceError("local-only protection rollback plan is incomplete")
    if path.resolve() != _exclude_file(root):
        raise WorkspaceError("local-only protection path changed before rollback")
    if not path.is_file() or _read_text_exact(path) != desired:
        raise WorkspaceError(
            "local Git info/exclude changed after Harness wrote it; automatic rollback refused"
        )
    if original_exists:
        harness_state.atomic_write_text(path, original, mode=original_mode)
        return {"mode": "git-info-exclude", "action": "restored"}
    path.unlink()
    harness_state.sync_directory(path.parent)
    return {"mode": "git-info-exclude", "action": "removed-created-file"}


def inspect_local_protection(root: Path, workspace_kind: str) -> dict:
    if workspace_kind not in GIT_WORKSPACE_KINDS:
        return {"state": "not-applicable", "worktreeCount": 0, "patternCount": 0}
    worktrees = registered_worktrees(root)
    path = _exclude_file(root)
    if not path.is_file():
        return {"state": "absent", "worktreeCount": len(worktrees), "patternCount": 0}
    text = _read_text_exact(path)
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count == 0 and end_count == 0:
        return {"state": "absent", "worktreeCount": len(worktrees), "patternCount": 0}
    if begin_count != 1 or end_count != 1:
        return {"state": "malformed", "worktreeCount": len(worktrees), "patternCount": 0}
    start = text.index(BEGIN_MARKER) + len(BEGIN_MARKER)
    try:
        end = text.index(END_MARKER, start)
    except ValueError:
        return {"state": "malformed", "worktreeCount": len(worktrees), "patternCount": 0}
    patterns = [line for line in text[start:end].splitlines() if line]
    return {
        "state": "shared-ambiguous" if len(worktrees) != 1 else "present-unbound",
        "worktreeCount": len(worktrees),
        "patternCount": len(patterns),
    }


def validate_manifest_protection(root: Path, workspace: object, managed_paths: Iterable[str]) -> None:
    if not isinstance(workspace, dict) or set(workspace) != {
        "scope",
        "kind",
        "instructionMode",
        "gitProtection",
    }:
        raise WorkspaceError("manifest workspace contract is incomplete")
    if workspace.get("scope") != LOCAL_SCOPE:
        raise WorkspaceError("manifest workspace scope must be local-only")
    protection = workspace.get("gitProtection")
    if not isinstance(protection, dict) or set(protection) != {"mode", "patterns"}:
        raise WorkspaceError("manifest gitProtection contract is incomplete")
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
