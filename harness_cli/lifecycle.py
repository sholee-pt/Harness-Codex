"""Remove only proved Harness-owned files, with a separate recoverable journal.

Removal Schema 1 deliberately is not the generator's Transaction Schema 2.
Its seal detects local journal corruption; it is not an authorization signature.
Recovery trusts the validated local operation plan and checks every surviving
original/backup before restoring anything, as the generator's transaction does.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import errno
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

from .project_installer import load_installer


JOURNAL = ".harness/transaction.json"
WORKSPACES = ".harness/removals"
GENERATOR = ".agents/skills/harness"
STATES = {"remove-preparing", "remove-applying", "remove-recovery-required", "remove-committed", "remove-rolled-back"}


class LifecycleError(ValueError):
    """Ownership or recovery cannot be established without risking user content."""


@dataclass(frozen=True)
class FileState:
    data: bytes
    mode: int
    mtime_ns: int

    def metadata(self) -> dict:
        return {"sha256": hashlib.sha256(self.data).hexdigest(), "size": len(self.data),
                "mode": self.mode, "mtimeNs": self.mtime_ns}


def _helpers(source_root: Path):
    source_root = Path(source_root).absolute()
    installer = load_installer(source_root)
    scripts = installer.checked_path(source_root / ".agents/skills/harness/scripts")
    sys.path.insert(0, str(scripts))
    try:
        modules = [importlib.import_module(name) for name in
                   ("harness_apply", "harness_state", "harness_metadata", "harness_transaction")]
        if any(Path(module.__file__).resolve().parent != scripts.resolve() for module in modules):
            raise LifecycleError("Another Harness helper version is already loaded; start a fresh Harness command.")
    finally:
        sys.path.remove(str(scripts))
    return installer, *modules


def _root(value: Path, installer) -> Path:
    from .paths import project_root
    return project_root(value, error_type=LifecycleError)


def _file(path: Path, installer) -> FileState | None:
    installer.checked_path(path)
    try:
        before = path.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(before.st_mode):
        raise LifecycleError(f"Expected a regular file: {path.name}")
    if stat.S_IMODE(before.st_mode) & 0o7000:
        raise LifecycleError(f"Special file permissions require manual review: {path.name}")
    data = path.read_bytes()
    after = path.stat()
    if (before.st_ino, before.st_dev, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise LifecycleError("A file changed while removal was being prepared.")
    return FileState(data, stat.S_IMODE(after.st_mode), after.st_mtime_ns)


def _same(actual: FileState | None, expected: dict | None) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    value = actual.metadata()
    return (value["sha256"] == expected["sha256"] and value["size"] == expected["size"]
            and (os.name == "nt" or value["mode"] == expected["mode"])
            and value["mtimeNs"] == expected["mtimeNs"])


def _seal(journal: dict) -> dict:
    value = {key: item for key, item in journal.items() if key != "seal"}
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**value, "seal": digest}


def _allowed(operation: dict, installer, transaction) -> bool:
    path, kind = operation.get("path"), operation.get("kind")
    if not isinstance(path, str):
        return False
    if kind == "manifest":
        return path == ".harness/manifest.json"
    if kind == 'guide':
        return path == '.harness/GUIDE.md'
    if kind == 'workspace-context':
        return path == '.harness/context.json'
    if kind == "managed-block":
        return path in {"AGENTS.md", "AGENTS.override.md"}
    if kind == "generator-receipt":
        return path == f"{GENERATOR}/{installer.RECEIPT}"
    if kind == "generator-file":
        if not path.startswith(GENERATOR + "/"):
            return False
        try:
            installer.managed_path(path[len(GENERATOR) + 1:])
            return True
        except ValueError:
            return False
    return (kind == "file" and transaction.is_allowed_target(path)
            and path not in {"AGENTS.md", "AGENTS.override.md", ".harness/manifest.json"})


def _validate_metadata(value: dict) -> bool:
    return (isinstance(value, dict) and set(value) == {"sha256", "size", "mode", "mtimeNs"}
            and isinstance(value["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is not None
            and type(value["size"]) is int and value["size"] >= 0
            and type(value["mode"]) is int and 0 <= value["mode"] <= 0o777
            and type(value["mtimeNs"]) is int and value["mtimeNs"] >= 0)


def _load_journal(root: Path, helpers) -> dict | None:
    installer, _, state, _, transaction = helpers
    current = _file(root / JOURNAL, installer)
    if current is None:
        return None
    try:
        value = json.loads(current.data)
    except (ValueError, UnicodeError) as exc:
        raise LifecycleError("The removal journal is invalid; all files have been preserved.") from exc
    fields = {"operation", "removalSchemaVersion", "runtime", "id", "state", "createdHarnessDirectory", "operations", "seal"}
    if (not isinstance(value, dict) or set(value) != fields or value.get("operation") != "remove"
            or type(value.get("removalSchemaVersion")) is not int or value["removalSchemaVersion"] != 1
            or value.get("runtime") != "codex" or not isinstance(value.get("state"), str) or value["state"] not in STATES
            or not isinstance(value.get("id"), str) or re.fullmatch(r"[0-9a-f]{32}", value["id"]) is None
            or type(value.get("createdHarnessDirectory")) is not bool
            or not isinstance(value.get("operations"), list) or not value["operations"]
            or _seal(value) != value):
        raise LifecycleError("This is not a valid CLI removal journal. Existing application transactions must use their own recovery tool.")
    paths = []
    for operation in value["operations"]:
        if (not isinstance(operation, dict) or set(operation) != {"path", "kind", "before", "after"}
                or not _allowed(operation, installer, transaction) or not _validate_metadata(operation["before"])
                or (operation["after"] is not None and
                    (operation["kind"] != "managed-block" or not _validate_metadata(operation["after"])))):
            raise LifecycleError("The removal journal contains an unsupported file operation.")
        paths.append(operation["path"])
        installer.checked_path(root / operation["path"])
    state.validate_file_namespace(paths, label="removal operations")
    installer.checked_path(root / WORKSPACES / value["id"])
    return value


def _write_journal(root: Path, journal: dict, helpers, *, create=False) -> None:
    installer, _, state, _, _ = helpers
    path = installer.checked_path(root / JOURNAL)
    payload = (json.dumps(journal, sort_keys=True, indent=2) + "\n").encode()
    if create:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            path.chmod(0o600)
        state.sync_directory(path.parent)
    else:
        current = _load_journal(root, helpers)
        if current is None or current["id"] != journal["id"]:
            raise LifecycleError("The removal journal changed during the operation.")
        state.atomic_write_bytes(path, payload, mode=0o600)


def _set_state(root: Path, journal: dict, value: str, helpers) -> dict:
    updated = _seal({**journal, "state": value})
    _write_journal(root, updated, helpers)
    return updated


def _workspace(root: Path, journal: dict) -> Path:
    return root / WORKSPACES / journal["id"]


def _backup(root: Path, journal: dict, index: int) -> Path:
    return _workspace(root, journal) / f"backup-{index:06d}"


def _staged(root: Path, journal: dict, index: int) -> Path:
    return _workspace(root, journal) / f"staged-{index:06d}"


def _recovery_states(root: Path, journal: dict, helpers, *, committed: bool) -> list:
    installer = helpers[0]
    workspace = _workspace(root, journal)
    installer.checked_path(workspace)
    known = {f"{prefix}-{index:06d}" for index in range(len(journal["operations"])) for prefix in ("backup", "staged")}
    if workspace.exists() and (not workspace.is_dir() or any(path.name not in known for path in workspace.iterdir())):
        raise LifecycleError("The removal backup directory contains unrecognized content; preserving it.")
    results = []
    for index, operation in enumerate(journal["operations"]):
        original = _file(root / operation["path"], installer)
        backup = _file(_backup(root, journal, index), installer)
        staged = _file(_staged(root, journal, index), installer)
        if backup is not None and not _same(backup, operation["before"]):
            raise LifecycleError("A removal backup changed; recovery cannot overwrite any files.")
        if staged is not None and not _same(staged, operation["after"]):
            raise LifecycleError("A staged removal replacement changed; recovery cannot overwrite any files.")
        if committed:
            if not _same(original, operation["after"]):
                raise LifecycleError("A file changed after removal committed; backup cleanup requires review.")
        elif backup is None:
            if not _same(original, operation["before"]):
                raise LifecycleError("An original file or required backup is missing or changed; recovery requires review.")
        elif original is not None and not _same(original, operation["after"]):
            raise LifecycleError("A file changed during removal; recovery will not overwrite the new content.")
        results.append((original, backup, staged))
    return results


def _cleanup(root: Path, journal: dict, helpers) -> None:
    installer, _, state, _, _ = helpers
    _recovery_states(root, journal, helpers, committed=journal["state"] == "remove-committed")
    workspace = _workspace(root, journal)
    for index, operation in enumerate(journal["operations"]):
        for path, expected in ((_backup(root, journal, index), operation["before"]),
                               (_staged(root, journal, index), operation["after"])):
            current = _file(path, installer)
            if current is not None:
                if not _same(current, expected):
                    raise LifecycleError("Removal backup changed before cleanup.")
                path.unlink()
    if workspace.exists():
        state.sync_directory(workspace)
        workspace.rmdir()
        state.sync_directory(workspace.parent)
    base = root / WORKSPACES
    if base.exists():
        state.sync_directory(base)
        base.rmdir()
        state.sync_directory(base.parent)
    if journal["state"] == "remove-committed":
        # Empty receipt-owned component parents must not obstruct a later install.
        # rmdir never removes unlisted files or nonempty user directories.
        generator = root / GENERATOR
        candidates = set()
        for operation in journal["operations"]:
            if operation["kind"] in {"generator-file", "generator-receipt"}:
                parent = (root / operation["path"]).parent
                while parent == generator or generator in parent.parents:
                    candidates.add(parent)
                    parent = parent.parent
        for path in sorted(candidates, key=lambda item: len(item.parts), reverse=True):
            installer.checked_path(path)
            try:
                path.rmdir()
                state.sync_directory(path.parent)
            except OSError as exc:
                if exc.errno not in {errno.ENOTEMPTY, errno.EEXIST, errno.ENOENT}:
                    raise
    current = _load_journal(root, helpers)
    if current is None or current["id"] != journal["id"]:
        raise LifecycleError("The removal journal changed before cleanup.")
    (root / JOURNAL).unlink()
    state.sync_directory(root / ".harness")
    if journal["createdHarnessDirectory"]:
        try:
            (root / ".harness").rmdir()
            state.sync_directory(root)
        except OSError:
            pass


def _rollback(root: Path, journal: dict, helpers) -> None:
    installer, _, state, _, _ = helpers
    snapshots = _recovery_states(root, journal, helpers, committed=False)
    for index in reversed(range(len(journal["operations"]))):
        operation = journal["operations"][index]
        original, backup, _ = snapshots[index]
        if backup is None:
            continue
        path = root / operation["path"]
        if not _same(_file(path, installer), operation["after"] if original is not None else None):
            raise LifecycleError("A file changed immediately before rollback; retaining its backup.")
        # Replace the known replacement (or absent path) with its original inode.
        os.replace(_backup(root, journal, index), path)
        state.sync_directory(path.parent)
        state.sync_directory(_workspace(root, journal))
    journal = _set_state(root, journal, "remove-rolled-back", helpers)
    _cleanup(root, journal, helpers)


def _plan(root: Path, include_generator: bool, helpers) -> tuple[dict, list, list]:
    installer, application, state, metadata, transaction = helpers
    for relative in (JOURNAL, ".harness/transactions", WORKSPACES):
        installer.checked_path(root / relative)
    if state.transaction_status(root) is not None or (root / WORKSPACES).exists():
        raise LifecycleError("A pending or orphaned Harness transaction must be recovered before removal.")
    operations, snapshots, replacements = [], [], []

    def add(relative: str, kind: str, replacement: bytes | None = None, *, expected=None, entry=None):
        current = _file(root / relative, installer)
        if current is None:
            raise LifecycleError(f"Owned file is missing: {relative}")
        if expected is not None and current != expected:
            raise LifecycleError(f"Owned file changed during preparation: {relative}")
        if entry is not None:
            owned = current.data
            if kind == "managed-block":
                owned = state.extract_managed_block(owned.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")).encode("utf-8")
            if hashlib.sha256(owned).hexdigest() != entry["sha256"]:
                raise LifecycleError(f"Managed file changed during preparation: {relative}")
            if (kind == "file" and os.name != "nt" and entry.get("mode") is not None
                    and current.mode != state.parse_mode(entry["mode"], "managed mode")):
                raise LifecycleError(f"Managed file mode changed during preparation: {relative}")
        after = None if replacement is None else FileState(replacement, current.mode, current.mtime_ns)
        operation = {"path": relative, "kind": kind, "before": current.metadata(),
                     "after": None if after is None else after.metadata()}
        if not _allowed(operation, installer, transaction):
            raise LifecycleError("A manifest claims a path outside supported removal ownership.")
        operations.append(operation)
        snapshots.append(current)
        replacements.append(after)

    manifest_snapshot = _file(root / ".harness/manifest.json", installer)
    manifest = None
    pointers = []
    if manifest_snapshot is not None:
        try:
            raw = json.loads(manifest_snapshot.data)
            if (not isinstance(raw, dict) or raw.get("schemaVersion") != metadata.MANIFEST_SCHEMA_VERSION
                    or metadata.artifact_contract_state(raw) != "current"):
                raise LifecycleError("Removal supports only compatible project-local v9 installations.")
            manifest, managed = application.existing_manifest_state(root)
        except (OSError, ValueError) as exc:
            raise LifecycleError(f"The generated harness ownership is invalid: {exc}") from exc
        for relative, entry in sorted(managed.items()):
            if entry.get("kind", "file") == "managed-block":
                current = _file(root / relative, installer)
                begin, end = state.BEGIN_MARKER.encode(), state.END_MARKER.encode()
                if current is None or current.data.count(begin) != 1 or current.data.count(end) != 1:
                    raise LifecycleError("The root instruction block is ambiguous.")
                start = current.data.index(begin)
                finish = current.data.index(end, start) + len(end)
                pointers.append((relative, current.data[:start] + current.data[finish:], current, entry))
            else:
                add(relative, "file", entry=entry)
    elif (root / ".agents/skills/project-harness/SKILL.md").exists():
        raise LifecycleError("Project-harness files exist without an ownership manifest; preserving them.")
    retained_generator_files = []
    if include_generator:
        destination = installer.checked_path(root / GENERATOR)
        entries = installer.snapshot(destination)
        managed = installer.read_receipt(entries)
        if managed:
            receipt = json.loads(entries[installer.RECEIPT].data)
            if (receipt["generatorVersion"] not in metadata.ARTIFACT_COMPATIBLE_GENERATOR_VERSIONS
                    or installer.source_version(entries) != receipt["generatorVersion"]):
                raise LifecycleError("The installed generator receipt has an unsupported or inconsistent version.")
            for relative in sorted(managed):
                old = entries[relative]
                add(f"{GENERATOR}/{relative}", "generator-file", expected=FileState(old.data, old.mode, old.mtime_ns))
            old = entries[installer.RECEIPT]
            add(f"{GENERATOR}/{installer.RECEIPT}", "generator-receipt", expected=FileState(old.data, old.mode, old.mtime_ns))
            retained_generator_files = sorted(name for name, item in entries.items()
                                              if item.data is not None and name not in managed and name != installer.RECEIPT)
    for relative, replacement, current, entry in pointers:
        add(relative, "managed-block", replacement, expected=current, entry=entry)
    from .project_guide import owned as owns_guide
    try:
        guide_owned = owns_guide(root)
    except (OSError, ValueError):
        guide_owned = False
    if guide_owned:
        add('.harness/GUIDE.md', 'guide')
    from .workspace_context import owned as owns_context
    try:
        context_owned = owns_context(root)
    except (OSError, ValueError):
        context_owned = False
    if context_owned:
        add('.harness/context.json', 'workspace-context')
    if manifest is not None:
        add(".harness/manifest.json", "manifest")
        if snapshots[-1] != manifest_snapshot:
            raise LifecycleError("The ownership manifest changed during removal preparation.")
    state.validate_file_namespace([item["path"] for item in operations], label="removal operations")
    report = {"valid": True, "state": "preview" if operations else "unchanged", "dryRun": True,
              "generatedHarnessPresent": manifest is not None, "includeGenerator": include_generator,
              "actions": [{"path": item["path"], "action": "remove-managed-block" if item["after"] is not None else "remove-file"}
                          for item in operations], "writes": 0, "gitMetadataTouched": False,
              "emptyProjectDirectoriesRetained": True, "retainedGeneratorFiles": retained_generator_files}
    report['planDigest'] = hashlib.sha256(json.dumps(operations, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if retained_generator_files:
        report["warning"] = "Unlisted generator files are preserved. Move them out of the reserved generator directory before reinstalling."
    return report, operations, replacements


def _serialized(function):
    @wraps(function)
    def locked(root, *, source_root, **kwargs):
        if kwargs.get('dry_run', True):
            return function(root, source_root=source_root, **kwargs)
        helpers = _helpers(source_root)
        root = _root(root, helpers[0])
        with helpers[-1].project_lock(root):
            return function(root, source_root=source_root, **kwargs)
    return locked


@_serialized
def remove_project(root: Path, *, source_root: Path, include_generator: bool = False, dry_run: bool = True, expected_plan: str | None = None) -> dict:
    """Preview by default; callers require explicit --yes before dry_run=False."""
    helpers = _helpers(source_root)
    installer, _, state, _, _ = helpers
    root = _root(root, installer)
    report, operations, replacements = _plan(root, include_generator, helpers)
    if expected_plan is not None and report['planDigest'] != expected_plan:
        raise LifecycleError('Removal files changed after the preview; review a fresh removal plan before confirming.')
    report["dryRun"] = dry_run
    if dry_run or not operations:
        return report
    harness_directory = root / ".harness"
    created = not harness_directory.exists()
    harness_directory.mkdir(exist_ok=True)
    journal = _seal({"operation": "remove", "removalSchemaVersion": 1, "runtime": "codex",
                     "id": uuid.uuid4().hex, "state": "remove-preparing", "createdHarnessDirectory": created,
                     "operations": operations})
    try:
        _write_journal(root, journal, helpers, create=True)
    except BaseException:
        if created:
            try:
                harness_directory.rmdir()
            except OSError:
                pass
        raise
    try:
        workspace = _workspace(root, journal)
        (root / WORKSPACES).mkdir(mode=0o700)
        workspace.mkdir(mode=0o700)
        state.sync_directory(root / ".harness")
        state.sync_directory(root / WORKSPACES)
        for index, replacement in enumerate(replacements):
            if replacement is not None:
                path = _staged(root, journal, index)
                state.atomic_write_bytes(path, replacement.data, mode=replacement.mode)
                os.utime(path, ns=(replacement.mtime_ns, replacement.mtime_ns))
        for operation in operations:
            if not _same(_file(root / operation["path"], installer), operation["before"]):
                raise LifecycleError("An owned file changed after preview; removal was refused.")
        journal = _set_state(root, journal, "remove-applying", helpers)
        for index, operation in enumerate(operations):
            original = root / operation["path"]
            if not _same(_file(original, installer), operation["before"]):
                raise LifecycleError("An owned file changed during removal; restoring earlier files.")
            installer.checked_path(_backup(root, journal, index))
            os.replace(original, _backup(root, journal, index))
            state.sync_directory(workspace)
            if operation["after"] is not None:
                os.replace(_staged(root, journal, index), original)
            state.sync_directory(original.parent)
        _recovery_states(root, journal, helpers, committed=True)
        journal = _set_state(root, journal, "remove-committed", helpers)
    except BaseException as exc:
        try:
            _rollback(root, journal, helpers)
        except BaseException as recovery_error:
            try:
                _set_state(root, journal, "remove-recovery-required", helpers)
            except BaseException:
                pass
            raise LifecycleError("Removal was interrupted; backups are retained. Run harness-codex remove --recover --project PATH. "
                                 f"Recovery detail: {recovery_error}") from exc
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise LifecycleError(f"Removal failed; original files were restored: {exc}") from exc
    report.update(state="removed", writes=len(operations), recoveryRequired=False)
    try:
        _cleanup(root, journal, helpers)
    except (OSError, ValueError) as exc:
        report.update(state="removed-cleanup-required", recoveryRequired=True,
                      warning=f"Removal committed; backups require cleanup through harness-codex remove --recover: {exc}")
    return report


def removal_status(root: Path, *, source_root: Path) -> dict:
    helpers = _helpers(source_root)
    root = _root(root, helpers[0])
    if _file(root / JOURNAL, helpers[0]) is None:
        helpers[0].checked_path(root / WORKSPACES)
        return {"state": "orphaned-removal-workspace" if (root / WORKSPACES).exists() else "none",
                "recoverable": False, "writes": 0}
    journal = _load_journal(root, helpers)
    _recovery_states(root, journal, helpers, committed=journal["state"] == "remove-committed")
    return {"state": journal["state"], "operation": "remove", "removalSchemaVersion": 1,
            "recoverable": True, "operationCount": len(journal["operations"]), "writes": 0}


@_serialized
def recover_removal(root: Path, *, source_root: Path, dry_run: bool = True) -> dict:
    helpers = _helpers(source_root)
    root = _root(root, helpers[0])
    journal = _load_journal(root, helpers)
    if journal is None:
        helpers[0].checked_path(root / WORKSPACES)
        if (root / WORKSPACES).exists():
            raise LifecycleError("Removal backups exist without a journal; ownership requires manual review.")
        return {"valid": True, "state": "unchanged", "dryRun": dry_run, "writes": 0}
    committed = journal["state"] == "remove-committed"
    _recovery_states(root, journal, helpers, committed=committed)
    result = {"valid": True, "state": "cleanup-preview" if committed else "rollback-preview", "dryRun": dry_run,
              "writes": 0, "operationCount": len(journal["operations"]), "gitMetadataTouched": False}
    if dry_run:
        return result
    if committed:
        _cleanup(root, journal, helpers)
    else:
        _rollback(root, journal, helpers)
    result.update(state="cleaned" if committed else "rolled-back", writes=len(journal["operations"]))
    return result
