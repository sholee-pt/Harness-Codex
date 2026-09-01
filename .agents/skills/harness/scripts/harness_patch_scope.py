#!/usr/bin/env python3
"""Bounded Git-visible patch-scope evaluation for Harness Schema 2."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import harness_eval_types as types
import harness_topology


class PatchScopeError(types.EvaluationError):
    pass


def validate_profile(value: Any) -> dict[str, Any]:
    profile = types._require_object(value, "patch scope profile")
    fields = {
        "schemaVersion", "id", "allowedScopes", "allowUntracked",
        "maximumChangedPaths", "maximumAddedLines", "maximumDeletedLines",
    }
    types._require_keys(profile, fields, fields, "patch scope profile")
    if profile["schemaVersion"] != 1 or not isinstance(profile["id"], str) or not profile["id"]:
        raise PatchScopeError("patch scope profile schemaVersion/id is invalid")
    scopes = profile["allowedScopes"]
    if not isinstance(scopes, list) or not scopes or any(not isinstance(scope, str) or not scope for scope in scopes):
        raise PatchScopeError("patch scope allowedScopes must be a non-empty string array")
    for scope in scopes:
        if "\\" in scope or scope.startswith("/") or ".." in Path(scope).parts:
            raise PatchScopeError("patch scope paths must be normalized repository-relative paths")
    if not isinstance(profile["allowUntracked"], bool):
        raise PatchScopeError("patch scope allowUntracked must be boolean")
    for key in ("maximumChangedPaths", "maximumAddedLines", "maximumDeletedLines"):
        item = profile[key]
        if item is not None and (isinstance(item, bool) or not isinstance(item, int) or item < 0):
            raise PatchScopeError(f"patch scope {key} must be null or a non-negative integer")
    return profile


def _git_bytes(root: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(root.resolve()), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PatchScopeError("patch scope requires a readable Git worktree") from exc


def _tracked_paths(root: Path) -> list[bytes]:
    """Return every affected path, counting both sides of a rename or copy."""
    tokens = [
        item
        for item in _git_bytes(root, "diff", "HEAD", "--name-status", "-z").split(b"\0")
        if item
    ]
    paths: list[bytes] = []
    index = 0
    while index < len(tokens):
        status = tokens[index]
        index += 1
        path_count = 2 if status[:1] in {b"R", b"C"} else 1
        if index + path_count > len(tokens):
            raise PatchScopeError("Git returned an incomplete name-status record")
        paths.extend(tokens[index:index + path_count])
        index += path_count
    return paths


def evaluate(
    *,
    root: Path,
    profile: dict[str, Any],
    repository_id: str,
    store: Any,
) -> dict[str, Any]:
    validate_profile(profile)
    tracked_raw = _tracked_paths(root)
    untracked_raw = [item for item in _git_bytes(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if item]
    all_raw = tracked_raw + untracked_raw
    if len(all_raw) > 4096:
        raise PatchScopeError("patch scope changed-path count exceeds the evaluation bound")
    paths = [os.fsdecode(item).replace("\\", "/") for item in all_raw]
    out_of_scope = [
        (raw, path)
        for raw, path in zip(all_raw, paths)
        if not any(harness_topology.scope_contains(scope, path) for scope in profile["allowedScopes"])
    ]
    if untracked_raw and not profile["allowUntracked"]:
        untracked_set = set(untracked_raw)
        out_of_scope.extend(
            (raw, path) for raw, path in zip(all_raw, paths)
            if raw in untracked_set and (raw, path) not in out_of_scope
        )
    maximum_exceeded = (
        profile["maximumChangedPaths"] is not None
        and len(set(all_raw)) > profile["maximumChangedPaths"]
    )
    completeness = "complete"
    added = deleted = 0
    for line in _git_bytes(root, "diff", "HEAD", "--numstat").splitlines():
        fields = line.split(b"\t", 2)
        if len(fields) < 2 or fields[0] == b"-" or fields[1] == b"-":
            completeness = "partial"
            continue
        try:
            added += int(fields[0])
            deleted += int(fields[1])
        except ValueError:
            completeness = "partial"
    line_exceeded = (
        profile["maximumAddedLines"] is not None and added > profile["maximumAddedLines"]
    ) or (
        profile["maximumDeletedLines"] is not None and deleted > profile["maximumDeletedLines"]
    )
    changed_refs = [store.pseudonym(repository_id, "path", os.fsdecode(raw)) for raw in all_raw]
    out_refs = [store.pseudonym(repository_id, "path", os.fsdecode(raw)) for raw, _ in out_of_scope]
    profile_fingerprint = types.digest_bytes(types.canonical_bytes(profile))
    return {
        "state": "measured",
        "profileFingerprint": profile_fingerprint,
        "changedTrackedCount": len(tracked_raw),
        "untrackedCount": len(untracked_raw),
        "outOfScopeCount": len(set(out_refs)),
        "changedPathRefs": sorted(set(changed_refs)),
        "outOfScopePathRefs": sorted(set(out_refs)),
        "withinDeclaredScope": not out_refs and not maximum_exceeded and not line_exceeded,
        "maximumChangedPathsExceeded": maximum_exceeded,
        "source": "git-evaluator",
        "fidelity": "exact",
        "completeness": completeness,
    }
