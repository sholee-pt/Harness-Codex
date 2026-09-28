"""Owned, immutable CLI releases and explicit GitHub source updates.

This module only touches its user-local tool installation. Project installation
and project Git repositories are deliberately outside its API.
"""

from __future__ import annotations

import ast
import errno
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

from .paths import checked_path, is_link as _linked
from .versions import BRANCH_RE, VERSION_RE, version_key, branch_version
from .project_installer import GENERATOR_ENTRYPOINTS, InstallError, validate_generator_source


DEFAULT_REPOSITORY = "https://github.com/sholee-pt/Harness-Codex.git"
# Old receipts remain readable. Network operations use the renamed repository.
REPOSITORIES = frozenset(prefix + name + '.git'
                        for prefix in ('https://github.com/', 'git@github.com:', 'ssh://git@github.com/')
                        for name in ('sholee-pt/Harness', 'sholee-pt/Harness-Codex'))
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
RELEASE_RE = re.compile(r"(?:[0-9a-f]{40}|content-[0-9a-f]{64})\Z")
MAX_FILES = 10000
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TREE_BYTES = 96 * 1024 * 1024
METADATA = ".agents/skills/harness/scripts/harness_metadata.py"
REQUIRED = frozenset({"harness.py", "install.py", "harness_cli/__init__.py", "harness_cli/main.py", "harness_cli/project.py", "harness_cli/distribution.py", ".agents/skills/harness/SKILL.md", METADATA})
# These are release-specific source dependencies, not a new installation schema.
# Keep the original common set valid for complete v9.2 and v9.3 distributions.
# Later releases inherit each dependency from its numeric introduction version.
VERSION_REQUIRED = (
    (version_key("0.24.0-beta"), frozenset({".agents/skills/harness/scripts/harness_maintenance_history.py"})),
    (version_key("0.23.0-beta"), frozenset({"harness_cli/auto_relay.py", "harness_cli/codex_entry.py", "harness_cli/official_codex.py", "harness_cli/release_updates.py"})),
    (version_key("0.22.2-beta"), frozenset({"harness_cli/project_installer.py", *(
        ".agents/skills/harness/scripts/" + name + ".py" for name in GENERATOR_ENTRYPOINTS
    )})),
    (version_key("0.22.1-beta"), frozenset({"harness_cli/helper.py"})),
    (version_key("0.22.0-beta"), frozenset({"harness_cli/skills.py", ".agents/skills/harness/scripts/harness_external_skills.py", ".agents/skills/harness/references/external-skills.md", ".agents/skills/harness/references/scientific-workflows.md", ".agents/skills/harness/references/contract-review.md"})),
    (version_key("0.21.0-beta"), frozenset({"harness_cli/locking.py", ".agents/skills/harness/scripts/harness_eval_lock.py", ".agents/skills/harness/scripts/harness_instruction_audit.py"})),
    (version_key("0.20.0-beta"), frozenset({"harness_cli/jev_auth.py"})),
    (version_key("0.18.0-beta"), frozenset({"harness_cli/jev.py", "harness_cli/jev_client.py"})),
    (version_key("0.17.0-beta"), frozenset({"harness_cli/graft_setup.py"})),
    (version_key("0.16.0-beta"), frozenset({"harness_cli/graft.py", "harness_cli/graft_bridge.mjs"})),
    (version_key("0.15.0-beta"), frozenset({"harness_cli/checkpoint.py", ".agents/skills/harness/scripts/harness_checkpoint.py", ".agents/skills/harness/references/task-checkpoints.md"})),
    (version_key("0.13.0-beta"), frozenset({"harness_cli/codex_integration.py", "harness_cli/integration_path.py"})),
    (version_key("0.12.0-beta"), frozenset({"harness_cli/model_routing.py", "harness_cli/routing.py", "harness_cli/native_ui.py", "harness_cli/native_router.py", "harness_cli/native_package.py"})),
    (version_key("0.11.0-beta"), frozenset({"harness_cli/native_session.py", "harness_cli/project_brief.py", "harness_cli/project_guide.py", "harness_cli/terminal_menu.py"})),
    (version_key("9.10"), frozenset({"harness_cli/presentation.py", "harness_cli/configuration.py"})),
    (version_key("9.11"), frozenset({"harness_cli/session_settings.py"})),
    (version_key("9.9"), frozenset({"harness_cli/runtime_cleanup.ps1"})),
    (version_key("9.8"), frozenset({"harness_cli/windows_path.py"})),
    (version_key("9.7"), frozenset({"harness_cli/shell.py", "harness_cli/prepare_conda.sh"})),
    (version_key("9.4"), frozenset({"harness_cli/lifecycle.py"})),
    (version_key("9.5"), frozenset({"harness_cli/environment.py"})),
    (version_key("0.10.0-beta"), frozenset({"harness_cli/versions.py", "harness_cli/maintenance.py", ".agents/skills/harness/scripts/harness_maintenance.py"})),
)
# Retain historical optional installer names for old managed receipts. New source
# checkouts keep installers outside the runtime; only archive setup needs them.
TOP_FILES = frozenset({"harness.py", "install.py", "install.sh", "install_harness.sh", "install_harness_codex.sh", "install.ps1", "install_harness_codex.ps1", "environment.yml", "README.md", "LICENSE", "_release.json"})
# Stable installation identity, independent of the GitHub repository display name.
OWNER = {"schema": 1, "tool": "sholee-pt/Harness"}
TOKEN_HELPER = ('!f() { if test "$1" != get; then return; fi; p=; h=; r=; '
                'while IFS="=" read -r k v; do case "$k" in '
                'protocol) p="$v";; host) h="$v";; path) r="$v";; esac; done; '
                'if test "$p" = https && test "$h" = github.com '
                '&& { test "$r" = sholee-pt/Harness.git || test "$r" = sholee-pt/Harness-Codex.git; }; then '
                'printf "username=x-access-token\\npassword=%s\\n" "$HARNESS_GITHUB_TOKEN"; '
                'fi; }; f')


class DistributionError(ValueError):
    """The requested managed installation cannot be changed safely."""


