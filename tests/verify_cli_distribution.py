"""Exercise the built Linux archive and real launcher without a model call."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile


def run(arguments, **kwargs):
    result = subprocess.run(list(map(str, arguments)), capture_output=True, text=True, encoding="utf-8", **kwargs)
    if result.returncode:
        raise AssertionError((arguments, result.returncode, result.stdout, result.stderr))
    return result.stdout


def verify(artifact: Path) -> dict:
    if os.name != "posix":
        return {"status": "not-applicable", "reason": "Linux launcher check requires POSIX"}
    with tempfile.TemporaryDirectory(prefix="harness-cli-smoke-") as temp:
        root = Path(temp)
        source = root / "source"
        source.mkdir()
        with tarfile.open(artifact, "r:gz") as archive:
            for member in archive.getmembers():
                parts = Path(member.name).parts
                assert member.isfile() and not Path(member.name).is_absolute() and ".." not in parts
                path = source / member.name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.extractfile(member).read())
                path.chmod(member.mode)
        sources = list(source.iterdir())
        assert len(sources) == 1
        source = sources[0]
        for entry in (source / "CONTENTS.sha256").read_text().splitlines():
            expected, name = entry.split("  ", 1)
            assert hashlib.sha256((source / name).read_bytes()).hexdigest() == expected
        data, binary, project = root / "tool data", root / "tool bin", root / "project space"
        project.mkdir()
        (project / "README.md").write_text("# Empty research project\n")
        env = os.environ.copy()
        env["HARNESS_NO_UPDATE_CHECK"] = "1"
        run(["bash", source / "install.sh", "--data-dir", data, "--bin-dir", binary, "--auto-update", "off"], env=env)
        executable = binary / "harness"
        version = run([executable, "--version"], env=env).strip()
        assert "Harness for Codex" in version
        assert "init" in run([executable, "--help"], env=env)
        run([executable, "init", "--project", project, "--dry-run"], env=env)
        assert not (project / ".agents").exists()
        assert not (project / ".git").exists()
        run([executable, "init", "--project", project, "--install-only"], env=env)
        installed = project / ".agents/skills/harness"
        assert (installed / "SKILL.md").is_file()
        assert not (project / ".harness/manifest.json").exists()
        before = {p.relative_to(installed).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in installed.rglob("*") if p.is_file()}
        run([executable, "init", "--project", project, "--install-only"], env=env)
        after = {p.relative_to(installed).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in installed.rglob("*") if p.is_file()}
        assert before == after
        assert not (project / ".git").exists()
        return {"status": "passed", "version": version, "archiveChecksums": True,
                "bootstrap": True, "launcher": True, "spacedPaths": True, "dryRunReadOnly": True,
                "installOnly": True, "repeatNoOp": True, "projectGitUntouched": True,
                "liveCodexInvoked": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.archive), indent=2))
