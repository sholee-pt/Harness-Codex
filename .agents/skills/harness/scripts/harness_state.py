#!/usr/bin/env python3
"""Record and verify Codex Harness-managed files and phase snapshots."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import stat
import tempfile
import tomllib
from pathlib import Path, PurePosixPath
from typing import Iterable

import harness_metadata


BEGIN_MARKER = "<!-- harness:begin -->"
END_MARKER = "<!-- harness:end -->"
RUNTIME = harness_metadata.RUNTIME
CURRENT_SCHEMA_VERSION = harness_metadata.MANIFEST_SCHEMA_VERSION
UPGRADE_SOURCE_SCHEMA_VERSION = 4
LOCAL_ONLY_UPGRADE_SOURCE_SCHEMA_VERSION = 5
GENERATOR_VERSION = harness_metadata.HARNESS_VERSION
LEGACY_MIGRATION_GENERATOR_VERSION = "4.0"
TRANSACTION_JOURNAL_RELATIVE = ".harness/transaction.json"
TRANSACTION_SCHEMA_VERSION = harness_metadata.TRANSACTION_SCHEMA_VERSION
MODE_RE = re.compile(r"^0[0-7]{3}$")
DEFAULT_FILE_MODE = 0o644
PROJECT_CONFIG_RELATIVE = ".codex/config.toml"
PROJECT_CONFIG_MAX_BYTES = 1024 * 1024
DEFAULT_INSTRUCTION_CANDIDATES = ("AGENTS.override.md", "AGENTS.md")


class StateError(ValueError):
    pass


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class EvidenceSnapshot:
    """Bounded, single-validation cache for source evidence, never write preconditions."""

    def __init__(self, limit: int = 16 * 1024 * 1024):
        self.limit = limit
        self.size = 0
        self.files: dict[Path, tuple[tuple, bytes, str]] = {}
        self.line_counts: dict[str, int] = {}

    @staticmethod
    def signature(path: Path) -> tuple:
        value = path.stat()
        return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def read(self, path: Path) -> tuple[bytes, str]:
        before = self.signature(path)
        saved = self.files.get(path)
        if saved is not None and saved[0] == before:
            return saved[1], saved[2]
        if saved is not None:
            self.size -= len(saved[1])
            del self.files[path]
        content = path.read_bytes()
        if self.signature(path) != before:
            raise OSError(f"source evidence changed while reading: {path.name}")
        digest = digest_bytes(content)
        if self.size + len(content) <= self.limit:
            self.files[path] = (before, content, digest)
            self.size += len(content)
        return content, digest

    def line_count(self, path: Path) -> int:
        content, digest = self.read(path)
        if digest in self.line_counts:
            return self.line_counts[digest]
        count = len(content.decode("utf-8").splitlines())
        if path in self.files:
            self.line_counts[digest] = count
        return count

    def verify(self) -> None:
        # Metadata is only a fast hint. Re-read before leaving this pass, including
        # same-size edits with restored timestamps. Never reuse this cache on apply.
        for path, (_, content, _) in self.files.items():
            if path.read_bytes() != content:
                raise OSError(f"source evidence changed during validation: {path.name}")


def mode_text(mode: int) -> str:
    if not isinstance(mode, int) or isinstance(mode, bool) or not 0 <= mode <= 0o777:
        raise StateError(f"file mode must contain only permission bits: {mode!r}")
    return f"{mode:04o}"


def parse_mode(value: object, label: str = "file mode") -> int:
    if not isinstance(value, str) or not MODE_RE.fullmatch(value):
        raise StateError(f"{label} must be a four-digit octal string such as '0644'")
    return int(value, 8)


def current_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def mode_matches(path: Path, expected: int) -> bool:
    return os.name == "nt" or current_mode(path) == expected


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


def atomic_write_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None:
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
            if mode is not None and os.name != "nt":
                os.fchmod(temporary.fileno(), mode)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
        temporary_name = None
        sync_directory(path.parent)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str, *, mode: int | None = None) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), mode=mode)


def resolve_inside(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise StateError(f"managed path must use POSIX separators: {relative!r}")
    if any(ord(character) < 32 or ord(character) == 127 for character in relative):
        raise StateError(f"managed path must not contain control characters: {relative!r}")
    candidate_rel = PurePosixPath(relative)
    if (
        candidate_rel.is_absolute()
        or candidate_rel.as_posix() != relative
        or any(part in {".", ".."} for part in candidate_rel.parts)
    ):
        raise StateError(f"managed path must be a normalized relative path: {relative}")
    resolved_root = root.resolve()
    candidate = resolved_root
    for part in candidate_rel.parts:
        candidate = candidate / part
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise StateError(f"managed path uses a symlink or reparse point: {relative}")
    candidate = candidate.resolve()
    if candidate == resolved_root or resolved_root not in candidate.parents:
        raise StateError(f"managed path escapes workspace root: {relative}")
    if must_exist and not candidate.is_file():
        raise StateError(f"managed file is missing: {relative}")
    return candidate


def portable_path_key(relative: str) -> tuple[str, ...]:
    if not isinstance(relative, str) or "\\" in relative:
        raise StateError(f"managed path must use POSIX separators: {relative!r}")
    if any(ord(character) < 32 or ord(character) == 127 for character in relative):
        raise StateError(f"managed path must not contain control characters: {relative!r}")
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or path.as_posix() != relative
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise StateError(f"managed path must be a normalized relative path: {relative}")
    return tuple(part.casefold() for part in path.parts)


def validate_evidence_relative(relative: str) -> tuple[str, ...]:
    """Reject control metadata before an evidence path is resolved or read."""
    key = portable_path_key(relative)
    if key and (".git" in key or key[0] == ".harness"):
        raise StateError(
            f"evidence path uses a reserved control namespace: {relative}"
        )
    return key


def resolve_lexical_regular_inside(
    root: Path,
    relative: str,
    *,
    must_exist: bool = False,
    label: str = "file",
) -> tuple[Path, bool]:
    """Resolve a regular file without following lexical symlink/reparse components."""
    key = portable_path_key(relative)
    original_parts = PurePosixPath(relative).parts
    if len(key) != len(original_parts):
        raise StateError(f"{label} path is not portable: {relative}")
    resolved_root = root.resolve()
    candidate = resolved_root
    exists = True
    for index, part in enumerate(original_parts):
        candidate = candidate / part
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            exists = False
            continue
        except OSError as exc:
            raise StateError(f"could not inspect {label} path: {relative}") from exc
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(metadata.st_mode) or (
            reparse_flag and attributes & reparse_flag
        ):
            raise StateError(
                f"{label} path uses a symlink or reparse point: {relative}"
            )
        if index < len(original_parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise StateError(f"{label} path has a non-directory ancestor: {relative}")
        if index == len(original_parts) - 1 and not stat.S_ISREG(metadata.st_mode):
            raise StateError(f"{label} path is not a regular file: {relative}")
    resolved = resolve_inside(resolved_root, relative)
    present = exists and resolved.exists()
    if must_exist and not present:
        raise StateError(f"{label} path does not exist: {relative}")
    return resolved, present


def project_instruction_candidates(root: Path) -> list[str]:
    """Return root instruction candidates in Codex precedence order."""
    candidates = list(DEFAULT_INSTRUCTION_CANDIDATES)
    config_path = root / PROJECT_CONFIG_RELATIVE
    if config_path.exists() or config_path.is_symlink():
        path, present = resolve_lexical_regular_inside(
            root,
            PROJECT_CONFIG_RELATIVE,
            must_exist=True,
            label="project Codex config",
        )
        if not present:
            raise StateError("project Codex config is missing")
        try:
            config_bytes = path.read_bytes()
            if len(config_bytes) > PROJECT_CONFIG_MAX_BYTES:
                raise StateError("project Codex config exceeds the size limit")
            config = tomllib.loads(config_bytes.decode("utf-8"))
        except StateError:
            raise
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise StateError(f"invalid project Codex config: {exc}") from exc
        fallbacks = config.get("project_doc_fallback_filenames", [])
        if not isinstance(fallbacks, list) or any(
            not isinstance(value, str) for value in fallbacks
        ):
            raise StateError(
                "project_doc_fallback_filenames must be an array of filenames"
            )
        for fallback in fallbacks:
            key = portable_path_key(fallback)
            if len(key) != 1:
                raise StateError(
                    "project_doc_fallback_filenames entries must be root filenames"
                )
            if key not in {portable_path_key(value) for value in candidates}:
                candidates.append(fallback)
    return candidates


def validate_file_namespace(paths: Iterable[str], *, label: str = "managed paths") -> None:
    entries: list[tuple[str, tuple[str, ...]]] = []
    for relative in paths:
        key = portable_path_key(relative)
        for previous, previous_key in entries:
            if key == previous_key:
                raise StateError(
                    f"{label} contains a portable path collision: {previous!r} and {relative!r}"
                )
            if (
                len(previous_key) < len(key)
                and key[: len(previous_key)] == previous_key
            ) or (
                len(key) < len(previous_key)
                and previous_key[: len(key)] == key
            ):
                raise StateError(
                    f"{label} contains a file/child path conflict: {previous!r} and {relative!r}"
                )
        entries.append((relative, key))


def normalize_relative(root: Path, value: str) -> str:
    path = resolve_inside(root, value, must_exist=True)
    return path.relative_to(root.resolve()).as_posix()


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
    path = resolve_inside(root, ".harness/manifest.json")
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
    """Return the root instruction file Codex will prefer or safely preserve."""
    candidates = project_instruction_candidates(root)
    first_existing: str | None = None
    for relative in candidates:
        path, present = resolve_lexical_regular_inside(
            root, relative, label="project instruction"
        )
        if not present:
            continue
        if first_existing is None:
            first_existing = relative
        try:
            if path.read_text(encoding="utf-8").strip():
                return relative
        except (OSError, UnicodeError) as exc:
            raise StateError(f"project instruction is not UTF-8: {relative}") from exc
    return first_existing or "AGENTS.md"


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
        expected_mode = entry.get("mode")
        if kind == "file" and expected_mode is not None:
            parsed_mode = parse_mode(expected_mode, f"managed mode for {relative}")
            if not mode_matches(path, parsed_mode):
                return {
                    "path": relative,
                    "kind": kind,
                    "state": "modified-mode",
                    "sha256": actual,
                    "mode": mode_text(current_mode(path)),
                }
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
    managed_paths = [
        entry.get("path")
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    ]
    validate_file_namespace(managed_paths, label="manifest managedFiles")
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
    files = list(files)
    block_files = list(block_files)
    validate_file_namespace([*files, *block_files], label="managed files")
    entries: list[dict] = []
    seen: set[str] = set()
    for kind, values in (("file", files), ("managed-block", block_files)):
        for value in values:
            relative = normalize_relative(root, value)
            if relative in seen:
                raise StateError(f"duplicate managed path: {relative}")
            seen.add(relative)
            path = resolve_inside(root, relative, must_exist=True)
            entry = {
                "path": relative,
                "kind": kind,
                "sha256": digest_bytes(content_for_entry(path, kind)),
            }
            if kind == "file":
                entry["mode"] = mode_text(current_mode(path))
            entries.append(entry)
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
    atomic_write_text(
        manifest_path,
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        mode=current_mode(manifest_path),
    )
    return manifest


def migrate_manifest(root: Path) -> dict:
    if transaction_status(root) is not None:
        raise StateError("cannot migrate while a Harness transaction journal exists; recover it first")
    manifest_path, manifest = load_manifest(root)
    if manifest is None:
        raise StateError("missing .harness/manifest.json")
    validate_runtime(manifest)
    version = manifest.get("schemaVersion")
    if version in {
        UPGRADE_SOURCE_SCHEMA_VERSION,
        LOCAL_ONLY_UPGRADE_SOURCE_SCHEMA_VERSION,
        CURRENT_SCHEMA_VERSION,
        harness_metadata.PREVIOUS_MANIFEST_SCHEMA_VERSION,
    }:
        return manifest
    if version not in {1, 2, 3}:
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

    def migrate_evidence(values: object, label: str) -> list[dict]:
        if not isinstance(values, list) or not values:
            raise StateError(f"{label} must contain evidence before schema 4 preparation")
        migrated: list[dict] = []
        for index, value in enumerate(values):
            if not isinstance(value, str) or not value.strip():
                raise StateError(f"{label}[{index}] is not a legacy file path")
            path = resolve_inside(root, value)
            if not path.is_file():
                raise StateError(f"{label}[{index}] does not exist: {value}")
            migrated.append(
                {
                    "path": value,
                    "sha256": digest_bytes(path.read_bytes()),
                    "claim": "Migrated from a legacy evidence path; review semantic support.",
                }
            )
        return migrated

    project = manifest.get("project")
    if not isinstance(project, dict):
        raise StateError("manifest project must be an object")
    project["evidence"] = migrate_evidence(project.get("evidence"), "project.evidence")
    topology = manifest.get("topology")
    if not isinstance(topology, dict):
        raise StateError("manifest topology must be an object")
    for kind in ("skills", "agents"):
        items = topology.get(kind)
        if not isinstance(items, list):
            raise StateError(f"manifest topology.{kind} must be an array")
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise StateError(f"manifest topology.{kind}[{index}] must be an object")
            item["evidence"] = migrate_evidence(
                item.get("evidence"), f"topology.{kind}[{index}].evidence"
            )

    managed_files = manifest.get("managedFiles")
    if not isinstance(managed_files, list):
        raise StateError("manifest managedFiles must be an array")
    for entry in managed_files:
        if not isinstance(entry, dict) or entry.get("kind", "file") != "file":
            continue
        relative = entry.get("path")
        if not isinstance(relative, str):
            raise StateError("managed file path must be text")
        path = resolve_inside(root, relative, must_exist=True)
        entry["mode"] = mode_text(current_mode(path))

    generator = manifest.get("generator")
    if not isinstance(generator, dict):
        raise StateError("manifest generator must be an object")
    generator["version"] = LEGACY_MIGRATION_GENERATOR_VERSION
    manifest["schemaVersion"] = UPGRADE_SOURCE_SCHEMA_VERSION
    manifest["application"] = {
        "mode": "journaled",
        "transactionSchemaVersion": TRANSACTION_SCHEMA_VERSION,
    }
    atomic_write_text(
        manifest_path,
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        mode=current_mode(manifest_path),
    )
    return manifest


def snapshot_data(root: Path, files: list[str]) -> dict:
    entries = build_entries(root, files, [])
    return {"schemaVersion": 1, "files": entries}


def evidence_data(root: Path, paths: list[str]) -> dict:
    records: list[dict] = []
    seen: set[str] = set()
    for value in paths:
        relative = normalize_relative(root, value)
        if relative in seen:
            raise StateError(f"duplicate evidence path: {relative}")
        seen.add(relative)
        path = resolve_inside(root, relative, must_exist=True)
        records.append({"path": relative, "sha256": digest_bytes(path.read_bytes())})
    return {"schemaVersion": 1, "evidence": records}


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
    return {"snapshot": snapshot_path.relative_to(root.resolve()).as_posix(), "files": results}


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

    evidence_parser = subparsers.add_parser("evidence")
    evidence_parser.add_argument("--root", default=".")
    evidence_parser.add_argument("--path", action="append", required=True)

    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f"workspace root is not a directory: {root}")

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
        if args.command == "evidence":
            data = evidence_data(root, args.path)
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return 0
        report = verify_snapshot(root, args.snapshot)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2 if has_conflict(report["files"]) else 0
    except (OSError, UnicodeError, StateError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