def _path(value) -> Path:
    return checked_path(value, error_type=DistributionError)


def _storage_path(value) -> Path:
    path = _path(value)
    if any(part.rstrip(" .").casefold() == ".git" for part in path.parts):
        raise DistributionError("tool storage and launchers must not be inside Git metadata")
    return path


def _relative(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "\\" in value or any(p in {"", ".", ".."} for p in value.split("/")):
        raise DistributionError("unsafe source path")
    if any(any(c in part for c in ':<>"|?*') or part.endswith((".", " ")) for part in path.parts):
        raise DistributionError("nonportable source path")
    if any(part.lower().split(".")[0] in {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))} for part in path.parts):
        raise DistributionError("reserved source path")
    return path.as_posix()


def _runtime(name: str) -> bool:
    return name in TOP_FILES or name.startswith("harness_cli/") or name.startswith(".agents/skills/harness/")


def _version(value: str) -> tuple[int, int, int, int]:
    try:
        return version_key(value)
    except ValueError as exc:
        raise DistributionError(str(exc)) from exc


def _branch(value: str) -> tuple[int, int, int, int]:
    try:
        return version_key(branch_version(value))
    except ValueError as exc:
        raise DistributionError(str(exc)) from exc


def _repository(value: str) -> str:
    if value not in REPOSITORIES:
        raise DistributionError("source must be the sholee-pt/Harness-Codex GitHub repository using HTTPS or SSH")
    return value


def canonical_repository(value: str) -> str:
    return _repository(value).replace('sholee-pt/Harness.git', 'sholee-pt/Harness-Codex.git')


def _read_json(path: Path) -> dict:
    _path(path)
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise DistributionError("managed metadata is too large")
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DistributionError("managed metadata is missing or invalid") from exc
    if not isinstance(result, dict):
        raise DistributionError("managed metadata must be an object")
    return result


_NO_EXPECTATION = object()


def _write_json(path: Path, value: dict, *, expected=_NO_EXPECTATION) -> None:
    _path(path)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if expected is not _NO_EXPECTATION:
            _path(path)
            current = None
            if path.exists():
                with path.open('rb') as stream:
                    current = stream.read(len(expected or b'') + 1)
            if current != expected:
                raise DistributionError("Managed metadata changed during update; concurrent edits preserved")
            if current is not None:
                Path(temporary).chmod(stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def _snapshot(root: Path, *, managed=False) -> dict[str, bytes]:
    root = _path(root)
    if not root.is_dir():
        raise DistributionError("source must be a directory")
    result = {}
    total = 0
    folded = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        relative_dir = directory_path.relative_to(root).as_posix()
        kept = []
        for name in dirs:
            relative = name if relative_dir == "." else f"{relative_dir}/{name}"
            if name in {".git", "__pycache__"}:
                if managed:
                    raise DistributionError("managed release contains unexpected Git metadata or bytecode caches")
                continue
            if relative in {"harness_cli", ".agents", ".agents/skills", ".agents/skills/harness"} or _runtime(relative + "/"):
                _path(directory_path / name)
                kept.append(name)
            elif managed:
                raise DistributionError("managed release contains unexpected directories")
        dirs[:] = kept
        for name in files:
            relative = name if relative_dir == "." else f"{relative_dir}/{name}"
            if name.endswith((".pyc", ".pyo")):
                if managed:
                    raise DistributionError("managed release contains unexpected bytecode caches")
                continue
            if not _runtime(relative):
                if managed:
                    raise DistributionError("managed release contains unexpected files")
                continue
            relative = _relative(relative)
            path = _path(directory_path / name)
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                raise DistributionError("unsupported or oversized runtime source file")
            if relative.casefold() in folded:
                raise DistributionError("source contains case-colliding paths")
            folded.add(relative.casefold())
            data = path.read_bytes()
            total += len(data)
            if len(data) > MAX_FILE_BYTES or total > MAX_TREE_BYTES or len(result) >= MAX_FILES:
                raise DistributionError("runtime source exceeds installation limits")
            result[relative] = data
    return result


def _hashes(snapshot: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(data).hexdigest() for name, data in sorted(snapshot.items())}


def _tree_hash(hashes: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _cli_imports(name: str, tree: ast.AST) -> set[str]:
    """Read first-party module dependencies without executing downloaded source."""
    package = name.removesuffix(".py").split("/")[:-1]
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = package[:len(package) - node.level + 1] if node.level else []
            parts = prefix + (node.module.split(".") if node.module else [])
            module = ".".join(parts)
            if module == "harness_cli":
                modules.update(module + "." + alias.name for alias in node.names if alias.name != "*")
            else:
                modules.add(module)
    return {module.replace(".", "/") for module in modules
            if module == "harness_cli" or module.startswith("harness_cli.")}


def _source_info(snapshot: dict[str, bytes]) -> tuple[str, str | None]:
    if not REQUIRED.issubset(snapshot):
        raise DistributionError("source is missing required CLI or generator files")
    try:
        syntax = ast.parse(snapshot[METADATA].decode("utf-8-sig"))
        versions = [ast.literal_eval(node.value) for node in syntax.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "HARNESS_VERSION" for target in node.targets)]
        if len(versions) != 1:
            raise ValueError("version declaration")
        version = versions[0]
        version_number = _version(version)
        imports = set()
        for name, data in snapshot.items():
            if name.endswith(".py"):
                if name in {"harness.py", "install.py"} or name.startswith("harness_cli/"):
                    tree = ast.parse(data, name)
                    imports.update(_cli_imports(name, tree))
                    compile(tree, name, "exec")
                elif not name.startswith(".agents/skills/harness/scripts/"):
                    compile(data, name, "exec")
        commit = None
        if "_release.json" in snapshot:
            release = json.loads(snapshot["_release.json"])
            if not isinstance(release, dict) or release.get("version") != version or release.get("runtime", "codex") != "codex":
                raise ValueError("release metadata version mismatch")
            commit = release.get("commit")
            if commit is not None and (not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit)):
                raise ValueError("release metadata commit")
            if release.get("branch") is not None and _branch(release["branch"]) != _version(version):
                raise ValueError("release metadata branch mismatch")
    except (ValueError, TypeError, SyntaxError, UnicodeError) as exc:
        raise DistributionError("source version, runtime, release metadata, or Python syntax is invalid") from exc
    required = REQUIRED.union(*(files for minimum, files in VERSION_REQUIRED if version_number >= minimum))
    missing = sorted(required.difference(snapshot))
    if missing:
        raise DistributionError(f"source is missing required files for Harness {version}: {', '.join(missing)}")
    # Refactors within a release may add modules. Check their actual imports so
    # complete earlier layouts remain valid while missing new dependencies fail
    # before installation state or launchers are created.
    missing_imports = sorted(module + ".py" for module in imports
                             if module + ".py" not in snapshot and module + "/__init__.py" not in snapshot)
    if missing_imports:
        raise DistributionError("source is missing imported CLI modules: " + ", ".join(missing_imports))
    prefix = ".agents/skills/harness/"
    try:
        validate_generator_source({name[len(prefix):]: data for name, data in snapshot.items() if name.startswith(prefix)}, version)
    except InstallError as exc:
        raise DistributionError(str(exc)) from exc
    return version, commit


