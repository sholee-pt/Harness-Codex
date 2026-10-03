#!/usr/bin/env python3
"""Prepare, apply, and recover journaled Harness file transactions."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path, PurePosixPath

import harness_metadata
import harness_state
from harness_eval_lock import project_lock, project_locked


TRANSACTION_SCHEMA_VERSION = harness_metadata.TRANSACTION_SCHEMA_VERSION
JOURNAL_RELATIVE = ".harness/transaction.json"
TRANSACTIONS_RELATIVE = ".harness/transactions"
TRANSACTION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
VALID_STATES = {
    "preparing",
    "prepared",
    "applying",
    "recovery-required",
    "committed",
    "rolled-back",
}
VALID_ACTIONS = {"create", "update", "unchanged"}


class TransactionError(ValueError):
    pass


def journal_path(root: Path) -> Path:
    return _resolve_inside(root, JOURNAL_RELATIVE)


def is_allowed_target(relative: str, *, root: Path | None = None) -> bool:
    if not isinstance(relative, str) or "\\" in relative:
        return False
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or path.as_posix() != relative
        or any(part in {".", ".."} for part in path.parts)
    ):
        return False
    parts = path.parts
    if any(part.casefold() == ".git" for part in parts):
        return False
    skill_output = (
        len(parts) >= 4 and parts[:2] == (".agents", "skills")
        and parts[2].casefold() != "harness"
    )
    agent_output = (
        len(parts) == 3
        and parts[:2] == (".codex", "agents")
        and path.suffix == ".toml"
    )
    return skill_output or agent_output or relative in {
        "AGENTS.md",
        "AGENTS.override.md",
        ".harness/manifest.json",
    } or (root is not None and harness_state.is_instruction_relative(root, relative))


def _transaction_relative(transaction_id: str) -> str:
    return f"{TRANSACTIONS_RELATIVE}/{transaction_id}"


def _resolve_inside(root: Path, relative: str, *, must_exist=False) -> Path:
    path = harness_state.resolve_inside(root, relative, must_exist=must_exist)
    return harness_state.io_path(path) if os.name == "nt" and len(str(path.absolute())) >= 248 else path


def _stage_relative(transaction_id: str, relative: str) -> str:
    return f"{_transaction_relative(transaction_id)}/staged/{relative}"


def _backup_relative(transaction_id: str, relative: str) -> str:
    return f"{_transaction_relative(transaction_id)}/backups/{relative}"


def _write_journal(root: Path, journal: dict) -> None:
    if journal_path(root).exists():
        _require_owner(root, journal)
    elif journal["state"] != "preparing":
        raise TransactionError("transaction journal disappeared; preserve staged data for review")
    harness_state.atomic_write_text(
        journal_path(root), json.dumps(journal, indent=2, ensure_ascii=False) + "\n"
    )


def _digest_path(path: Path) -> str:
    return harness_state.digest_bytes(path.read_bytes())


def _cleanup_transaction_directory(root: Path, transaction_id: str) -> None:
    transactions_root = _resolve_inside(root, TRANSACTIONS_RELATIVE)
    transaction_root = _resolve_inside(root, _transaction_relative(transaction_id))
    if harness_state.io_path(transaction_root.parent) != harness_state.io_path(transactions_root):
        raise TransactionError("transaction directory is outside the reserved transaction root")
    if transaction_root.exists():
        if not transaction_root.is_dir():
            raise TransactionError("transaction workspace is not a directory")
        shutil.rmtree(harness_state.io_path(transaction_root))
        harness_state.sync_directory(transactions_root)
    if transactions_root.is_dir():
        try:
            transactions_root.rmdir()
            harness_state.sync_directory(transactions_root.parent)
        except OSError:
            pass


def _cleanup_transaction(root: Path, journal: dict) -> None:
    _require_owner(root, journal)
    _cleanup_transaction_directory(root, journal["transactionId"])
    path = journal_path(root)
    path.unlink(missing_ok=True)
    harness_state.sync_directory(path.parent)


def inspect_transaction(root: Path) -> dict:
    """Return non-mutating details for a journal or an orphaned staging workspace."""
    try:
        _resolve_inside(root, JOURNAL_RELATIVE)
        workspace = _resolve_inside(root, TRANSACTIONS_RELATIVE)
    except (OSError, harness_state.StateError) as exc:
        return {"state": "invalid", "detail": str(exc), "workspaces": [], "cleanupAllowed": False}
    status = harness_state.transaction_status(root)
    if status is None:
        return {"state": "none", "workspaces": []}
    if status.get("state") == "orphaned-workspace":
        if workspace.is_symlink() or not workspace.is_dir():
            return {**status, "workspaces": [], "cleanupAllowed": False}
        workspaces = sorted(path.name for path in workspace.iterdir())
        return {**status, "workspaces": workspaces, "cleanupAllowed": True}
    try:
        journal = load_journal(root)
    except TransactionError as exc:
        return {**status, "detail": str(exc), "cleanupAllowed": False}
    return {
        "state": journal["state"],
        "transactionId": journal["transactionId"],
        "schemaVersion": journal["schemaVersion"],
        "operations": [
            {"path": item["path"], "action": item["action"]}
            for item in journal["operations"]
        ],
        "applied": list(journal["applied"]),
        "cleanupAllowed": False,
    }


@project_locked
def clean_orphaned_workspace(root: Path) -> dict:
    """Remove the reserved staging root only when no recovery journal exists."""
    _resolve_inside(root, JOURNAL_RELATIVE)
    workspace = _resolve_inside(root, TRANSACTIONS_RELATIVE)
    status = harness_state.transaction_status(root)
    if status is None or status.get("state") != "orphaned-workspace":
        raise TransactionError("no orphaned Harness transaction workspace was found")
    if workspace.is_symlink() or not workspace.is_dir():
        raise TransactionError("orphaned transaction workspace is not a regular directory")
    workspaces = sorted(path.name for path in workspace.iterdir())
    workspace = _resolve_inside(root, TRANSACTIONS_RELATIVE)
    shutil.rmtree(workspace)
    harness_state.sync_directory(workspace.parent)
    return {"state": "orphaned-workspace", "cleaned": True, "workspaces": workspaces}


def _validate_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        raise TransactionError(f"{label} must be a SHA-256 hash")
    return value


def _validate_mode(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0o777:
        raise TransactionError(f"{label} must contain only POSIX permission bits")
    return value


def validate_journal(root: Path, journal: object) -> dict:
    if not isinstance(journal, dict):
        raise TransactionError("transaction journal root must be an object")
    if journal.get("schemaVersion") != TRANSACTION_SCHEMA_VERSION:
        raise TransactionError(
            f"transaction schemaVersion must be {TRANSACTION_SCHEMA_VERSION}"
        )
    if journal.get("runtime") != harness_state.RUNTIME:
        raise TransactionError("transaction runtime does not match this Harness edition")
    transaction_id = journal.get("transactionId")
    if not isinstance(transaction_id, str) or not TRANSACTION_ID_RE.fullmatch(transaction_id):
        raise TransactionError("transactionId must be 32 lowercase hexadecimal characters")
    state = journal.get("state")
    if state not in VALID_STATES:
        raise TransactionError(f"invalid transaction state: {state!r}")
    operations = journal.get("operations")
    if not isinstance(operations, list) or not operations:
        raise TransactionError("transaction operations must be a non-empty array")

    seen: set[str] = set()
    operation_paths: list[str] = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise TransactionError(f"transaction operation {index} must be an object")
        relative = operation.get("path")
        action = operation.get("action")
        if not isinstance(relative, str) or not is_allowed_target(relative, root=root):
            raise TransactionError(f"transaction target is not allowed: {relative!r}")
        if relative in seen:
            raise TransactionError(f"duplicate transaction target: {relative}")
        seen.add(relative)
        operation_paths.append(relative)
        _resolve_inside(root, relative)
        if action not in {"create", "update"}:
            raise TransactionError(f"invalid transaction action for {relative}: {action!r}")
        had_original = operation.get("hadOriginal")
        if had_original is not (action == "update"):
            raise TransactionError(f"transaction ownership mismatch for {relative}")
        _validate_hash(operation.get("desiredSha256"), f"{relative} desiredSha256")
        expected_stage = _stage_relative(transaction_id, relative)
        if operation.get("stage") != expected_stage:
            raise TransactionError(f"invalid staged path for {relative}")
        _resolve_inside(root, expected_stage)
        if had_original:
            _validate_hash(operation.get("originalSha256"), f"{relative} originalSha256")
            _validate_mode(operation.get("originalMode"), f"{relative} originalMode")
            expected_backup = _backup_relative(transaction_id, relative)
            if operation.get("backup") != expected_backup:
                raise TransactionError(f"invalid backup path for {relative}")
            _resolve_inside(root, expected_backup)
        elif (
            operation.get("originalSha256") is not None
            or operation.get("originalMode") is not None
            or operation.get("backup") is not None
        ):
            raise TransactionError(f"create operation contains original metadata: {relative}")
        _validate_mode(operation.get("desiredMode"), f"{relative} desiredMode")

    try:
        harness_state.validate_file_namespace(operation_paths, label="transaction operations")
    except harness_state.StateError as exc:
        raise TransactionError(str(exc)) from exc

    applied = journal.get("applied")
    if not isinstance(applied, list) or not all(isinstance(value, str) for value in applied):
        raise TransactionError("transaction applied must be an array of paths")
    if len(applied) != len(set(applied)) or not set(applied).issubset(seen):
        raise TransactionError("transaction applied contains duplicate or unknown paths")
    return journal


def _read_journal(root: Path) -> dict:
    path = journal_path(root)
    if not path.is_file():
        raise TransactionError("no pending Harness transaction was found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransactionError(f"invalid transaction journal: {exc}") from exc
    return data


def load_journal(root: Path) -> dict:
    return validate_journal(root, _read_journal(root))


def _require_owner(root: Path, journal: dict) -> dict:
    # Validate the full path/operation contract once at entry. During writes,
    # compare immutable fields instead of repeating all filesystem path checks.
    current = _read_journal(root)
    if not isinstance(current, dict) or current.get("transactionId") != journal["transactionId"]:
        raise TransactionError("transaction ownership changed; another journal must not be overwritten or recovered")
    if any(current.get(key) != journal[key] for key in ("schemaVersion", "runtime", "operations")):
        raise TransactionError("transaction contract changed; preserve the journal for review")
    return current


def ensure_no_pending_transaction(root: Path) -> None:
    status = harness_state.transaction_status(root)
    if status is not None:
        raise TransactionError(
            f"Harness transaction state is {status.get('state')!r}; "
            "resolve it before planning another apply"
        )


def _validate_preconditions(
    root: Path,
    actions: dict[str, str],
    original_hashes: dict[str, str],
    original_modes: dict[str, int],
    managed_preconditions: list[dict],
) -> None:
    for entry in managed_preconditions:
        state = harness_state.entry_status(root, entry)
        if state.get("state") != "unchanged":
            raise TransactionError(
                f"managed precondition changed before apply: {entry.get('path')!r} is {state.get('state')}"
            )

    for relative, action in actions.items():
        if action not in VALID_ACTIONS:
            raise TransactionError(f"invalid application action for {relative!r}: {action!r}")
        path = _resolve_inside(root, relative)
        if action == "create":
            if path.exists():
                raise TransactionError(f"create target appeared before apply: {relative}")
            continue
        expected = original_hashes.get(relative)
        if not isinstance(expected, str) or not HASH_RE.fullmatch(expected):
            raise TransactionError(f"missing original hash precondition for {relative}")
        if not path.is_file():
            raise TransactionError(f"existing target disappeared before apply: {relative}")
        actual = _digest_path(path)
        if actual != expected:
            raise TransactionError(f"existing target changed before apply: {relative}")
        expected_mode = original_modes.get(relative)
        if not isinstance(expected_mode, int) or isinstance(expected_mode, bool):
            raise TransactionError(f"missing original mode precondition for {relative}")
        if not harness_state.mode_matches(path, expected_mode):
            raise TransactionError(f"existing target mode changed before apply: {relative}")


@project_locked
def prepare_transaction(
    root: Path,
    outputs: dict[str, str],
    actions: dict[str, str],
    original_hashes: dict[str, str],
    original_modes: dict[str, int],
    desired_modes: dict[str, int],
    managed_preconditions: list[dict],
) -> dict | None:
    ensure_no_pending_transaction(root)
    if set(outputs) != set(actions):
        raise TransactionError("transaction outputs and action paths do not match")
    if set(outputs) != set(desired_modes):
        raise TransactionError("transaction desired modes and output paths do not match")
    try:
        harness_state.validate_file_namespace(outputs, label="transaction outputs")
    except harness_state.StateError as exc:
        raise TransactionError(str(exc)) from exc
    for relative in outputs:
        if not isinstance(relative, str) or not is_allowed_target(relative, root=root):
            raise TransactionError(f"transaction target is not allowed: {relative!r}")
        _resolve_inside(root, relative)
    if not all(isinstance(entry, dict) for entry in managed_preconditions):
        raise TransactionError("managed preconditions must be objects")
    for relative, desired_mode in desired_modes.items():
        _validate_mode(desired_mode, f"{relative} desired mode")
    _validate_preconditions(
        root, actions, original_hashes, original_modes, managed_preconditions
    )

    active_paths = [relative for relative, action in actions.items() if action != "unchanged"]
    if not active_paths:
        return None

    transaction_id = uuid.uuid4().hex
    journal = {
        "schemaVersion": TRANSACTION_SCHEMA_VERSION,
        "runtime": harness_state.RUNTIME,
        "transactionId": transaction_id,
        "state": "preparing",
        "operations": [],
        "applied": [],
    }
    prepared_data: list[tuple[dict, bytes, bytes | None]] = []
    try:
        for relative in sorted(
            active_paths, key=lambda value: (value == ".harness/manifest.json", value)
        ):
            action = actions[relative]
            target = _resolve_inside(root, relative)
            desired = outputs[relative].encode("utf-8")
            stage_relative = _stage_relative(transaction_id, relative)
            operation = {
                "path": relative,
                "action": action,
                "hadOriginal": action == "update",
                "originalSha256": None,
                "originalMode": None,
                "desiredSha256": harness_state.digest_bytes(desired),
                "desiredMode": desired_modes[relative],
                "stage": stage_relative,
                "backup": None,
            }
            original: bytes | None = None
            if action == "update":
                if not target.is_file():
                    raise TransactionError(f"update target disappeared while staging: {relative}")
                original = target.read_bytes()
                original_hash = harness_state.digest_bytes(original)
                if original_hash != original_hashes[relative]:
                    raise TransactionError(f"update target changed while staging: {relative}")
                backup_relative = _backup_relative(transaction_id, relative)
                operation["originalSha256"] = original_hash
                operation["originalMode"] = harness_state.current_mode(target)
                if not harness_state.mode_matches(target, original_modes[relative]):
                    raise TransactionError(f"update target mode changed while staging: {relative}")
                operation["backup"] = backup_relative
            elif target.exists():
                raise TransactionError(f"create target appeared while staging: {relative}")
            journal["operations"].append(operation)
            prepared_data.append((operation, desired, original))

        _write_journal(root, journal)
        for operation, desired, original in prepared_data:
            stage = _resolve_inside(root, operation["stage"])
            harness_state.atomic_write_bytes(stage, desired)
            if original is not None:
                backup = _resolve_inside(root, operation["backup"])
                harness_state.atomic_write_bytes(backup, original)
        journal["state"] = "prepared"
        _write_journal(root, journal)
        return validate_journal(root, journal)
    except Exception:
        if not journal_path(root).exists():
            _cleanup_transaction_directory(root, transaction_id)
        raise


def _validated_operation_data(root: Path, operation: dict) -> tuple[Path, bytes, bytes | None]:
    target = _resolve_inside(root, operation["path"])
    stage = _resolve_inside(root, operation["stage"], must_exist=True)
    desired = stage.read_bytes()
    if harness_state.digest_bytes(desired) != operation["desiredSha256"]:
        raise TransactionError(f"staged content is corrupt: {operation['path']}")
    original: bytes | None = None
    if operation["hadOriginal"]:
        backup = _resolve_inside(root, operation["backup"], must_exist=True)
        original = backup.read_bytes()
        if harness_state.digest_bytes(original) != operation["originalSha256"]:
            raise TransactionError(f"backup content is corrupt: {operation['path']}")
    return target, desired, original


def _mode_matches(path: Path, expected: int) -> bool:
    return path.is_file() and harness_state.mode_matches(path, expected)


@project_locked
def recover_transaction(root: Path, *, expected_id: str | None = None) -> dict:
    journal = load_journal(root)
    if expected_id is not None and journal["transactionId"] != expected_id:
        raise TransactionError("transaction ownership changed; recovery refused")
    if journal["state"] in {"preparing", "committed", "rolled-back"}:
        previous_state = journal["state"]
        _cleanup_transaction(root, journal)
        return {"state": previous_state, "cleaned": True, "restored": 0, "removed": 0}

    prepared: list[tuple[dict, Path, bytes, bytes | None, str | None, int | None]] = []
    conflicts: list[str] = []
    for operation in journal["operations"]:
        target, desired, original = _validated_operation_data(root, operation)
        if target.exists() and not target.is_file():
            conflicts.append(f"{operation['path']}: target is not a regular file")
            current_hash = None
        else:
            current_hash = _digest_path(target) if target.is_file() else None
        current_mode = harness_state.current_mode(target) if target.is_file() else None
        if operation["hadOriginal"]:
            if current_hash is None:
                conflicts.append(f"{operation['path']}: original target was removed externally")
            elif not (
                current_hash == operation["originalSha256"]
                and _mode_matches(target, operation["originalMode"])
            ) and not (
                current_hash == operation["desiredSha256"]
                and _mode_matches(target, operation["desiredMode"])
            ):
                conflicts.append(f"{operation['path']}: content changed outside the transaction")
        elif current_hash is not None and not (
            current_hash == operation["desiredSha256"]
            and _mode_matches(target, operation["desiredMode"])
        ):
            conflicts.append(f"{operation['path']}: created target was modified after interruption")
        prepared.append((operation, target, desired, original, current_hash, current_mode))

    if conflicts:
        raise TransactionError("recovery refused: " + "; ".join(conflicts))

    restored = 0
    removed = 0
    for operation, target, _desired, original, current_hash, current_mode in reversed(prepared):
        target = _resolve_inside(root, operation["path"])
        observed_hash = _digest_path(target) if target.is_file() else None
        observed_mode = harness_state.current_mode(target) if target.is_file() else None
        if (target.exists() and not target.is_file()) or observed_hash != current_hash or observed_mode != current_mode:
            raise TransactionError(f"target changed during recovery: {operation['path']}")
        if operation["hadOriginal"]:
            if not (
                current_hash == operation["originalSha256"]
                and _mode_matches(target, operation["originalMode"])
            ):
                if original is None:
                    raise TransactionError(f"missing recovery backup: {operation['path']}")
                harness_state.atomic_write_bytes(
                    target, original, mode=operation["originalMode"]
                )
                restored += 1
        elif current_hash == operation["desiredSha256"] and _mode_matches(
            target, operation["desiredMode"]
        ):
            target.unlink()
            harness_state.sync_directory(target.parent)
            removed += 1

    journal["state"] = "rolled-back"
    _write_journal(root, journal)
    _cleanup_transaction(root, journal)
    return {"state": "rolled-back", "cleaned": True, "restored": restored, "removed": removed}


@project_locked
def apply_transaction(root: Path, journal: dict) -> dict:
    validate_journal(root, journal)
    if _require_owner(root, journal) != journal:
        raise TransactionError("transaction journal changed after preparation")
    if journal["state"] != "prepared":
        raise TransactionError(
            f"transaction must be prepared before apply, found {journal['state']!r}"
        )
    prepared: list[tuple[dict, Path, bytes]] = []
    try:
        for operation in journal["operations"]:
            target, desired, _original = _validated_operation_data(root, operation)
            if operation["hadOriginal"]:
                if (
                    not target.is_file()
                    or _digest_path(target) != operation["originalSha256"]
                    or not _mode_matches(target, operation["originalMode"])
                ):
                    raise TransactionError(
                        f"update target changed after transaction preparation: {operation['path']}"
                    )
            elif target.exists():
                raise TransactionError(
                    f"create target appeared after transaction preparation: {operation['path']}"
                )
            prepared.append((operation, target, desired))
    except Exception:
        _cleanup_transaction(root, journal)
        raise

    journal["state"] = "applying"
    try:
        _write_journal(root, journal)
        for operation, target, desired in prepared:
            target = _resolve_inside(root, operation["path"])
            if operation["hadOriginal"]:
                if (
                    not target.is_file()
                    or _digest_path(target) != operation["originalSha256"]
                    or not _mode_matches(target, operation["originalMode"])
                ):
                    raise TransactionError(
                        f"update target changed during transaction apply: {operation['path']}"
                    )
            elif target.exists():
                raise TransactionError(
                    f"create target appeared during transaction apply: {operation['path']}"
                )
            harness_state.atomic_write_bytes(target, desired, mode=operation["desiredMode"])
            if operation["path"] not in journal["applied"]:
                journal["applied"].append(operation["path"])
            _write_journal(root, journal)
    except Exception as apply_error:
        try:
            recovery = recover_transaction(root, expected_id=journal["transactionId"])
        except Exception as recovery_error:
            journal["state"] = "recovery-required"
            try:
                _write_journal(root, journal)
            except Exception:
                pass
            raise TransactionError(
                f"apply failed and automatic recovery failed: {apply_error}; recovery error: {recovery_error}"
            ) from apply_error
        raise TransactionError(
            f"apply failed and was rolled back: {apply_error}; restored={recovery['restored']}, removed={recovery['removed']}"
        ) from apply_error

    journal["state"] = "committed"
    _write_journal(root, journal)
    try:
        _cleanup_transaction(root, journal)
    except (OSError, TransactionError) as exc:
        raise TransactionError(
            f"outputs were committed but transaction cleanup failed; run --recover: {exc}"
        ) from exc
    return {"state": "committed", "writes": len(journal["operations"]), "cleaned": True}
