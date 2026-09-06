#!/usr/bin/env python3
"""Install the Harness generator inside an existing, explicitly selected folder.

Only .agents/skills/harness is owned by this installer. It never configures Git,
the project harness, or a user-level skill location implicitly. An existing
unmanaged, nonempty destination is refused, even when its files match the source.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import stat
import sys
import tempfile
import time


RECEIPT = ".harness-install.json"
COMPONENTS = ("SKILL.md", "scripts", "references", "assets")
IGNORED = {".git", "__pycache__", RECEIPT}


class InstallError(ValueError):
    """A source or destination cannot be installed without losing ownership."""


@dataclass(frozen=True)
class Entry:
    data: bytes | None
    mode: int
    mtime_ns: int


def checked_path(path: Path) -> Path:
    """Check before resolving so symlink and Windows junction hops stay visible."""
    path = Path(os.path.abspath(path.expanduser()))
    for candidate in (*reversed(path.parents), path):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise InstallError(f"symlinks and junctions are not supported: {candidate}")
    return path


def snapshot(folder: Path, *, source: bool = False) -> dict[str, Entry]:
    entries: dict[str, Entry] = {}

    def visit(path: Path) -> None:
        relative = path.relative_to(folder).as_posix()
        if source and (path.name in IGNORED or path.suffix in {".pyc", ".pyo"}):
            return
        checked_path(path)
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            entries[relative] = Entry(None, stat.S_IMODE(info.st_mode), info.st_mtime_ns)
            for child in sorted(path.iterdir()):
                visit(child)
        elif stat.S_ISREG(info.st_mode):
            entries[relative] = Entry(path.read_bytes(), stat.S_IMODE(info.st_mode), info.st_mtime_ns)
        else:
            raise InstallError(f"only regular files and directories are supported: {path}")

    if folder.exists():
        checked_path(folder)
        if not folder.is_dir():
            raise InstallError(f"destination is not a directory: {folder}")
        for name in (COMPONENTS if source else sorted(p.name for p in folder.iterdir())):
            path = folder / name
            if source and not path.exists():
                raise InstallError(f"missing source component: {name}")
            visit(path)
    return entries


def source_version(entries: dict[str, Entry]) -> str:
    entry = entries.get("scripts/harness_metadata.py")
    if entry is None or entry.data is None:
        raise InstallError("source is missing scripts/harness_metadata.py")
    try:
        tree = ast.parse(entry.data.decode("utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "HARNESS_VERSION" for target in node.targets):
                version = ast.literal_eval(node.value)
                if isinstance(version, str) and version:
                    return version
    except (SyntaxError, UnicodeError, ValueError) as exc:
        raise InstallError("invalid source release metadata") from exc
    raise InstallError("source must declare HARNESS_VERSION as a nonempty string")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def managed_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise InstallError("invalid managed path in install receipt")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(part in {".", ".."} for part in path.parts):
        raise InstallError("invalid managed path in install receipt")
    reserved = {"con", "prn", "aux", "nul"} | {f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)}
    for part in path.parts:
        if part.endswith((".", " ")) or any(ord(c) < 32 or c in '<>"|?*' for c in part) or part.split(".", 1)[0].casefold() in reserved:
            raise InstallError("nonportable managed path in install receipt")
    if value != "SKILL.md" and (len(path.parts) < 2 or path.parts[0] not in COMPONENTS[1:]):
        raise InstallError("managed path is outside generator components")
    if any(part in IGNORED for part in path.parts) or path.suffix in {".pyc", ".pyo"}:
        raise InstallError("invalid managed path in install receipt")
    return value


def read_receipt(entries: dict[str, Entry]) -> dict[str, str]:
    entry = entries.get(RECEIPT)
    if entry is None:
        if entries:
            raise InstallError("nonempty unmanaged destination; preserve it and choose an empty destination")
        return {}
    try:
        receipt = json.loads(entry.data)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise InstallError("invalid install receipt") from exc
    if not isinstance(receipt, dict) or set(receipt) != {"schemaVersion", "generatorVersion", "files"}:
        raise InstallError("invalid install receipt fields")
    if type(receipt["schemaVersion"]) is not int or receipt["schemaVersion"] != 1:
        raise InstallError("unsupported install receipt schema")
    if not isinstance(receipt["generatorVersion"], str) or not receipt["generatorVersion"]:
        raise InstallError("invalid installed generator version")
    files = receipt["files"]
    if not isinstance(files, dict) or "SKILL.md" not in files:
        raise InstallError("invalid managed files in install receipt")
    folded: set[str] = set()
    for name, expected in files.items():
        managed_path(name)
        if name.casefold() in folded:
            raise InstallError("case-colliding managed paths in install receipt")
        folded.add(name.casefold())
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise InstallError("invalid file hash in install receipt")
        current = entries.get(name)
        if current is None or current.data is None or digest(current.data) != expected:
            raise InstallError(f"managed file was modified or removed; preserving destination: {name}")
    return files


def populate(folder: Path, entries: dict[str, Entry]) -> None:
    for name, entry in sorted(entries.items(), key=lambda pair: (len(PurePosixPath(pair[0]).parts), pair[0])):
        path = folder / name
        if entry.data is None:
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(entry.data)
            os.chmod(path, entry.mode)
            os.utime(path, ns=(entry.mtime_ns, entry.mtime_ns))
    for name, entry in sorted(entries.items(), reverse=True):
        if entry.data is None:
            os.utime(folder / name, ns=(entry.mtime_ns, entry.mtime_ns))


def replace_folder(destination: Path, old: dict[str, Entry], new: dict[str, Entry]) -> list[str]:
    """Rollback rename failures; leave an explicit backup if cleanup is unavailable."""
    parents: list[Path] = []
    staging: Path | None = None
    backup: Path | None = None
    warnings: list[str] = []
    existed = destination.exists()
    try:
        for parent in reversed(destination.parent.parents):
            checked_path(parent)
        missing: list[Path] = []
        cursor = destination.parent
        while not cursor.exists():
            missing.append(cursor)
            cursor = cursor.parent
        for parent in reversed(missing):
            parent.mkdir()
            parents.append(parent)
        checked_path(destination.parent)
        staging = Path(tempfile.mkdtemp(prefix=".harness-install-stage-", dir=destination.parent))
        populate(staging, new)
        checked_path(destination)
        if destination.exists() != existed or snapshot(destination) != old:
            raise InstallError("destination changed during preparation; install refused")
        if existed:
            backup = destination.parent / (".harness-install-backup-" + secrets.token_hex(12))
            if backup.exists():
                raise InstallError("backup path already exists")
            os.replace(destination, backup)
        try:
            os.replace(staging, destination)
            staging = None
        except OSError:
            if backup is not None:
                try:
                    os.replace(backup, destination)
                    backup = None
                except OSError as exc:
                    raise InstallError(f"install failed; original files retained for recovery at {backup}") from exc
            raise
        if backup is not None:
            try:
                shutil.rmtree(backup)
                backup = None
            except OSError:
                warnings.append(f"installation completed; remove retained backup after review: {backup}")
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
        for parent in reversed(parents):
            try:
                parent.rmdir()
            except OSError:
                pass
    return warnings


def install(root: Path, *, dry_run: bool = False, source: Path | None = None) -> dict:
    root = checked_path(Path(root))
    if any(part.rstrip(" .").casefold() == ".git" for part in root.parts):
        raise InstallError("--root must not be inside Git metadata")
    if not root.is_dir():
        raise InstallError("--root must name an existing directory")
    source = checked_path(source or Path(__file__).absolute().parent / ".agents/skills/harness")
    incoming = snapshot(source, source=True)
    if incoming.get("SKILL.md") is None or incoming["SKILL.md"].data is None:
        raise InstallError("source SKILL.md must be a regular file")
    for name in COMPONENTS[1:]:
        if name not in incoming or incoming[name].data is not None:
            raise InstallError(f"source {name} must be a directory")
    version = source_version(incoming)
    destination = checked_path(root / ".agents/skills/harness")
    report = {"valid": True, "generatorVersion": version, "destination": str(destination), "dryRun": dry_run,
              "writes": 0, "removes": 0, "mode": "unchanged", "gitMetadataTouched": False, "warnings": []}
    if source == destination:
        report["mode"] = "self"
        return report
    if source in destination.parents or destination in source.parents:
        raise InstallError("source and destination must not contain one another")
    old = snapshot(destination)
    managed = read_receipt(old)
    desired = dict(old)
    for name in managed:
        desired.pop(name)
    desired.pop(RECEIPT, None)
    unowned = {name.casefold(): name for name in desired}
    for name, entry in incoming.items():
        previous_name = unowned.get(name.casefold())
        if previous_name is not None and (entry.data is not None or desired[previous_name].data is not None or previous_name != name):
            raise InstallError(f"source conflicts with an unmanaged path: {previous_name}")
        if entry.data is not None:
            managed_path(name)
        # Reusing the destination entry retains file timestamps on safe updates.
        desired[name] = old[name] if name in old and old[name].data == entry.data else entry
    names = [name.casefold() for name in desired]
    if len(names) != len(set(names)):
        raise InstallError("case-colliding source or destination paths")
    files = {name: digest(entry.data) for name, entry in sorted(incoming.items()) if entry.data is not None}
    receipt_data = (json.dumps({"schemaVersion": 1, "generatorVersion": version, "files": files}, indent=2) + "\n").encode("utf-8")
    desired[RECEIPT] = old[RECEIPT] if RECEIPT in old and old[RECEIPT].data == receipt_data else Entry(receipt_data, 0o644, time.time_ns())
    report["writes"] = sum(entry.data is not None and (name not in old or old[name].data != entry.data) for name, entry in desired.items())
    report["removes"] = sum(name not in desired for name in managed)
    if not report["writes"] and not report["removes"]:
        return report
    report["mode"] = "update" if managed else "install"
    if not dry_run:
        report["warnings"] = replace_folder(destination, old, desired)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        report = install(args.root, dry_run=args.dry_run)
    except (InstallError, OSError) as exc:
        print(json.dumps({"valid": False, "dryRun": args.dry_run, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
