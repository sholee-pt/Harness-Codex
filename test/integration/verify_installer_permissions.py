#!/usr/bin/env python3
"""Compare real installer CLIs on POSIX using pinned baseline/candidate sources.

Run with the harness Conda environment. Only the provided installer is executed;
the update probe is a text data file added to a temporary source copy. Original
checkouts remain unchanged. Windows skips because mode bits do not verify ACLs.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile


COMPONENTS = ("SKILL.md", "scripts", "references", "assets")
SKILL = Path(".agents/skills/harness")
PROBE = "assets/independent-permission-update-probe.txt"
PROBE_DATA = b"Independent installer permission regression fixture.\n"
USER_DATA = b"Preserve this unmanaged private content.\n"
FIXED_MTIME = 1_700_000_000_123_456_789
SOURCE_IGNORED = {".git", "__pycache__", ".harness-install.json"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def version(source: Path) -> str:
    tree = ast.parse((source / SKILL / "scripts/harness_metadata.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "HARNESS_VERSION" for t in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise AssertionError("source lacks a literal HARNESS_VERSION")


def tree_state(root: Path, *, source: bool = False) -> dict:
    result = {}
    for path in (root, *sorted(root.rglob("*"))):
        relative = path.relative_to(root)
        if source and any(part in SOURCE_IGNORED or Path(part).suffix in {".pyc", ".pyo"} for part in relative.parts):
            continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise AssertionError(f"source/fixture contains a link or reparse point: {path}")
        is_directory = stat.S_ISDIR(info.st_mode)
        if not is_directory and not stat.S_ISREG(info.st_mode):
            raise AssertionError(f"unsupported source/fixture entry: {path}")
        result[relative.as_posix()] = {
            "type": "directory" if is_directory else "file",
            "mode": f"{stat.S_IMODE(info.st_mode):04o}",
            "mtimeNs": info.st_mtime_ns,
            "sha256": None if is_directory else sha256(path.read_bytes()),
        }
    return result


def tree_digest(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def source_binding(source: Path) -> dict:
    entries = {}
    for component in COMPONENTS:
        base = source / SKILL / component
        if not base.exists():
            raise AssertionError(f"missing source component: {component}")
        if base.is_dir():
            entries[component] = tree_state(base, source=True)
        else:
            entries[component] = {"sha256": sha256(base.read_bytes()), "mode": f"{stat.S_IMODE(base.stat().st_mode):04o}"}
    return {"version": version(source), "installerSha256": sha256((source / "install.py").read_bytes()),
            "installerImplementationSha256": sha256((source / "harness_cli/project_installer.py").read_bytes()) if (source / "harness_cli/project_installer.py").is_file() else None,
            "payloadTreeSha256": tree_digest(entries), "sourcePath": str(source),
            "generatorRootMode": f"{stat.S_IMODE((source / SKILL).stat().st_mode):04o}"}


def copy_source(source: Path, destination: Path) -> Path:
    destination.mkdir()
    shutil.copy2(source / "install.py", destination / "install.py")
    if (source / "harness_cli/project_installer.py").is_file():
        shutil.copytree(source / "harness_cli", destination / "harness_cli",
                        ignore=shutil.ignore_patterns(*SOURCE_IGNORED, "*.pyc", "*.pyo"))
    (destination / SKILL).mkdir(parents=True)
    for name in COMPONENTS:
        incoming, target = source / SKILL / name, destination / SKILL / name
        if incoming.is_dir():
            shutil.copytree(incoming, target, ignore=shutil.ignore_patterns(*SOURCE_IGNORED, "*.pyc", "*.pyo"))
        else:
            shutil.copy2(incoming, target)
    shutil.copystat(source / SKILL, destination / SKILL)
    assert sha256((destination / "install.py").read_bytes()) == sha256((source / "install.py").read_bytes())
    return destination


def cli(source: Path, project: Path, *, dry_run: bool = False) -> dict:
    command = [sys.executable, "-B", str(source / "install.py"), "--root", str(project)]
    if dry_run:
        command.append("--dry-run")
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if result.returncode != 0:
        raise AssertionError(f"installer CLI failed ({result.returncode}): {result.stdout}\n{result.stderr}")
    report = json.loads(result.stdout)
    assert report["valid"] is True and report["gitMetadataTouched"] is False, report
    assert not report.get("warnings"), report
    return report


def prepare_user_metadata(target: Path) -> None:
    private = target / "private"
    private.mkdir()
    (private / "note.txt").write_bytes(USER_DATA)
    os.chmod(private / "note.txt", 0o640)
    os.utime(private / "note.txt", ns=(FIXED_MTIME, FIXED_MTIME))
    os.chmod(private, 0o700)
    os.utime(private, ns=(FIXED_MTIME, FIXED_MTIME))
    os.chmod(target, 0o750)
    os.utime(target, ns=(FIXED_MTIME, FIXED_MTIME))


def observations(target: Path) -> dict:
    state = tree_state(target)
    return {"root": state["."], "private": state["private"],
            "privateFile": state["private/note.txt"], "managedSkill": state["SKILL.md"],
            "treeSha256": tree_digest(state), "entryCount": len(state)}


def apply_and_check(source: Path, project: Path, *, expected_modes: tuple[str, str], preserve_root: bool) -> dict:
    target = project / SKILL
    before = observations(target)
    before_tree = tree_state(target)
    dry_report = cli(source, project, dry_run=True)
    assert tree_state(target) == before_tree, "dry-run changed the existing generator"
    applied = cli(source, project)
    after = observations(target)
    assert (after["root"]["mode"], after["private"]["mode"]) == expected_modes, after
    assert after["privateFile"] == before["privateFile"], "private file bytes/mode/mtime changed"
    assert after["private"]["mtimeNs"] == before["private"]["mtimeNs"], "private directory mtime changed"
    if preserve_root:
        assert after["root"] == before["root"], "root mode/mtime changed"
    after_tree = tree_state(target)
    repeats = []
    for dry_run in (True, False):
        repeated = cli(source, project, dry_run=dry_run)
        assert repeated["mode"] == "unchanged" and repeated["writes"] == 0 and repeated["removes"] == 0, repeated
        assert repeated.get("directoriesCreated", 0) == 0, repeated
        assert tree_state(target) == after_tree, "no-op changed generator bytes or metadata"
        repeats.append(repeated)
    return {"before": before, "after": after, "dryRun": dry_report, "applied": applied,
            "repeated": repeats, "dryRunUnchanged": True, "noOpUnchanged": True}


def ordinary_update(source: Path, base: Path) -> dict:
    copied = copy_source(source, base / "source")
    project = base / "project"
    project.mkdir()
    initial = cli(copied, project)
    target = project / SKILL
    initial_observation = tree_state(target)["."]
    assert initial_observation["mode"] == f"{stat.S_IMODE((copied / SKILL).stat().st_mode):04o}"
    prepare_user_metadata(target)
    probe = copied / SKILL / PROBE
    assert not probe.exists(), "probe path unexpectedly exists in the supplied source"
    probe.write_bytes(PROBE_DATA)
    result = apply_and_check(copied, project, expected_modes=("0750", "0700"), preserve_root=True)
    assert (target / PROBE).read_bytes() == PROBE_DATA
    result.update({"initialInstall": initial, "initialRoot": initial_observation,
                   "fixtureMutation": {"kind": "new-text-data-file", "path": PROBE, "sha256": sha256(PROBE_DATA)},
                   "installerUnchangedFromSuppliedSource": True, "preparedSourceBinding": source_binding(copied)})
    return result


def cross_version_update(baseline: Path, candidate: Path, base: Path) -> dict:
    project = base / "project"
    project.mkdir()
    initial = cli(baseline, project)
    target = project / SKILL
    prepare_user_metadata(target)
    result = apply_and_check(candidate, project, expected_modes=("0750", "0700"), preserve_root=True)
    receipt = json.loads((target / ".harness-install.json").read_text(encoding="utf-8"))
    assert receipt["generatorVersion"] == version(candidate)
    assert (target / "scripts/harness_metadata.py").read_bytes() == (candidate / SKILL / "scripts/harness_metadata.py").read_bytes()
    result.update({"initialInstall": initial, "installedVersion": receipt["generatorVersion"], "fixtureSourceMutation": None})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.baseline, args.candidate = args.baseline.resolve(), args.candidate.resolve()
    report = {"schemaVersion": 1, "python": sys.version, "platform": sys.platform,
              "status": "running", "posixPermissionsVerified": False, "windowsAclVerified": False}
    code = 0
    try:
        bindings = {"baseline": source_binding(args.baseline), "candidate": source_binding(args.candidate)}
        report["sources"] = bindings
        assert bindings["baseline"]["version"] == "0.22.3-beta", "baseline must be the pinned previous source"
        assert bindings["candidate"]["version"] == "0.23.0-beta", "candidate must be the beta source"
        if os.name != "posix":
            report.update(status="skipped", reason="POSIX directory mode semantics are unavailable; Windows ACL preservation is not verified.")
        else:
            previous_umask = os.umask(0o022)
            try:
                with tempfile.TemporaryDirectory(prefix="harness-permission-crosscheck-") as temporary:
                    base = Path(temporary)
                    for name in ("baseline", "candidate", "upgrade"):
                        (base / name).mkdir()
                    report["umask"] = "0022"
                    report["previousReleaseOrdinaryUpdate"] = ordinary_update(args.baseline, base / "baseline")
                    report["candidateOrdinaryUpdate"] = ordinary_update(args.candidate, base / "candidate")
                    report["actualVersionUpgrade"] = cross_version_update(args.baseline, args.candidate, base / "upgrade")
            finally:
                os.umask(previous_umask)
            assert source_binding(args.baseline) == bindings["baseline"], "original baseline source changed"
            assert source_binding(args.candidate) == bindings["candidate"], "original candidate source changed"
            report.update(status="passed", posixPermissionsVerified=True, originalSourcesUnchanged=True)
    except (AssertionError, OSError, ValueError, subprocess.SubprocessError) as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output), "error": report.get("error")}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
