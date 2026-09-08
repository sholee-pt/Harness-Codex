"""Compare the pre-refactor and current builder on identical release inputs.

The baseline contains the actual old builder, not a second implementation of its
expected output. Only its input folder layout is adapted. Real CLI subprocesses
must produce byte-identical archives, bootstraps and checksums. No network used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from build.source import ROOT_DIRS, ROOT_FILES


def run(arguments):
    result = subprocess.run(list(map(str, arguments)), capture_output=True,
                            text=True, encoding="utf-8", timeout=60)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


def verify(baseline):
    with tempfile.TemporaryDirectory(prefix="harness-build-compare-") as temporary:
        base = Path(temporary)
        results = []
        for label, tooling in (("before", "tools"), ("after", "build")):
            root = base / label
            root.mkdir()
            for name in ROOT_FILES:
                destination = name.replace("installer/", "installers/", 1) if label == "before" else name
                target = root / destination
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            for name in ROOT_DIRS:
                shutil.copytree(ROOT / name, root / name,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
            shutil.copytree((baseline if label == "before" else ROOT) / tooling, root / tooling,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
            git = ["git", "-c", "safe.directory=" + root.as_posix(), "-C", str(root)]
            run([*git, "init", "--quiet"])
            # Identical uncommitted payloads deliberately carry no source commit.
            run([*git, "-c", "user.name=Build comparison", "-c", "user.email=fixture@example.invalid",
                 "commit", "--quiet", "--allow-empty", "-m", "Build comparison fixture"])
            before = snapshot(root)
            output = base / (label + " output")
            report = json.loads(run([sys.executable, "-B", root / tooling / "build_release.py",
                                     "--allow-dirty", "--output", output]))
            assert report["developmentBuild"] and report["commit"] is None, report
            assert snapshot(root) == before, "Build changed source files or timestamps"
            results.append((output, report))
        old_output, old_report = results[0]
        new_output, new_report = results[1]
        assert {p.name for p in old_output.iterdir()} == {p.name for p in new_output.iterdir()}
        hashes = {}
        for path in old_output.iterdir():
            if path.name == "build.json":
                continue  # Report paths necessarily identify separate output directories.
            assert path.read_bytes() == (new_output / path.name).read_bytes(), path.name
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        for report in (old_report, new_report):
            for key in ("artifact", "windowsArtifact"):
                report[key] = Path(report[key]).name
        assert old_report == new_report, (old_report, new_report)
        return {"valid": True, "comparison": "identical payloads, real old/new build CLIs",
                "archivesAndInstallersByteIdentical": True, "sourceBytesAndMtimesPreserved": True,
                "normalizedReportsEqual": True, "sha256": hashes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.baseline.resolve())
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
