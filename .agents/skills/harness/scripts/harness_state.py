#!/usr/bin/env python3
"""Record and verify Harness-managed files and frozen phase snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable


BEGIN_MARKER = "<!-- harness:begin -->"
END_MARKER = "<!-- harness:end -->"
SUPPORTED_RUNTIMES = {"codex", "claude"}


class StateError(ValueError):
    pass


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_inside(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    candidate_rel = Path(relative)
    if candidate_rel.is_absolute():
        raise StateError(f"managed path must be relative: {relative}")
    candidate = (root / candidate_rel).resolve()
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


def validate_runtime(manifest: dict, runtime: str) -> None:
    recorded = manifest.get("generator", {}).get("runtime")
    if recorded != runtime:
        raise StateError(f"manifest runtime is {recorded!r}, expected {runtime!r}")


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


def status_report(root: Path, runtime: str) -> dict:
    _, manifest = load_manifest(root)
    if manifest is None:
        return {"runtime": runtime, "manifest": "missing", "files": [], "counts": {}}
    validate_runtime(manifest, runtime)
    entries = manifest.get("managedFiles", [])
    if not isinstance(entries, list):
        raise StateError("managedFiles must be an array")
    files = [entry_status(root, entry) for entry in entries if isinstance(entry, dict)]
    counts: dict[str, int] = {}
    for item in files:
        counts[item["state"]] = counts.get(item["state"], 0) + 1
    return {"runtime": runtime, "manifest": "present", "files": files, "counts": counts}


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


def record_manifest(root: Path, runtime: str, files: list[str], block_files: list[str]) -> dict:
    manifest_path, manifest = load_manifest(root)
    if manifest is None:
        raise StateError("create .harness/manifest.json from the bundled template before recording files")
    validate_runtime(manifest, runtime)
    manifest["managedFiles"] = build_entries(root, files, block_files)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
    results = [entry_status(root, entry) for entry in data.get("files", [])]
    return {"snapshot": snapshot_path.relative_to(root).as_posix(), "files": results}


def has_conflict(states: Iterable[dict]) -> bool:
    return any(item.get("state") != "unchanged" for item in states)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--root", default=".")
    status_parser.add_argument("--runtime", choices=sorted(SUPPORTED_RUNTIMES), required=True)

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--root", default=".")
    record_parser.add_argument("--runtime", choices=sorted(SUPPORTED_RUNTIMES), required=True)
    record_parser.add_argument("--file", action="append", default=[])
    record_parser.add_argument("--block-file", action="append", default=[])

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
            report = status_report(root, args.runtime)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 2 if has_conflict(report["files"]) else 0
        if args.command == "record":
            manifest = record_manifest(root, args.runtime, args.file, args.block_file)
            print(json.dumps({"recorded": len(manifest["managedFiles"])}, indent=2))
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
