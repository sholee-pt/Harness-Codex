#!/usr/bin/env python3
"""Build a reproducible Linux distribution with stdlib and a pinned source identity."""
from __future__ import annotations
import argparse
import ast
import gzip
import hashlib
import io
import json
import os
import re
from pathlib import Path
import stat
import subprocess
import tarfile

from harness_cli.distribution import _source_info

ROOT_FILES = ("harness.py", "install.py", "install.sh", "install_harness.sh", "environment.yml", "README.md", "LICENSE")
ROOT_DIRS = ("harness_cli", ".agents/skills/harness")


def checked_path(value: Path) -> Path:
    path = Path(os.path.abspath(value.expanduser()))
    for ancestor in (*reversed(path.parents), path):
        if not os.path.lexists(ancestor):
            continue
        info = ancestor.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Build paths must not contain symlinks or reparse points")
    return path


def release_version(root: Path) -> str:
    tree = ast.parse((root / ".agents/skills/harness/scripts/harness_metadata.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "HARNESS_VERSION" for t in node.targets):
            value = ast.literal_eval(node.value)
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+", value):
                raise ValueError("Release version must be a major.minor string")
            return value
    raise ValueError("Missing release version")


def build(root: Path, output: Path, *, allow_dirty: bool = False) -> dict:
    root = checked_path(root)
    output = checked_path(output)
    if output == root or root in output.parents or any(p.casefold() == ".git" for p in output.parts):
        raise ValueError("Build output must be outside the source tree and Git metadata")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Build output must be a new or empty directory; existing files are preserved")
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
    # Completeness is independent of hashes and syntax of files that happen to
    # exist. Reject missing version-specific runtime modules before output writes.
    _source_info(files)
    files["_release.json"] = (json.dumps({"runtime": "codex", "version": version, "commit": commit, "branch": f"codex/v{version}"}, sort_keys=True, indent=2) + "\n").encode()
    files["CONTENTS.sha256"] = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items())).encode()
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / f"harness-codex-{version}-linux.tar.gz"
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(f"harness-codex-{version}/{name}")
            info.size = len(data)
            info.mode = 0o755 if name in {"install.sh", "install_harness.sh", "harness.py"} else 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    with artifact.open("xb") as stream:
        with gzip.GzipFile(fileobj=stream, filename="", mode="wb", mtime=0) as compressed:
            compressed.write(content.getvalue())
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    bootstrap = output / "install_harness.sh"
    with bootstrap.open("xb") as stream:
        stream.write(files["install_harness.sh"])
    bootstrap.chmod(0o755)
    bootstrap_digest = hashlib.sha256(files["install_harness.sh"]).hexdigest()
    with (output / "SHA256SUMS").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(f"{digest}  {artifact.name}\n{bootstrap_digest}  {bootstrap.name}\n")
    report = {"runtime": "codex", "version": version, "commit": commit, "developmentBuild": commit is None,
              "artifact": str(artifact), "sha256": digest, "bootstrapSha256": bootstrap_digest, "files": len(files)}
    with (output / "build.json").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(build(Path(__file__).resolve().parent, args.output, allow_dirty=args.allow_dirty), indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"build: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