def _legacy_launcher_source() -> str:
    # This loader stays independent of the source it checks before execution.
    return '''"""Owned Harness CLI launcher; generated by Harness install."""
import hashlib, json, os, pathlib, re, runpy, stat, sys

def fail():
    raise SystemExit("Harness managed installation is invalid or modified; repair it explicitly.")

def safe(path):
    for item in (path, *path.parents):
        if os.path.lexists(item):
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                fail()
    return path

try:
    base = safe(pathlib.Path(os.path.abspath(__file__)).parent)
    active = json.loads(safe(base / "active.json").read_text(encoding="utf-8"))
    release_id = active["releaseId"]
    if not isinstance(release_id, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|content-[0-9a-f]{64})", release_id):
        fail()
    source = safe(base / "releases" / release_id)
    receipt = json.loads(safe(base / "receipts" / (release_id + ".json")).read_text(encoding="utf-8"))
    hashes = {}
    for directory, dirs, files in os.walk(source, followlinks=False):
        for name in dirs:
            safe(pathlib.Path(directory) / name)
        for name in files:
            path = safe(pathlib.Path(directory) / name)
            if not path.is_file():
                fail()
            hashes[path.relative_to(source).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if hashes != receipt["files"] or digest != active["treeHash"]:
        fail()
except (OSError, ValueError, KeyError, TypeError):
    fail()
os.environ["HARNESS_TOOL_HOME"] = str(base)
prefix = pathlib.Path(sys.prefix)
if (prefix / "conda-meta" / "history").is_file() and prefix.name == "harness":
    os.environ["CONDA_PREFIX"] = str(prefix)
    os.environ["CONDA_DEFAULT_ENV"] = "harness"
sys.dont_write_bytecode = True
sys.path.insert(0, str(source))
sys.argv[0] = str(source / "harness.py")
runpy.run_path(sys.argv[0], run_name="__main__")
'''


def _previous_launcher_source() -> str:
    legacy_environment = '''prefix = pathlib.Path(sys.prefix)
if (prefix / "conda-meta" / "history").is_file() and prefix.name == "harness":
    os.environ["CONDA_PREFIX"] = str(prefix)
    os.environ["CONDA_DEFAULT_ENV"] = "harness"
'''
    return _legacy_launcher_source().replace(legacy_environment, '''os.environ.pop("HARNESS_LAUNCHER_ENVIRONMENT", None)
version = active.get("version", "")
if isinstance(version, str) and re.fullmatch(r"[0-9]+\\.[0-9]+", version):
    if tuple(int(part) for part in version.split(".")) >= (9, 5):
        os.environ["HARNESS_LAUNCHER_ENVIRONMENT"] = "preserved-v1"
''')


def _launcher_source() -> str:
    return _previous_launcher_source().replace(
        're.fullmatch(r"[0-9]+\\.[0-9]+", version)',
        're.fullmatch(r"[0-9]+\\.[0-9]+(?:\\.[0-9]+(?:-beta)?)?", version)').replace(
        'if tuple(int(part) for part in version.split(".")) >= (9, 5):',
        'if len(version.removesuffix("-beta").split(".")) == 3 or tuple(int(part) for part in version.split(".")) >= (9, 5):')


def _launchers(data_root: Path, bin_dir: Path, python: str, command: str = "harness") -> dict[Path, bytes]:
    if command not in {"harness", "harness-codex"}:
        raise DistributionError("unsupported launcher command")
    result = {data_root / "launcher.py": _launcher_source().encode("utf-8")}
    result[bin_dir / command] = ("#!/bin/sh\nexec " + shlex.quote(python) + " -B " + shlex.quote(str(data_root / "launcher.py")) + ' "$@"\n').encode()
    if os.name == "nt":
        if any(c in python + str(data_root) for c in '%!\r\n"'):
            raise DistributionError("Windows launcher paths contain unsupported shell characters")
        result[bin_dir / (command + ".cmd")] = (f'@echo off\r\n"{python}" -B "{data_root / "launcher.py"}" %*\r\n').encode()
    return result


def _owned_root(data_root: Path) -> None:
    _path(data_root)
    if not data_root.is_dir() or _read_json(data_root / ".harness-tool.json") != OWNER:
        raise DistributionError("tool directory is not an owned Harness installation")
    for name in ("releases", "receipts"):
        path = _path(data_root / name)
        if not path.is_dir():
            raise DistributionError("managed installation directories are missing")


