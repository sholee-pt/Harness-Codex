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


def run(arguments, *, timeout=60, **kwargs):
    result = subprocess.run(list(map(str, arguments)), capture_output=True, text=True, encoding="utf-8", timeout=timeout, **kwargs)
    if result.returncode:
        raise AssertionError((arguments, result.returncode, result.stdout, result.stderr))
    return result.stdout


def reject(arguments, expected: str, **kwargs):
    result = subprocess.run(list(map(str, arguments)), capture_output=True, text=True, encoding="utf-8", timeout=60, **kwargs)
    assert result.returncode != 0, (arguments, result.stdout, result.stderr)
    assert expected in result.stderr, (arguments, result.stdout, result.stderr)
    return result


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None,
                                            p.stat().st_mtime_ns, p.stat().st_mode & 0o7777)
            for p in root.rglob("*")}


def report(output: str) -> dict:
    # Preview commands append an explanatory sentence after their JSON report.
    value, _ = json.JSONDecoder().raw_decode(output.lstrip())
    assert isinstance(value, dict)
    return value


def terminal_uninstall(executable: Path, answer: str, env: dict) -> str:
    """Exercise the actual shell command with terminal streams, not mocked input."""
    import pty
    import select
    import time
    master, slave = pty.openpty()
    child = subprocess.Popen([str(executable), 'uninstall'], stdin=slave, stdout=slave, stderr=slave, env=env)
    os.close(slave)
    transcript = b''
    sent = False
    deadline = time.monotonic() + 60
    try:
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.2)[0]:
                try:
                    part = os.read(master, 8192)
                except OSError:
                    break  # PTY closes with EIO after the child exits.
                if not part:
                    break
                transcript += part
                if b'Type yes to uninstall' in transcript and not sent:
                    os.write(master, (answer + '\n').encode())
                    sent = True
            if child.poll() is not None:
                break
        assert sent, transcript
        assert child.wait(timeout=5) == 0, transcript
        return transcript.decode('utf-8')
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)


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
        readme_before = snapshot(project)["README.md"]
        env = os.environ.copy()
        env["HARNESS_NO_UPDATE_CHECK"] = "1"
        home = root / "home"
        home.mkdir()
        env["HOME"] = str(home)
        run(["bash", source / "install.sh", "--agent", "codex", "--data-dir", data,
             "--bin-dir", binary, "--auto-update", "off"], env=env, timeout=900)
        executable = binary / "harness-codex"
        version = run([executable, "--agent", "codex", "--version"], env=env).strip()
        assert "Harness for Codex" in version
        assert run([executable, "--runtime", "codex", "--version"], env=env).strip() == version
        help_text = run([executable, "--help"], env=env)
        assert "init" in help_text and "--agent" not in help_text and "--runtime" not in help_text
        tool_before = snapshot(data)
        project_before = snapshot(project)
        reject([executable, "--agent", "claude", "status", "--project", project], "not implemented", env=env)
        reject([executable, "--runtime", "claude", "status", "--project", project,
                "--agent", "codex"], "Conflicting", env=env)
        assert snapshot(data) == tool_before and snapshot(project) == project_before

        invalid_brief = root / "invalid-brief.md"
        invalid_brief.write_bytes(b"\xff\xfe invalid UTF-8 project brief")
        reject([executable, "init", "--agent", "codex", "--project", project,
                "--goal-file", invalid_brief, "--codex-binary", root / "must-not-launch-codex"],
               "UTF-8", env=env)
        assert snapshot(data) == tool_before and snapshot(project) == project_before
        run([executable, "init", "--agent", "codex", "--project", project, "--dry-run"], env=env)
        assert snapshot(project) == project_before
        assert not (project / ".agents").exists()
        assert not (project / ".git").exists()
        run([executable, "init", "--agent", "codex", "--project", project, "--install-only"], env=env)
        installed = project / ".agents/skills/harness"
        assert (installed / "SKILL.md").is_file()
        assert not (project / ".harness/manifest.json").exists()
        before = snapshot(installed)
        run([executable, "init", "--runtime", "codex", "--project", project, "--install-only"], env=env)
        after = snapshot(installed)
        assert before == after
        assert not (project / ".git").exists()

        # Observe existing Git metadata too, without running Git or configuring a
        # remote. Every lifecycle command must preserve these sentinel bytes.
        git_metadata = project / ".git"
        git_metadata.mkdir()
        (git_metadata / "config").write_text("[core]\n\trepositoryformatversion = 0\n")
        (git_metadata / "HEAD").write_text("ref: refs/heads/user-owned\n")
        git_before = snapshot(git_metadata)
        project_before = snapshot(project)
        status = report(run([executable, "status", "--json", "--agent", "codex", "--project", project], env=env))
        assert status["state"] == "generator-only" and status["generator"] == "installed"
        assert status["harnessPresent"] is False
        assert snapshot(project) == project_before

        for arguments in ([], ["--include-generator"], ["--include-generator", "--yes", "--dry-run"]):
            preview = report(run([executable, "remove", "--json", "--agent", "codex", "--project", project,
                                  *arguments], env=env))
            assert preview["dryRun"] is True and preview["writes"] == 0
            assert preview["gitMetadataTouched"] is False
            assert bool(preview["actions"]) == ("--include-generator" in arguments)
            assert snapshot(project) == project_before

        removed = report(run([executable, "remove", "--json", "--runtime", "codex", "--project", project,
                              "--include-generator", "--yes"], env=env))
        assert removed["state"] == "removed" and removed["dryRun"] is False and removed["writes"] > 0
        assert removed["gitMetadataTouched"] is False
        assert not installed.exists() and not (project / ".harness/manifest.json").exists()
        assert snapshot(git_metadata) == git_before
        assert snapshot(project)["README.md"] == readme_before
        absent_before = snapshot(project)
        absent = report(run([executable, "status", "--json", "--agent", "codex", "--project", project], env=env))
        assert absent["state"] == "absent" and absent["generator"] == "absent"
        assert snapshot(project) == absent_before

        run([executable, "init", "--agent", "codex", "--project", project, "--install-only"], env=env)
        reinstalled = report(run([executable, "status", "--json", "--project", project], env=env))
        assert (installed / "SKILL.md").is_file() and reinstalled["state"] == "generator-only"
        assert snapshot(git_metadata) == git_before
        assert snapshot(project)["README.md"] == readme_before
        assert snapshot(data) == tool_before
        project_before = snapshot(project)
        run([executable, 'uninstall', '--dry-run'], env=env)
        reject([executable, 'uninstall'], 'interactive terminal', input='yes\n', env=env)
        assert 'cancelled' in terminal_uninstall(executable, 'no', env)
        assert snapshot(data) == tool_before
        assert 'Uninstalled harness-codex' in terminal_uninstall(executable, 'yes', env)
        assert not data.exists() and not executable.exists()
        assert snapshot(project) == project_before
        assert '# >>> harness-codex PATH >>>' not in (home / '.bashrc').read_text()
        return {"status": "passed", "version": version, "archiveChecksums": True,
                "bootstrap": True, "launcher": True, "spacedPaths": True, "dryRunReadOnly": True,
                "installOnly": True, "repeatNoOp": True, "projectGitUntouched": True,
                "agentOption": True, "legacyRuntimeAlias": True, "providerConflictRejected": True,
                "invalidMarkdownReadOnly": True, "generatorOnlyStatus": True,
                "removalPreviewReadOnly": True, "ownedGeneratorRemoved": True,
                "absentStatus": True, "reinstallAfterRemoval": True, "userReadmePreserved": True,
                "toolStateUnchangedByProjectCommands": True,
                "nativeTerminalUninstallConfirmed": True, "uninstallKeptProject": True,
                "liveCodexInvoked": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.archive), indent=2))
