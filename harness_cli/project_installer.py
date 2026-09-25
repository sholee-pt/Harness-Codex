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
import importlib.util
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
GENERATOR_ENTRYPOINTS = frozenset({"inventory", "harness_state", "harness_plan_builder", "harness_apply", "validate_harness", "harness_doctor", "harness_metadata"})


class InstallError(ValueError):
    """A source or destination cannot be installed without losing ownership."""


@dataclass(frozen=True)
class Entry:
    data: bytes | None
    mode: int
    mtime_ns: int


@dataclass(frozen=True)
class DirectoryState:
    mode: int
    mtime_ns: int
    ctime_ns: int
    device: int
    inode: int


def directory_state(folder: Path) -> DirectoryState | None:
    checked_path(folder)
    try:
        info = folder.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(info.st_mode):
        raise InstallError(f"destination is not a directory: {folder}")
    return DirectoryState(stat.S_IMODE(info.st_mode), info.st_mtime_ns,
                          info.st_ctime_ns, info.st_dev, info.st_ino)


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


def validate_generator_source(files: dict[str, bytes], version: str) -> None:
    """Check generator entrypoints and local imports without executing source."""
    from harness_cli.versions import version_key

    try:
        current = version_key(version) >= version_key("0.22.2-beta")
    except ValueError as exc:
        raise InstallError("invalid generator release version") from exc
    required = set(GENERATOR_ENTRYPOINTS) if current else set()
    modules = {Path(name).stem for name in files if name.startswith("scripts/") and name.endswith(".py")}
    local_names = modules | GENERATOR_ENTRYPOINTS | {"validate_runtime_plan", "validate_coordination_packet", "evaluate_topology"}
    for name, data in files.items():
        if not name.startswith("scripts/") or not name.endswith(".py"):
            continue
        try:
            tree = ast.parse(data, name)
            compile(tree, name, "exec")
        except (SyntaxError, UnicodeError, ValueError) as exc:
            raise InstallError(f"invalid generator Python source: {name}") from exc
        for node in ast.walk(tree):
            imports = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for module in imports:
                module = module.split(".", 1)[0]
                if module in local_names or module.startswith("harness_"):
                    required.add(module)
    missing = sorted(f"scripts/{module}.py" for module in required if f"scripts/{module}.py" not in files)
    if missing:
        raise InstallError("source is missing required generator modules: " + ", ".join(missing))


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
            # Final restrictive modes are applied after all children are written.
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name == "posix":
                os.chmod(path, 0o700)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(entry.data)
            os.chmod(path, entry.mode)
            os.utime(path, ns=(entry.mtime_ns, entry.mtime_ns))
    for name, entry in sorted(entries.items(), key=lambda pair: len(PurePosixPath(pair[0]).parts), reverse=True):
        if entry.data is None:
            os.utime(folder / name, ns=(entry.mtime_ns, entry.mtime_ns))
            if os.name == "posix":
                os.chmod(folder / name, entry.mode)


def remove_prepared_tree(folder: Path) -> None:
    """Remove only an installer-created staging tree or a committed backup."""
    if os.name == "posix":
        def make_removable(path: Path) -> None:
            checked_path(path)
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                os.chmod(path, stat.S_IMODE(info.st_mode) | 0o700)
                for child in path.iterdir():
                    make_removable(child)
        # No target directory is passed here before a successful promotion.
        make_removable(folder)
    shutil.rmtree(folder)


def replace_folder(destination: Path, old: dict[str, Entry], new: dict[str, Entry],
                   old_root: DirectoryState | None, desired_root: DirectoryState) -> list[str]:
    """Rollback rename failures; leave an explicit backup if cleanup is unavailable."""
    parents: list[Path] = []
    staging: Path | None = None
    backup: Path | None = None
    warnings: list[str] = []
    existed = old_root is not None
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
        if os.name == "posix":
            os.chmod(staging, 0o700)
        populate(staging, new)
        os.utime(staging, ns=(desired_root.mtime_ns, desired_root.mtime_ns))
        if os.name == "posix":
            os.chmod(staging, desired_root.mode)
        checked_path(destination)
        if (directory_state(destination) != old_root or snapshot(destination) != old
                or directory_state(destination) != old_root):
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
                remove_prepared_tree(backup)
                backup = None
            except OSError:
                warnings.append(f"installation completed; remove retained backup after review: {backup}")
    finally:
        if staging is not None and staging.exists():
            remove_prepared_tree(staging)
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
    source = checked_path(source or Path(__file__).absolute().parents[1] / ".agents/skills/harness")
    source_root = directory_state(source)
    if source_root is None:
        raise InstallError("source must be an existing directory")
    incoming = snapshot(source, source=True)
    if incoming.get("SKILL.md") is None or incoming["SKILL.md"].data is None:
        raise InstallError("source SKILL.md must be a regular file")
    for name in COMPONENTS[1:]:
        if name not in incoming or incoming[name].data is not None:
            raise InstallError(f"source {name} must be a directory")
    version = source_version(incoming)
    validate_generator_source({name: entry.data for name, entry in incoming.items() if entry.data is not None}, version)
    destination = checked_path(root / ".agents/skills/harness")
    report = {"valid": True, "generatorVersion": version, "destination": str(destination), "dryRun": dry_run,
              "writes": 0, "removes": 0, "directoriesCreated": 0,
              "mode": "unchanged", "gitMetadataTouched": False, "warnings": []}
    if source == destination:
        report["mode"] = "self"
        return report
    if source in destination.parents or destination in source.parents:
        raise InstallError("source and destination must not contain one another")
    old_root = directory_state(destination)
    old = snapshot(destination)
    if directory_state(destination) != old_root:
        raise InstallError("destination changed during preparation; install refused")
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
    report["directoriesCreated"] = sum(entry.data is None and name not in old for name, entry in desired.items())
    if not report["writes"] and not report["removes"] and not report["directoriesCreated"]:
        return report
    report["mode"] = "update" if managed else "install"
    if not dry_run:
        report["warnings"] = replace_folder(destination, old, desired, old_root, old_root or source_root)
    return report


def load_installer(source_root: Path):
    """Load the selected release's installer without reusing another release's module."""
    path = checked_path(Path(source_root) / "harness_cli/project_installer.py")
    name = "_harness_project_installer_" + digest(str(path).encode("utf-8"))[:16]
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise InstallError("The project installer is unavailable; reinstall the tool.")
    module = importlib.util.module_from_spec(specification)
    previous = sys.modules.get(name)
    sys.modules[name] = module  # dataclass resolves its defining module during import.
    try:
        # Immutable releases must not acquire bytecode files during a read-only
        # preflight, even when a caller did not start Python with -B.
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    except BaseException:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        raise
    return module


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
