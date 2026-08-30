#!/usr/bin/env python3
"""Prepare, apply, and recover journaled Harness file transactions."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path, PurePosixPath

import harness_state


TRANSACTION_SCHEMA_VERSION = 1
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
    return harness_state.resolve_inside(root, JOURNAL_RELATIVE)


def is_allowed_target(relative: str) -> bool:
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
    skill_output = len(parts) >= 4 and parts[:2] == (".agents", "skills")
    agent_output = (
        len(parts) == 3
        and parts[:2] == (".codex", "agents")
        and path.suffix == ".toml"
    )
    return skill_output or agent_output or relative in {
        "AGENTS.md",
        "AGENTS.override.md",
        ".harness/manifest.json",
    }


def _transaction_relative(transaction_id: str) -> str:
    return f"{TRANSACTIONS_RELATIVE}/{transaction_id}"


def _stage_relative(transaction_id: str, relative: str) -> str:
    return f"{_transaction_relative(transaction_id)}/staged/{relative}"


def _backup_relative(transaction_id: str, relative: str) -> str:
    return f"{_transaction_relative(transaction_id)}/backups/{relative}"


def _write_journal(root: Path, journal: dict) -> None:
    harness_state.atomic_write_text(
        journal_path(root), json.dumps(journal, indent=2, ensure_ascii=False) + "\n"
    )


def _digest_path(path: Path) -> str:
    return harness_state.digest_bytes(path.read_bytes())


def _cleanup_transaction_directory(root: Path, transaction_id: str) -> None:
    transactions_root = harness_state.resolve_inside(root, TRANSACTIONS_RELATIVE)
    transaction_root = harness_state.resolve_inside(root, _transaction_relative(transaction_id))
    if transaction_root.parent != transactions_root:
        raise TransactionError("transaction directory is outside the reserved transaction root")
    if transaction_root.exists():
        if not transaction_root.is_dir():
            raise TransactionError("transaction workspace is not a directory")
        shutil.rmtree(transaction_root)
        harness_state.sync_directory(transactions_root)
    if transactions_root.is_dir():
        try:
            transactions_root.rmdir()
            harness_state.sync_directory(transactions_root.parent)
        except OSError:
            pass


def _cleanup_transaction(root: Path, journal: dict) -> None:
    _cleanup_transaction_directory(root, journal["transactionId"])
    path = journal_path(root)
    path.unlink(missing_ok=True)
    harness_state.sync_directory(path.parent)


def inspect_transaction(root: Path) -> dict:
    """Return non-mutating details for a journal or an orphaned staging workspace."""
    status = harness_state.transaction_status(root)
    if status is None:
        return {"state": "none", "workspaces": []}
    if status.get("state") == "orphaned-workspace":
        workspace = root / TRANSACTIONS_RELATIVE
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


def clean_orphaned_workspace(root: Path) -> dict:
    """Remove the reserved staging root only when no recovery journal exists."""
    status = harness_state.transaction_status(root)
    if status is None or status.get("state") != "orphaned-workspace":
        raise TransactionError("no orphaned Harness transaction workspace was found")
    workspace = root / TRANSACTIONS_RELATIVE
    if workspace.is_symlink() or not workspace.is_dir():
        raise TransactionError("orphaned transaction workspace is not a regular directory")
    workspaces = sorted(path.name for path in workspace.iterdir())
    shutil.rmtree(workspace)
    harness_state.sync_directory(workspace.parent)
    return {"state": "orphaned-workspace", "cleaned": True, "workspaces": workspaces}


def _validate_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        raise TransactionError(f"{label} must be a SHA-256 hash")
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
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise TransactionError(f"transaction operation {index} must be an object")
        relative = operation.get("path")
        action = operation.get("action")
        if not isinstance(relative, str) or not is_allowed_target(relative):
            raise TransactionError(f"transaction target is not allowed: {relative!r}")
        if relative in seen:
            raise TransactionError(f"duplicate transaction target: {relative}")
        seen.add(relative)
        harness_state.resolve_inside(root, relative)
        if action not in {"create", "update"}:
            raise TransactionError(f"invalid transaction action for {relative}: {action!r}")
        had_original = operation.get("hadOriginal")
        if had_original is not (action == "update"):
            raise TransactionError(f"transaction ownership mismatch for {relative}")
        _validate_hash(operation.get("desiredSha256"), f"{relative} desiredSha256")
        expected_stage = _stage_relative(transaction_id, relative)
        if operation.get("stage") != expected_stage:
            raise TransactionError(f"invalid staged path for {relative}")
        harness_state.resolve_inside(root, expected_stage)
        if had_original:
            _validate_hash(operation.get("originalSha256"), f"{relative} originalSha256")
            expected_backup = _backup_relative(transaction_id, relative)
            if operation.get("backup") != expected_backup:
                raise TransactionError(f"invalid backup path for {relative}")
            harness_state.resolve_inside(root, expected_backup)
        elif operation.get("originalSha256") is not None or operation.get("backup") is not None:
            raise TransactionError(f"create operation contains an original backup: {relative}")

    applied = journal.get("applied")
    if not isinstance(applied, list) or not all(isinstance(value, str) for value in applied):
        raise TransactionError("transaction applied must be an array of paths")
    if len(applied) != len(set(applied)) or not set(applied).issubset(seen):
        raise TransactionError("transaction applied contains duplicate or unknown paths")
    return journal


def load_journal(root: Path) -> dict:
    path = journal_path(root)
    if not path.is_file():
        raise TransactionError("no pending Harness transaction was found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransactionError(f"invalid transaction journal: {exc}") from exc
    return validate_journal(root, data)


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
        path = harness_state.resolve_inside(root, relative)
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


def prepare_transaction(
    root: Path,
    outputs: dict[str, str],
    actions: dict[str, str],
    original_hashes: dict[str, str],
    managed_preconditions: list[dict],
) -> dict | None:
    ensure_no_pending_transaction(root)
    if set(outputs) != set(actions):
        raise TransactionError("transaction outputs and action paths do not match")
    for relative in outputs:
        if not isinstance(relative, str) or not is_allowed_target(relative):
            raise TransactionError(f"transaction target is not allowed: {relative!r}")
        harness_state.resolve_inside(root, relative)
    if not all(isinstance(entry, dict) for entry in managed_preconditions):
        raise TransactionError("managed preconditions must be objects")
    _validate_preconditions(root, actions, original_hashes, managed_preconditions)

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
            target = harness_state.resolve_inside(root, relative)
            desired = outputs[relative].encode("utf-8")
            stage_relative = _stage_relative(transaction_id, relative)
            operation = {
                "path": relative,
                "action": action,
                "hadOriginal": action == "update",
                "originalSha256": None,
                "desiredSha256": harness_state.digest_bytes(desired),
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
                operation["backup"] = backup_relative
            elif target.exists():
                raise TransactionError(f"create target appeared while staging: {relative}")
            journal["operations"].append(operation)
            prepared_data.append((operation, desired, original))

        _write_journal(root, journal)
        for operation, desired, original in prepared_data:
            stage = harness_state.resolve_inside(root, operation["stage"])
            harness_state.atomic_write_bytes(stage, desired)
            if original is not None:
                backup = harness_state.resolve_inside(root, operation["backup"])
                harness_state.atomic_write_bytes(backup, original)
        journal["state"] = "prepared"
        _write_journal(root, journal)
        return validate_journal(root, journal)
    except Exception:
        if not journal_path(root).exists():
            _cleanup_transaction_directory(root, transaction_id)
        raise


def _validated_operation_data(root: Path, operation: dict) -> tuple[Path, bytes, bytes | None]:
    target = harness_state.resolve_inside(root, operation["path"])
    stage = harness_state.resolve_inside(root, operation["stage"], must_exist=True)
    desired = stage.read_bytes()
    if harness_state.digest_bytes(desired) != operation["desiredSha256"]:
        raise TransactionError(f"staged content is corrupt: {operation['path']}")
    original: bytes | None = None
    if operation["hadOriginal"]:
        backup = harness_state.resolve_inside(root, operation["backup"], must_exist=True)
        original = backup.read_bytes()
        if harness_state.digest_bytes(original) != operation["originalSha256"]:
            raise TransactionError(f"backup content is corrupt: {operation['path']}")
    return target, desired, original


def recover_transaction(root: Path) -> dict:
    journal = load_journal(root)
    if journal["state"] in {"preparing", "committed", "rolled-back"}:
        previous_state = journal["state"]
        _cleanup_transaction(root, journal)
        return {"state": previous_state, "cleaned": True, "restored": 0, "removed": 0}

    prepared: list[tuple[dict, Path, bytes, bytes | None, str | None]] = []
    conflicts: list[str] = []
    for operation in journal["operations"]:
        target, desired, original = _validated_operation_data(root, operation)
        if target.exists() and not target.is_file():
            conflicts.append(f"{operation['path']}: target is not a regular file")
            current_hash = None
        else:
            current_hash = _digest_path(target) if target.is_file() else None
        if operation["hadOriginal"]:
            if current_hash is None:
                conflicts.append(f"{operation['path']}: original target was removed externally")
            elif current_hash not in {
                operation["originalSha256"],
                operation["desiredSha256"],
            }:
                conflicts.append(f"{operation['path']}: content changed outside the transaction")
        elif current_hash not in {None, operation["desiredSha256"]}:
            conflicts.append(f"{operation['path']}: created target was modified after interruption")
        prepared.append((operation, target, desired, original, current_hash))

    if conflicts:
        raise TransactionError("recovery refused: " + "; ".join(conflicts))

    restored = 0
    removed = 0
    for operation, target, _desired, original, current_hash in reversed(prepared):
        if operation["hadOriginal"]:
            if current_hash != operation["originalSha256"]:
                if original is None:
                    raise TransactionError(f"missing recovery backup: {operation['path']}")
                harness_state.atomic_write_bytes(target, original)
                restored += 1
        elif current_hash == operation["desiredSha256"]:
            target.unlink()
            harness_state.sync_directory(target.parent)
            removed += 1

    journal["state"] = "rolled-back"
    _write_journal(root, journal)
    _cleanup_transaction(root, journal)
    return {"state": "rolled-back", "cleaned": True, "restored": restored, "removed": removed}


def apply_transaction(root: Path, journal: dict) -> dict:
    validate_journal(root, journal)
    if journal["state"] != "prepared":
        raise TransactionError(
            f"transaction must be prepared before apply, found {journal['state']!r}"
        )
    prepared: list[tuple[dict, Path, bytes]] = []
    try:
        for operation in journal["operations"]:
            target, desired, _original = _validated_operation_data(root, operation)
            if operation["hadOriginal"]:
                if not target.is_file() or _digest_path(target) != operation["originalSha256"]:
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
            if operation["hadOriginal"]:
                if not target.is_file() or _digest_path(target) != operation["originalSha256"]:
                    raise TransactionError(
                        f"update target changed during transaction apply: {operation['path']}"
                    )
            elif target.exists():
                raise TransactionError(
                    f"create target appeared during transaction apply: {operation['path']}"
                )
            harness_state.atomic_write_bytes(target, desired)
            if operation["path"] not in journal["applied"]:
                journal["applied"].append(operation["path"])
            _write_journal(root, journal)
    except Exception as apply_error:
        try:
            recovery = recover_transaction(root)
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