@contextmanager
def _lock(data_root: Path):
    lock = _path(data_root / ".install.lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise DistributionError("another installation is active, or its lock needs manual recovery") from exc
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


def _installation_status(data_root, *, launcher_hashes_override=None) -> dict:
    """Read and verify the active source, receipt, and launchers without writes."""
    data_root = _storage_path(data_root)
    _owned_root(data_root)
    active = _read_json(data_root / "active.json")
    if active.get("schema") != 1 or not isinstance(active.get("releaseId"), str) or not RELEASE_RE.fullmatch(active["releaseId"]):
        raise DistributionError("invalid active release metadata")
    _version(active.get("version"))
    if active.get("runtime", "codex") != "codex":
        raise DistributionError("this installation belongs to an unsupported runtime")
    _repository(active.get("repository"))
    if active.get("branch") is not None:
        _branch(active["branch"])
    if active.get("commit") is not None and (not isinstance(active["commit"], str) or not COMMIT_RE.fullmatch(active["commit"])):
        raise DistributionError("invalid active source commit")
    source = _path(data_root / "releases" / active["releaseId"])
    receipt = _read_json(data_root / "receipts" / (active["releaseId"] + ".json"))
    snapshot = _snapshot(source, managed=True)
    hashes = _hashes(snapshot)
    if (receipt.get("runtime", "codex") != "codex" or receipt.get("schema") != 1
            or receipt.get("treeHash") != active.get("treeHash") or receipt.get("files") != hashes
            or active.get("treeHash") != _tree_hash(hashes)):
        raise DistributionError("managed release contains local changes; refusing to overwrite them")
    version, declared_commit = _source_info(snapshot)
    expected_id = active["commit"] or "content-" + active["treeHash"]
    if version != active["version"] or (declared_commit is not None and declared_commit != active["commit"]) or active["releaseId"] != expected_id:
        raise DistributionError("active source version or provenance mismatch")
    if not isinstance(active.get("python"), str) or not isinstance(active.get("binDir"), str):
        raise DistributionError("invalid launcher metadata")
    launcher_hashes = active.get("launchers")
    expected_paths = {str(path) for path in _launchers(data_root, _storage_path(active["binDir"]), active["python"], active.get("command", "harness"))}
    if not isinstance(launcher_hashes, dict) or set(launcher_hashes) != expected_paths:
        raise DistributionError("invalid launcher ownership metadata")
    if launcher_hashes_override is not None:
        if set(launcher_hashes_override) != set(launcher_hashes):
            raise DistributionError("invalid launcher transition metadata")
        launcher_hashes = launcher_hashes_override
    for path, expected in launcher_hashes.items():
        candidate = _path(path)
        if not candidate.is_file() or hashlib.sha256(candidate.read_bytes()).hexdigest() != expected:
            raise DistributionError("managed launcher was changed; refusing to overwrite it")
    if active.get("auto_update") not in {"compatible", "check", "off"}:
        raise DistributionError("invalid automatic update policy")
    return {**active, "dataRoot": str(data_root), "sourceRoot": str(source), "releasePath": str(source), "release_root": str(source)}


def installed_status(data_root) -> dict:
    """Verify the source, receipts and current launcher hashes without writes."""
    return _installation_status(data_root)


def _migration_seal(value: dict) -> dict:
    content = {key: item for key, item in value.items() if key != "seal"}
    return {**content, "seal": hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def _launcher_migration(data_root: Path) -> tuple[dict, dict] | None:
    journal_path = _path(data_root / ".launcher-migration.json")
    if not journal_path.exists():
        return None
    journal = _read_json(journal_path)
    if (set(journal) != {"schema", "operation", "before", "after", "mode", "seal"}
            or type(journal.get("schema")) is not int or journal["schema"] != 1
            or journal.get("operation") != "preserve-caller-environment"
            or not isinstance(journal.get("before"), dict) or not isinstance(journal.get("after"), dict)
            or type(journal.get("mode")) is not int or not 0 <= journal["mode"] <= 0o777
            or _migration_seal(journal) != journal):
        raise DistributionError("invalid launcher migration journal; preserving the installation")
    launcher = _path(data_root / "launcher.py")
    before, after = journal["before"], journal["after"]
    old_hashes = {hashlib.sha256(source().encode()).hexdigest()
                  for source in (_legacy_launcher_source, _previous_launcher_source)}
    new_hash = hashlib.sha256(_launcher_source().encode()).hexdigest()
    hashes = before.get("launchers")
    if not isinstance(hashes, dict) or hashes.get(str(launcher)) not in old_hashes:
        raise DistributionError("launcher migration does not identify an owned legacy launcher")
    old_hash = hashes[str(launcher)]
    expected_after = {**before, "launchers": {**hashes, str(launcher): new_hash}}
    if after != expected_after:
        raise DistributionError("launcher migration attempts to change unrelated installation state")
    active = _read_json(data_root / "active.json")
    if active != before and active != after:
        raise DistributionError("active installation changed during launcher migration")
    if not launcher.is_file():
        raise DistributionError("launcher is missing during migration; preserving the journal")
    current_hash = hashlib.sha256(launcher.read_bytes()).hexdigest()
    if current_hash not in {old_hash, new_hash}:
        raise DistributionError("managed launcher changed during migration; preserving user edits")
    if os.name != "nt" and stat.S_IMODE(launcher.stat().st_mode) != journal["mode"]:
        raise DistributionError("managed launcher permissions changed during migration")
    # Only this strictly checked two-state transition can override the active
    # launcher hash. All immutable source, receipt and other launcher checks run.
    status = _installation_status(data_root, launcher_hashes_override={**hashes, str(launcher): current_hash})
    return journal, status


def launcher_status(data_root) -> dict:
    """Inspect an owned environment migration without repairing or writing it."""
    data_root = _storage_path(data_root)
    pending = _launcher_migration(data_root)
    if pending is not None:
        status = pending[1]
        state = "repair-pending"
    else:
        status = installed_status(data_root)
        content = (data_root / "launcher.py").read_bytes()
        if content == _launcher_source().encode():
            state = "current"
        elif content in {_legacy_launcher_source().encode(), _previous_launcher_source().encode()}:
            state = "legacy"
        else:
            raise DistributionError("owned launcher has an unknown implementation; automatic repair refused")
        lock = _path(data_root / ".install.lock")
        if lock.is_file() and lock.read_bytes() == b"Harness launcher environment migration v1\n":
            state = "repair-pending"
    return {"state": state, "sourceRoot": status["sourceRoot"],
            "callerEnvironmentPreserved": state == "current", "writes": 0,
            "repairCommand": status.get("command", "harness") + " update --repair-launcher" if state != "current" else None}


def _sync_launcher_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EINVAL, errno.ENOTSUP}:
            return
        raise
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if exc.errno not in {errno.EINVAL, errno.ENOTSUP}:
                raise
    finally:
        os.close(descriptor)


def _replace_launcher(path: Path, payload: bytes, mode: int) -> None:
    _path(path)
    fd, temporary = tempfile.mkstemp(prefix=".launcher-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            if os.name != "nt":
                os.fchmod(output.fileno(), mode)
            output.flush()
            os.fsync(output.fileno())
        if (_path(path).read_bytes() not in {_legacy_launcher_source().encode(), _previous_launcher_source().encode()}
                or (os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != mode)):
            raise DistributionError("managed launcher changed immediately before replacement")
        os.replace(temporary, path)
        _sync_launcher_directory(path.parent)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


@contextmanager
def _launcher_repair_lock(data_root: Path):
    """Serialize repairs with a crash-released OS lock and exclude old updaters."""
    path = _path(data_root / ".launcher-migration.lock")
    marker = b"Harness launcher migration lock v1\n"
    try:
        stream = path.open("x+b")
        stream.write(marker)
        stream.flush()
        os.fsync(stream.fileno())
        _sync_launcher_directory(data_root)
    except FileExistsError:
        stream = path.open("r+b")
    locked = False
    try:
        stream.seek(0)
        if stream.read() != marker:
            raise DistributionError("unrecognized launcher migration lock; preserving it")
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise DistributionError("another launcher migration is active") from exc
        install_lock = _path(data_root / ".install.lock")
        own_marker = b"Harness launcher environment migration v1\n"
        try:
            with install_lock.open("xb") as output:
                output.write(own_marker)
                output.flush()
                os.fsync(output.fileno())
                _sync_launcher_directory(data_root)
        except FileExistsError:
            # The OS lock proves a previous migration process no longer holds
            # this protocol. Ordinary updater/PID locks are never taken over.
            if not install_lock.is_file() or install_lock.read_bytes() != own_marker:
                raise DistributionError("another installation is active, or its lock needs manual recovery")
        try:
            yield
        finally:
            if _path(install_lock).is_file() and install_lock.read_bytes() == own_marker:
                install_lock.unlink()
                _sync_launcher_directory(data_root)
    finally:
        if locked:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _repair_launcher(data_root) -> dict:
    """Finish an owned launcher transition offline, retaining a recovery journal.

    The two-file commit is recoverable, not a claim of multi-file atomicity.
    Each file replacement is atomic; a validated journal permits an interrupted
    transition to finish without overwriting changed launchers or project files.
    """
    data_root = _storage_path(data_root)
    _owned_root(data_root)
    pending = _launcher_migration(data_root)
    if pending is None:
        status = launcher_status(data_root)
        if (data_root / "launcher.py").read_bytes() == _launcher_source().encode():
            return {"state": "unchanged", "repaired": False, "writes": 0, "installation": installed_status(data_root)}
        before = _read_json(data_root / "active.json")
        launcher = _path(data_root / "launcher.py")
        mode = stat.S_IMODE(launcher.stat().st_mode)
        if mode & 0o7000:
            raise DistributionError("special launcher permissions require manual review")
        after = {**before, "launchers": {**before["launchers"],
                  str(launcher): hashlib.sha256(_launcher_source().encode()).hexdigest()}}
        journal = _migration_seal({"schema": 1, "operation": "preserve-caller-environment",
                                   "before": before, "after": after, "mode": mode})
        path = _path(data_root / ".launcher-migration.json")
        with path.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(journal, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        _sync_launcher_directory(data_root)
    else:
        journal = pending[0]
    try:
        _launcher_migration(data_root)  # Recheck all state before any replacement.
        launcher = _path(data_root / "launcher.py")
        if launcher.read_bytes() != _launcher_source().encode():
            _replace_launcher(launcher, _launcher_source().encode(), journal["mode"])
        _launcher_migration(data_root)
        if _read_json(data_root / "active.json") != journal["after"]:
            _write_json(data_root / "active.json", journal["after"])
            _sync_launcher_directory(data_root)
        status = installed_status(data_root)
        _launcher_migration(data_root)
        (data_root / ".launcher-migration.json").unlink()
        _sync_launcher_directory(data_root)
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise DistributionError("Launcher migration is incomplete; the owned recovery journal was retained. "
                                "Run harness update --repair-launcher from the same parent terminal.") from exc
    return {"state": "repaired", "repaired": True, "writes": 2, "installation": status}


def repair_launcher(data_root) -> dict:
    data_root = _storage_path(data_root)
    _owned_root(data_root)
    if launcher_status(data_root)["state"] == "current":
        return {"state": "unchanged", "repaired": False, "writes": 0, "installation": installed_status(data_root)}
    with _launcher_repair_lock(data_root):
        return _repair_launcher(data_root)


def _activate(snapshot: dict[str, bytes], data_root: Path, active: dict) -> dict:
    hashes = _hashes(snapshot)
    active["treeHash"] = _tree_hash(hashes)
    release_id = active.get("commit") or "content-" + active["treeHash"]
    active["releaseId"] = release_id
    active["runtime"] = "codex"
    target = _path(data_root / "releases" / release_id)
    receipt = _path(data_root / "receipts" / (release_id + ".json"))
    created = False
    receipt_value = {"schema": 1, "runtime": "codex", "files": hashes, "treeHash": active["treeHash"]}
    try:
        if target.exists():
            existing_receipt = _read_json(receipt) if receipt.exists() else {}
            existing_receipt.setdefault("runtime", "codex")
            if existing_receipt != receipt_value or _hashes(_snapshot(target, managed=True)) != hashes:
                raise DistributionError("existing release is unowned, changed, or inconsistent")
        else:
            if receipt.exists():
                raise DistributionError("orphaned release receipt requires manual recovery")
            with tempfile.TemporaryDirectory(prefix=".release-", dir=data_root / "releases") as temporary:
                staged = Path(temporary) / "source"
                staged.mkdir()
                for name, data in snapshot.items():
                    path = staged.joinpath(*PurePosixPath(name).parts)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    path.chmod(0o755 if name in {"install.sh", "install_harness.sh", "install_harness_codex.sh"} else 0o644)
                os.replace(staged, target)
                created = True
            _write_json(receipt, receipt_value)
        pointer = data_root / "active.json"
        if not pointer.exists() or _read_json(pointer) != active:
            _write_json(pointer, active)
    except BaseException:
        if created:
            # Roll back only this attempt's unchanged files, and only before its
            # pointer commit. Never remove an earlier release or concurrent edit.
            try:
                pointer = data_root / "active.json"
                committed = pointer.exists() and _read_json(pointer).get("releaseId") == release_id
                expected_dirs = {str(parent) for name in snapshot for parent in PurePosixPath(name).parents if str(parent) != "."}
                actual_dirs = {path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_dir()}
                if (not committed and _path(target).parent == _path(data_root / "releases")
                        and _hashes(_snapshot(target, managed=True)) == hashes and actual_dirs == expected_dirs):
                    shutil.rmtree(target)
                    if receipt.exists() and _read_json(receipt) == receipt_value:
                        receipt.unlink()
            except (OSError, DistributionError):
                pass  # Preserve questionable data for explicit recovery.
        raise
    return installed_status(data_root)


def _install_tool(source_root, data_root, bin_dir, python_executable=sys.executable, branch=None, repository=DEFAULT_REPOSITORY, auto_update="compatible") -> dict:
    """Install a trusted local source tree into user-owned immutable releases."""
    source_root, data_root, bin_dir = _path(source_root), _storage_path(data_root), _storage_path(bin_dir)
    repository = _repository(repository)
    if auto_update not in {"compatible", "check", "off"}:
        raise DistributionError("automatic updates must be compatible, check, or off")
    if branch is not None:
        _branch(branch)
    managed_source = None
    if source_root == data_root or source_root in data_root.parents or data_root in source_root.parents:
        if data_root in source_root.parents:
            managed_source = installed_status(data_root)
        if managed_source is None or source_root != Path(managed_source["sourceRoot"]):
            raise DistributionError("source and installation directories must not overlap")
    if bin_dir == data_root or bin_dir in data_root.parents or data_root in bin_dir.parents:
        raise DistributionError("bin and tool directories must not overlap")
    # Conda commonly exposes bin/python as a symlink to its real interpreter.
    python = str(Path(python_executable).expanduser().resolve())
    if not Path(python).is_file():
        raise DistributionError("Python executable is missing")
    snapshot = _snapshot(source_root)
    version, commit = _source_info(snapshot)
    if managed_source is not None:
        commit = managed_source["commit"]
    if commit is None and (source_root / ".git").exists():
        commit = _checkout_commit(source_root, snapshot)
    if branch is not None and _branch(branch) != _version(version):
        raise DistributionError("source version does not match pinned branch")
    command = "harness-codex" if _version(version) >= _version("9.7") else "harness"
    launchers = _launchers(data_root, bin_dir, python, command)
    existing = None
    if data_root.exists() and any(data_root.iterdir()):
        existing = installed_status(data_root)
        command = existing.get("command", "harness")
        if existing["python"] != python or existing["binDir"] != str(bin_dir):
            raise DistributionError("existing installation uses different interpreter or bin directory")
        if _version(version) < _version(existing["version"]):
            raise DistributionError("installation would downgrade the current version")
        if version == existing["version"] and _tree_hash(_hashes(snapshot)) != existing["treeHash"]:
            raise DistributionError("same-version replacement needs a verified remote update")
    else:
        for path in launchers:
            if os.path.lexists(path):
                raise DistributionError("launcher path is already user-owned; refusing to replace it")
    created_root = not data_root.exists()
    created_files = {}
    created_dirs = []
    data_root.mkdir(parents=True, exist_ok=True)
    try:
        with _lock(data_root):
            if existing:
                if installed_status(data_root) != existing:
                    raise DistributionError("installation changed during setup; retry against the current installation")
            else:
                if any(path.name != ".install.lock" for path in data_root.iterdir()):
                    raise DistributionError("installation directory changed during setup")
                marker = data_root / ".harness-tool.json"
                _write_json(marker, OWNER)
                created_files[marker] = marker.read_bytes()
                for name in ("releases", "receipts"):
                    directory = data_root / name
                    directory.mkdir()
                    created_dirs.append(directory)
                if not bin_dir.exists():
                    bin_dir.mkdir(parents=True)
                    created_dirs.append(bin_dir)
                for path, data in launchers.items():
                    with path.open("xb") as stream:
                        created_files[path] = data
                        stream.write(data)
                    path.chmod(0o755 if path.name == command else 0o644)
            active = {"schema": 1, "version": version, "commit": commit, "python": python, "binDir": str(bin_dir), "repository": repository, "branch": branch, "auto_update": auto_update,
                      "launchers": existing["launchers"] if existing else {str(path): hashlib.sha256(data).hexdigest() for path, data in launchers.items()}}
            if command != "harness":
                active["command"] = command
            return _activate(snapshot, data_root, active)
    except BaseException:
        if not existing and not (data_root / "active.json").exists():
            for path, expected in reversed(tuple(created_files.items())):
                try:
                    if _path(path).is_file() and path.read_bytes() == expected:
                        path.unlink()
                except (OSError, DistributionError):
                    pass
            for directory in reversed(created_dirs):
                try:
                    _path(directory).rmdir()  # Only an empty, unchanged directory.
                except (OSError, DistributionError):
                    pass
            if created_root:
                try:
                    _path(data_root).rmdir()
                except (OSError, DistributionError):
                    pass
        raise


def _git(arguments: list[str], *, timeout: int, git_executable: str = "git", allow_failure=False) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GCM_INTERACTIVE"] = "Never"
    # Match bootstrap isolation for every source-provenance and download call.
    # Ordinary Git config files, HOME and SSH identity/command selection remain
    # available; ambient repository and command-line config injections do not.
    context_keys = {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                    "GIT_NAMESPACE", "GIT_SHALLOW_FILE", "GIT_REPLACE_REF_BASE",
                    "GIT_EXEC_PATH", "GIT_CONFIG", "GIT_TEMPLATE_DIR", "GIT_ASKPASS"}
    for key in tuple(environment):
        if key in context_keys or key.startswith(("GIT_CONFIG_", "GIT_TRACE", "GIT_REDIRECT_", "GIT_ATTR_")):
            environment.pop(key, None)
    authentication = []
    # Only these fixed-repository HTTPS operations receive environment auth.
    # The helper string contains no secret and ignores Git's store/erase actions.
    if DEFAULT_REPOSITORY in arguments and ("ls-remote" in arguments or "fetch" in arguments):
        token = environment.get("GITHUB_TOKEN") or environment.get("GH_TOKEN")
        if token:
            if any(ord(character) < 32 or ord(character) == 127 for character in token):
                raise DistributionError("GitHub token contains unsupported control characters")
            environment["HARNESS_GITHUB_TOKEN"] = token
            for key in tuple(environment):
                if key.startswith("GIT_TRACE") or key in {"GIT_CURL_VERBOSE", "GCM_TRACE", "GCM_TRACE_SECRETS"}:
                    environment.pop(key, None)
            authentication = ["-c", "credential.helper=", "-c", "credential.useHttpPath=true",
                              "-c", "credential.helper=" + TOKEN_HELPER]
    if git_executable == "git" and shutil.which("git") is None:
        prefix = Path(sys.executable).parent
        candidates = ([prefix / name for name in ("Library/cmd/git.exe", "Library/bin/git.exe", "Library/usr/bin/git.exe", "git.exe")]
                      if os.name == "nt" else [prefix / "git"])
        for bundled in candidates:
            if bundled.is_file():
                git_executable = str(bundled)
                if os.name == "nt":
                    # Git's DLLs belong to this child only; Codex keeps the caller environment.
                    environment["PATH"] = os.pathsep.join([str(bundled.parent), str(prefix / "Library/bin"),
                                                          str(prefix / "Library/usr/bin"), environment.get("PATH", "")])
                break
    try:
        result = subprocess.run([git_executable, "-c", "protocol.file.allow=never", *authentication, *arguments], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DistributionError("GitHub update check or download failed; check Git availability, authentication, and network access") from exc
    if result.returncode and not allow_failure:
        # Git errors can include authenticated URLs or credential-helper output.
        raise DistributionError("GitHub source operation failed; check existing GitHub authentication and network access")
    return result


def _checkout_commit(source_root: Path, snapshot: dict[str, bytes]) -> str | None:
    """Use checkout provenance only when the runtime exactly equals its HEAD."""
    try:
        commit = _git(["-C", str(source_root), "rev-parse", "HEAD^{commit}"], timeout=10).stdout.decode("ascii").strip()
        if not COMMIT_RE.fullmatch(commit):
            return None
        with tempfile.TemporaryDirectory(prefix="harness-provenance-") as temporary:
            archive = Path(temporary) / "source.tar"
            _git(["-C", str(source_root), "archive", "--format=tar", "--output=" + str(archive), commit], timeout=10)
            extracted = Path(temporary) / "runtime"
            extracted.mkdir()
            _extract_archive(archive, extracted)
            return commit if _snapshot(extracted) == snapshot else None
    except (DistributionError, OSError, UnicodeError):
        return None


def check_update(data_root, *, branch=None, repository=None, timeout=20, git_executable="git") -> dict:
    """Query branch heads. No cache, project, release, or pointer is modified."""
    active = installed_status(data_root)
    repository = canonical_repository(repository if repository is not None else active["repository"])
    selected = branch if branch is not None else active["branch"]
    if selected is not None:
        _branch(selected)
    patterns = ['refs/heads/' + selected] if selected else ['refs/heads/v*', 'refs/heads/codex/v*']
    result = _git(["ls-remote", "--heads", repository, *patterns], timeout=timeout, git_executable=git_executable)
    heads = {}
    try:
        for line in result.stdout.decode("utf-8").splitlines():
            parts = line.split()
            if len(parts) != 2 or not parts[1].startswith("refs/heads/"):
                continue
            name = parts[1][11:]
            if BRANCH_RE.fullmatch(name) and COMMIT_RE.fullmatch(parts[0]) and (selected is None or name == selected):
                if name in heads and heads[name] != parts[0]:
                    raise DistributionError("remote returned conflicting branch heads")
                heads[name] = parts[0]
    except UnicodeError as exc:
        raise DistributionError("remote branch response is invalid") from exc
    if not heads:
        raise DistributionError("no supported Codex release branch was found")
    selected = max(heads, key=lambda name: (_branch(name), name))
    available = branch_version(selected)
    downgrade = _version(available) < _version(active["version"])
    changed = heads[selected] != active["commit"] or available != active["version"]
    return {"status": "downgrade-refused" if downgrade else "update-available" if changed else "up-to-date", "updateAvailable": changed and not downgrade,
            "currentVersion": active["version"], "currentCommit": active["commit"], "availableVersion": available,
            "availableCommit": heads[selected], "branch": selected, "repository": repository,
            "majorUpgrade": _version(available)[0] > _version(active["version"])[0]}


def _extract_archive(archive: Path, target: Path) -> None:
    """Extract a bounded Git archive, rejecting unsafe entries before writing."""
    if archive.stat().st_size > MAX_TREE_BYTES * 2:
        raise DistributionError("downloaded archive is too large")
    try:
        with tarfile.open(archive, mode="r:") as bundle:
            members = bundle.getmembers()
            total = 0
            names = set()
            if len(members) > MAX_FILES * 2:
                raise DistributionError("downloaded archive contains too many entries")
            for member in members:
                name = _relative(member.name.rstrip("/") if member.isdir() else member.name)
                if name.casefold() in names:
                    raise DistributionError("downloaded archive contains duplicate paths")
                names.add(name.casefold())
                if not member.isdir() and not member.isfile():
                    raise DistributionError("downloaded archive contains links or special files")
                if member.size < 0 or member.size > MAX_FILE_BYTES:
                    raise DistributionError("downloaded archive member exceeds limits")
                total += member.size
                if total > MAX_TREE_BYTES:
                    raise DistributionError("downloaded archive exceeds limits")
            for member in members:
                name = member.name.rstrip("/")
                if member.isdir() or not _runtime(name):
                    continue
                path = target.joinpath(*PurePosixPath(name).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                stream = bundle.extractfile(member)
                if stream is None:
                    raise DistributionError("downloaded archive file is unreadable")
                with stream, path.open("xb") as output:
                    shutil.copyfileobj(stream, output)
    except (tarfile.TarError, OSError) as exc:
        raise DistributionError("downloaded archive is invalid") from exc


def _update_tool(data_root, *, branch=None, repository=None, timeout=120, git_executable="git", expected_major=None) -> dict:
    """Download a resolved commit, validate it, then atomically switch releases."""
    data_root = _storage_path(data_root)
    active = installed_status(data_root)
    with _lock(data_root):
        active = installed_status(data_root)
        check = check_update(data_root, branch=branch, repository=repository, timeout=min(timeout, 20), git_executable=git_executable)
        if expected_major is not None and (type(expected_major) is not int or _version(check["availableVersion"])[0] != expected_major):
            raise DistributionError("automatic update cannot cross a major version; run harness update explicitly")
        if check["status"] == "downgrade-refused":
            raise DistributionError("remote branch would downgrade the installed version")
        if not check["updateAvailable"]:
            # A branch/transport selection is an explicit tracking preference,
            # including when that branch already points to the installed code.
            if ((branch is not None and branch != active["branch"])
                    or check["repository"] != active["repository"]):
                saved = {key: value for key, value in active.items() if key not in {"dataRoot", "sourceRoot", "releasePath", "release_root"}}
                saved["repository"] = check["repository"]
                if branch is not None:
                    saved["branch"] = branch
                _write_json(data_root / "active.json", saved)
                active = installed_status(data_root)
            return {**check, "updated": False, "installation": active}
        if active["commit"] is None and check["availableVersion"] == active["version"]:
            raise DistributionError("same-version update requires recorded commit provenance; install a release package or select a newer release")
        with tempfile.TemporaryDirectory(prefix=".download-", dir=data_root) as temporary:
            temporary = Path(temporary)
            git_root = temporary / "source.git"
            _git(["init", "--bare", str(git_root)], timeout=timeout, git_executable=git_executable)
            _git(["--git-dir", str(git_root), "fetch", "--no-tags", check["repository"], check["availableCommit"]], timeout=timeout, git_executable=git_executable)
            resolved = _git(["--git-dir", str(git_root), "rev-parse", "FETCH_HEAD^{commit}"], timeout=timeout, git_executable=git_executable).stdout.decode("ascii", errors="replace").strip()
            if resolved != check["availableCommit"]:
                raise DistributionError("download did not resolve to the selected immutable commit")
            if active["commit"]:
                ancestry = _git(["--git-dir", str(git_root), "merge-base", "--is-ancestor", active["commit"], resolved], timeout=timeout, git_executable=git_executable, allow_failure=True)
                if ancestry.returncode:
                    raise DistributionError("remote history is not a verified forward update; refusing rollback or rewritten history")
            archive = temporary / "source.tar"
            _git(["--git-dir", str(git_root), "archive", "--format=tar", "--output=" + str(archive), resolved], timeout=timeout, git_executable=git_executable)
            extracted = temporary / "runtime"
            extracted.mkdir()
            _extract_archive(archive, extracted)
            snapshot = _snapshot(extracted)
            version, commit = _source_info(snapshot)
            if version != check["availableVersion"] or (commit is not None and commit != resolved):
                raise DistributionError("downloaded source version or commit disagrees with the selected branch")
            # Verify again after download; retain any local edits made meanwhile.
            current = installed_status(data_root)
            if current["releaseId"] != active["releaseId"]:
                raise DistributionError("active installation changed during download")
            new_active = {key: value for key, value in active.items() if key not in {"dataRoot", "sourceRoot", "releasePath", "release_root"}}
            new_active.update(version=version, commit=resolved, repository=check["repository"])
            if branch is not None:
                new_active["branch"] = branch
            installation = _activate(snapshot, data_root, new_active)
        return {**check, "status": "updated", "updated": True, "installation": installation}


def install_tool(source_root, data_root, bin_dir, python_executable=sys.executable, branch=None, repository=DEFAULT_REPOSITORY, auto_update="compatible") -> dict:
    # Recovery happens outside the general update lock. A crash in launcher
    # migration must not leave that lock obstructing its explicit recovery path.
    data_root = _storage_path(data_root)
    if os.path.lexists(data_root / ".launcher-migration.json"):
        repair_launcher(data_root)
    result = _install_tool(source_root, data_root, bin_dir, python_executable, branch, repository, auto_update)
    return repair_launcher(data_root)["installation"]


def update_tool(data_root, *, branch=None, repository=None, timeout=120, git_executable="git", expected_major=None) -> dict:
    data_root = _storage_path(data_root)
    if os.path.lexists(data_root / ".launcher-migration.json"):
        repair_launcher(data_root)
    result = _update_tool(data_root, branch=branch, repository=repository, timeout=timeout,
                          git_executable=git_executable, expected_major=expected_major)
    result["installation"] = repair_launcher(data_root)["installation"]
    return result


def mark_check(data_root, *, now=None) -> None:
    """Record an automatic check attempt, including offline failures, for its TTL."""
    data_root = _storage_path(data_root)
    _owned_root(data_root)
    _write_json(data_root / "last-check.json", {"schema": 1, "attemptedAt": time.time() if now is None else now})


def check_due(data_root, ttl_seconds=86400, *, now=None) -> bool:
    data_root = _storage_path(data_root)
    _owned_root(data_root)
    path = data_root / "last-check.json"
    if not path.exists():
        return True
    record = _read_json(path)
    timestamp = record.get("attemptedAt")
    if record.get("schema") != 1 or isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        raise DistributionError("invalid update check timestamp")
    current = time.time() if now is None else now
    return timestamp > current or current - timestamp >= ttl_seconds
