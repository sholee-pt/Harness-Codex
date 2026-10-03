"""Collect and validate release inputs against their immutable Git source."""
from __future__ import annotations

import ast
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

from harness_cli.distribution import _source_info, source_contract
from harness_cli.paths import checked_path as _checked_path
from harness_cli.versions import VERSION_RE


BOOTSTRAPS = ("install_harness_codex.sh", "install_harness_codex.ps1")
ROOT_FILES = ("harness.py", "install.py", "environment.yml", "README.md", "LICENSE",
              "installer/install.sh", "installer/install.ps1",
              *("installer/" + name for name in BOOTSTRAPS))
ROOT_DIRS = ("harness_cli", ".agents/skills/harness")


def checked_path(value: Path) -> Path:
    return _checked_path(value.expanduser(), message="Build paths must not contain symlinks or reparse points")


def release_version(root: Path) -> str:
    tree = ast.parse((root / ".agents/skills/harness/scripts/harness_metadata.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "HARNESS_VERSION" for t in node.targets):
            value = ast.literal_eval(node.value)
            if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
                raise ValueError("Release version must be N.N.N[-beta]")
            return value
    raise ValueError("Missing release version")


def collect_source(root: Path, *, allow_dirty: bool = False):
    version = release_version(root)
    git = ["git", "-c", "safe.directory=" + root.as_posix(), "-C", str(root)]
    commit_result = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    status = subprocess.run([*git, "status", "--porcelain=v1", "--untracked-files=all"], capture_output=True, text=True, check=True)
    if status.stdout.strip() and not allow_dirty:
        raise ValueError("Release builds require clean committed source; use --allow-dirty only for local checks.")
    commit = None if status.stdout.strip() else commit_result.stdout.strip()
    files: dict[str, bytes] = {}
    for name in ROOT_FILES:
        path = checked_path(root / name)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Required regular release file missing: {name}")
        files[name] = path.read_bytes()
    for name in ROOT_DIRS:
        directory = checked_path(root / name)
        if not directory.is_dir():
            raise ValueError(f"Required release directory missing: {name}")
        for path in sorted(directory.rglob("*")):
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            checked_path(path)
            if path.is_file():
                files[path.relative_to(root).as_posix()] = path.read_bytes()
    if commit is not None:
        # Porcelain can hide assume-unchanged entries. Compare the actual build
        # bytes to the immutable commit before claiming a source identity.
        captured = subprocess.run([*git, "archive", "--format=tar", commit], capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(captured)) as archive:
            committed = {
                m.name: archive.extractfile(m).read()
                for m in archive.getmembers()
                if m.isfile()
                and (m.name in ROOT_FILES or any(m.name.startswith(d + "/") for d in ROOT_DIRS))
                and "__pycache__" not in Path(m.name).parts
                and Path(m.name).suffix not in {".pyc", ".pyo"}
            }
        if committed != files:
            if not allow_dirty:
                raise ValueError("Release payload does not match the source commit")
            commit = None
    # Keep source identity checks above in repository coordinates. The unpacked
    # entry points retain their public paths; downloaders are standalone assets,
    # not dependencies to copy into every installed tool release.
    bootstraps = {name: files.pop("installer/" + name) for name in BOOTSTRAPS}
    files = {name.removeprefix("installer/"): data for name, data in files.items()}
    # Completeness is independent of hashes and syntax of files that happen to
    # exist. Reject missing version-specific runtime modules before output writes.
    _source_info(files)
    release = {"runtime": "codex", "version": version, "commit": commit, "branch": f"v{version}"}
    contract = source_contract(files)
    if contract is not None:
        release["sourceContract"] = contract
    files["_release.json"] = (json.dumps(release, sort_keys=True, indent=2) + "\n").encode()
    files["CONTENTS.sha256"] = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items())).encode()
    return version, commit, files, bootstraps
