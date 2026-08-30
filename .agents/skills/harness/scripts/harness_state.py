#!/usr/bin/env python3
"""Record and verify Codex Harness-managed files and phase snapshots."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Iterable


BEGIN_MARKER = "<!-- harness:begin -->"
END_MARKER = "<!-- harness:end -->"
RUNTIME = "codex"
CURRENT_SCHEMA_VERSION = 3
GENERATOR_VERSION = "3.1.0"
TRANSACTION_JOURNAL_RELATIVE = ".harness/transaction.json"
TRANSACTION_SCHEMA_VERSION = 1


class StateError(ValueError):
    pass


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sync_directory(path: Path) -> bool:
    """Best-effort persistence for directory entry changes on POSIX filesystems."""
    if os.name == "nt":
        return False
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EINVAL, errno.ENOTSUP}:
            return False
        raise
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if exc.errno in {errno.EINVAL, errno.ENOTSUP}:
                return False
            raise
    finally:
        os.close(descriptor)
    return True


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Replace a file atomically after writing it in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.harness-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
        temporary_name = None
        sync_directory(path.parent)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def resolve_inside(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise StateError(f"managed path must use POSIX separators: {relative!r}")
    candidate_rel = PurePosixPath(relative)
    if (
        candidate_rel.is_absolute()
        or candidate_rel.as_posix() != relative
        or any(part in {".", ".."} for part in candidate_rel.parts)
    ):
        raise StateError(f"managed path must be a normalized relative path: {relative}")
    candidate = root.joinpath(*candidate_rel.parts).resolve()
    if candidate == root or root not in candidate.parents:
        raise StateError(f"managed path escapes repository root: {relative}")
    if must_exist and not candidate.is_file():
        raise StateError(f"managed file is missing: {relative}")
    return candidate


def normalize_relative(root: Path, value: str) -> str:
    path = resolve_inside(root, value, must_exist=True)
    return path.relative_to(root).as_posix()


def extract_managed_block(text: str) -> str:
    if text.count(BEGIN_MARKER) != 1 or text.count(END_MARKER) != 1:
        raise StateError("managed block markers must each occur exactly once")
    start = text.index(BEGIN_MARKER)
    end = text.index(END_MARKER, start) + len(END_MARKER)
    if end <= start:
        raise StateError("managed block markers are out of order")
    return text[start:end]


def content_for_entry(path: Path, kind: str) -> bytes:
    if kind == "file":
        return path.read_bytes()
    if kind == "managed-block":
        block = extract_managed_block(path.read_text(encoding="utf-8"))
        return block.encode("utf-8")
    raise StateError(f"unsupported managed entry kind: {kind}")


def load_manifest(root: Path) -> tuple[Path, dict | None]:
    path = root / ".harness" / "manifest.json"
    if not path.exists():
        return path, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"invalid manifest: {exc}") from exc
    if not isinstance(data, dict):
        raise StateError("manifest root must be an object")
    return path, data


def transaction_status(root: Path) -> dict | None:
    path = root / TRANSACTION_JOURNAL_RELATIVE
    if not path.exists():
        transaction_workspace = root / ".harness" / "transactions"
        if transaction_workspace.exists():
            return {
                "state": "orphaned-workspace",
                "detail": ".harness/transactions exists without a transaction journal",
            }
        return None
    if not path.is_file():
        return {"state": "invalid", "detail": "transaction journal is not a regular file"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"state": "invalid", "detail": str(exc)}
    if not isinstance(data, dict):
        return {"state": "invalid", "detail": "transaction journal root is not an object"}
    return {
        "state": data.get("state", "invalid"),
        "transactionId": data.get("transactionId"),
    }


def validate_runtime(manifest: dict) -> None:
    generator = manifest.get("generator")
    if not isinstance(generator, dict):
        raise StateError("manifest generator must be an object")
    recorded = generator.get("runtime")
    if recorded != RUNTIME:
        raise StateError(f"manifest runtime is {recorded!r}, expected {RUNTIME!r}")


def active_instruction_relative(root: Path) -> str:
    """Return the root instruction file Codex will prefer."""
    return "AGENTS.override.md" if (root / "AGENTS.override.md").is_file() else "AGENTS.md"


def entry_status(root: Path, entry: dict) -> dict:
    relative = entry.get("path")
    kind = entry.get("kind", "file")
    expected = entry.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected, str):
        return {"path": relative, "kind": kind, "state": "invalid-entry"}
    try:
        path = resolve_inside(root, relative)
        if not path.is_file():
            return {"path": relative, "kind": kind, "state": "missing"}
        actual = digest_bytes(content_for_entry(path, kind))
    except (OSError, UnicodeError, StateError) as exc:
        return {"path": relative, "kind": kind, "state": "invalid", "detail": str(exc)}
    state = "unchanged" if actual == expected else "modified"
    return {"path": relative, "kind": kind, "state": state, "sha256": actual}


def status_report(root: Path) -> dict:
    transaction = transaction_status(root)
    _, manifest = load_manifest(root)
    if manifest is None:
        return {
            "runtime": RUNTIME,
            "manifest": "missing",
            "transaction": transaction,
            "files": [],
            "counts": {},
        }
    validate_runtime(manifest)
    entries = manifest.get("managedFiles", [])
    if not isinstance(entries, list):
        raise StateError("managedFiles must be an array")
    files = [entry_status(root, entry) for entry in entries if isinstance(entry, dict)]
    counts: dict[str, int] = {}
    for item in files:
        counts[item["state"]] = counts.get(item["state"], 0) + 1
    return {
        "runtime": RUNTIME,
        "manifest": "present",
        "transaction": transaction,
        "files": files,
        "counts": counts,
    }


def build_entries(root: Path, files: Iterable[str], block_files: Iterable[str]) -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()
    for kind, values in (("file", files), ("managed-block", block_files)):
        for value in values:
            relative = normalize_relative(root, value)
            if relative in seen:
                raise StateError(f"duplicate managed path: {relative}")
            seen.add(relative)
            path = resolve_inside(root, relative, must_exist=True)
            entries.append(
                {
                    "path": relative,
                    "kind": kind,
                    "sha256": digest_bytes(content_for_entry(path, kind)),
                }
            )
    return sorted(entries, key=lambda item: item["path"])


def record_manifest(root: Path, files: list[str], block_files: list[str]) -> dict:
    manifest_path, manifest = load_manifest(root)
    if manifest is None:
        raise StateError("create .harness/manifest.json from the bundled template before recording files")
    validate_runtime(manifest)
    if manifest.get("managedFiles"):
        raise StateError(
            "managed files are already recorded; use harness_apply.py so existing hashes are checked before update"
        )
    manifest["managedFiles"] = build_entries(root, files, block_files)
    atomic_write_text(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def migrate_manifest(root: Path) -> dict:
    if transaction_status(root) is not None:
        raise StateError("cannot migrate while a Harness transaction journal exists; recover it first")
    manifest_path, manifest = load_manifest(root)
    if manifest is None:
        raise StateError("missing .harness/manifest.json")
    validate_runtime(manifest)
    version = manifest.get("schemaVersion")
    if version == CURRENT_SCHEMA_VERSION:
        return manifest
    if version not in {1, 2}:
        raise StateError(f"unsupported manifest schemaVersion: {version!r}")

    report = status_report(root)
    if has_conflict(report["files"]):
        raise StateError("cannot migrate a manifest while managed files are modified, missing, or invalid")

    if version == 1:
        managed_blocks = [
            entry.get("path")
            for entry in manifest.get("managedFiles", [])
            if isinstance(entry, dict) and entry.get("kind") == "managed-block"
        ]
        if len(managed_blocks) > 1:
            raise StateError("schema v1 manifest contains multiple managed instruction blocks")

        project = manifest.get("project")
        if not isinstance(project, dict):
            raise StateError("manifest project must be an object")
        project.setdefault(
            "rationale",
            {
                "summary": "Migrated from schema v1; regenerate the harness to record detailed topology rationale.",
                "uncertainties": [],
            },
        )
        manifest["instructionFile"] = (
            managed_blocks[0] if managed_blocks else active_instruction_relative(root)
        )

    generator = manifest.get("generator")
    if not isinstance(generator, dict):
        raise StateError("manifest generator must be an object")
    generator["version"] = GENERATOR_VERSION
    manifest["schemaVersion"] = CURRENT_SCHEMA_VERSION
    manifest["application"] = {
        "mode": "journaled",
        "transactionSchemaVersion": TRANSACTION_SCHEMA_VERSION,
    }
    atomic_write_text(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def snapshot_data(root: Path, files: list[str]) -> dict:
    entries = build_entries(root, files, [])
    return {"schemaVersion": 1, "files": entries}


def write_snapshot(root: Path, output: str, files: list[str]) -> dict:
    output_path = resolve_inside(root, output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = snapshot_data(root, files)
    output_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def verify_snapshot(root: Path, snapshot: str) -> dict:
    snapshot_path = resolve_inside(root, snapshot, must_exist=True)
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"invalid snapshot: {exc}") from exc
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise StateError("snapshot root must be a schemaVersion 1 object")
    entries = data.get("files")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise StateError("snapshot files must be an array of objects")
    results = [entry_status(root, entry) for entry in entries]
    return {"snapshot": snapshot_path.relative_to(root).as_posix(), "files": results}


def has_conflict(states: Iterable[dict]) -> bool:
    return any(item.get("state") != "unchanged" for item in states)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--root", default=".")

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--root", default=".")
    record_parser.add_argument("--file", action="append", default=[])
    record_parser.add_argument("--block-file", action="append", default=[])

    migrate_parser = subparsers.add_parser("migrate")
    migrate_parser.add_argument("--root", default=".")

    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--root", default=".")
    snapshot_parser.add_argument("--output", required=True)
    snapshot_parser.add_argument("--file", action="append", required=True)

    verify_parser = subparsers.add_parser("verify-snapshot")
    verify_parser.add_argument("--root", default=".")
    verify_parser.add_argument("--snapshot", required=True)

    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f"repository root is not a directory: {root}")

    try:
        if args.command == "status":
            report = status_report(root)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 2 if has_conflict(report["files"]) or report["transaction"] else 0
        if args.command == "record":
            manifest = record_manifest(root, args.file, args.block_file)
            print(json.dumps({"recorded": len(manifest["managedFiles"])}, indent=2))
            return 0
        if args.command == "migrate":
            manifest = migrate_manifest(root)
            print(json.dumps({"schemaVersion": manifest["schemaVersion"]}, indent=2))
            return 0
        if args.command == "snapshot":
            data = write_snapshot(root, args.output, args.file)
            print(json.dumps({"snapshotted": len(data["files"]), "output": args.output}, indent=2))
            return 0
        report = verify_snapshot(root, args.snapshot)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2 if has_conflict(report["files"]) else 0
    except (OSError, UnicodeError, StateError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
