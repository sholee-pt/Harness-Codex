"""Legacy entry points cannot silently dispatch Codex with a changed environment."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from harness_cli import distribution as dist, environment, main as cli


REPO = Path(__file__).resolve().parents[1]


def snapshot(root):
    return {path.relative_to(root).as_posix(): (
        path.read_bytes() if path.is_file() else None,
        path.stat().st_mtime_ns, path.stat().st_mode & 0o7777,
    ) for path in root.rglob("*")}


class LegacyLauncherGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "tool data"
        source = self.root / "source"
        source.mkdir()
        for name, payload in dist._snapshot(REPO).items():
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        installed = dist.install_tool(source, self.data, self.root / "tool bin",
                                      sys.executable, auto_update="off")
        self.source = Path(installed["sourceRoot"])
        self.launcher = self.data / "launcher.py"
        self.launcher.write_bytes(dist._legacy_launcher_source().encode())
        active_path = self.data / "active.json"
        active = json.loads(active_path.read_bytes())
        active["launchers"][str(self.launcher)] = hashlib.sha256(self.launcher.read_bytes()).hexdigest()
        active_path.write_text(json.dumps(active), encoding="utf-8")
        self.project = self.root / "user project"
        self.project.mkdir()
        (self.project / "README.md").write_bytes(b"# User project\r\n")
        (self.project / ".git").mkdir()
        (self.project / ".git/config").write_bytes(b"User Git metadata\r\n")
        self.caller = {**os.environ, "CONDA_PREFIX": str(self.root / "project environment"),
                       "CONDA_DEFAULT_ENV": "project", "VIRTUAL_ENV": str(self.root / "project venv"),
                       "HARNESS_TOOL_HOME": str(self.data), "HARNESS_NO_UPDATE_CHECK": "1"}
        self.caller.pop(environment.LAUNCHER_MARKER, None)

    def test_real_legacy_readonly_commands_do_not_repair_or_change_files(self):
        before = snapshot(self.root)
        for arguments in (["status"], ["doctor"], ["init", "--dry-run"],
                          ["remove"], ["reset", "--dry-run"]):
            with self.subTest(arguments=arguments):
                completed = subprocess.run(
                    [sys.executable, "-B", str(self.launcher), *arguments,
                     "--project", str(self.project)],
                    capture_output=True, text=True, encoding="utf-8", env=self.caller, timeout=30,
                )
                # Doctor reports the intentionally unconfigured project.
                self.assertEqual(completed.returncode, 1 if arguments[0] == "doctor" else 0,
                                 completed.stdout + completed.stderr)
                self.assertEqual(snapshot(self.root), before)
                if arguments[0] in {"status", "doctor"}:
                    report = json.loads(completed.stdout)
                    self.assertEqual(report["cliLauncher"]["state"], "legacy")
                    self.assertFalse(report["cliLauncher"]["callerEnvironmentPreserved"])
                if arguments[0] == "doctor":
                    self.assertTrue(report["environment"]["harnessCondaEnvironment"])
                    self.assertFalse(report["codexInvoked"])

    def test_legacy_launch_requires_repair_and_a_fresh_preserved_invocation(self):
        arguments = ["start", "--project", str(self.project)]
        project_before = snapshot(self.project)
        with mock.patch.dict(os.environ, self.caller, clear=True), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors, \
                mock.patch.object(cli, "_automatic_update", return_value=None) as automatic, \
                mock.patch.object(cli, "run_project_command", return_value=23) as dispatch:
            before = snapshot(self.root)
            with mock.patch.object(sys.stdin, "isatty", return_value=False), \
                    mock.patch.object(sys.stdout, "isatty", return_value=False):
                self.assertEqual(cli.main(arguments, source_root=self.source), 1)
            self.assertEqual(snapshot(self.root), before)
            self.assertIn("offline repair", errors.getvalue())
            automatic.assert_not_called()
            dispatch.assert_not_called()

            with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                    mock.patch.object(sys.stdout, "isatty", return_value=True):
                self.assertEqual(cli.main(arguments, source_root=self.source), 1)
            self.assertEqual(dist.launcher_status(self.data)["state"], "current")
            self.assertIn("Codex was not started", errors.getvalue())
            automatic.assert_not_called()
            dispatch.assert_not_called()
            self.assertEqual(dict(os.environ), self.caller)

            # Repairing files cannot undo an old launcher's process environment.
            repaired = snapshot(self.root)
            self.assertEqual(cli.main(arguments, source_root=self.source), 1)
            self.assertEqual(snapshot(self.root), repaired)
            self.assertIn("cannot establish preserved caller environment", errors.getvalue())
            dispatch.assert_not_called()
            with mock.patch.dict(os.environ, {environment.LAUNCHER_MARKER: environment.PRESERVED_ENVIRONMENT}):
                self.assertEqual(cli.main(arguments, source_root=self.source), 23)
            dispatch.assert_called_once()
            self.assertEqual(snapshot(self.project), project_before)


class UpdateEnvironmentHandoffTests(unittest.TestCase):
    def test_update_reexec_preserves_present_or_absent_marker_without_fabricating_it(self):
        current_version = cli.version(REPO)
        next_source = REPO.parent / "next-release-fixture"
        args = SimpleNamespace(command="start", dry_run=False, install_only=False, no_update_check=False)
        for preserved in (False, True):
            caller = {**os.environ, "HARNESS_TOOL_HOME": "unused-managed-tool",
                      "CONDA_PREFIX": "/project/environment", "CONDA_DEFAULT_ENV": "project"}
            caller.pop("HARNESS_NO_UPDATE_CHECK", None)
            caller.pop(environment.LAUNCHER_MARKER, None)
            if preserved:
                caller[environment.LAUNCHER_MARKER] = environment.PRESERVED_ENVIRONMENT
            with self.subTest(preserved=preserved), mock.patch.dict(os.environ, caller, clear=True), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                    mock.patch.object(sys.stdin, "isatty", return_value=True), \
                    mock.patch.object(sys.stdout, "isatty", return_value=True), \
                    mock.patch.object(dist, "installed_status", side_effect=[
                        {"auto_update": "compatible"}, {"release_root": str(next_source)}]), \
                    mock.patch.object(dist, "check_due", return_value=True), \
                    mock.patch.object(dist, "mark_check"), \
                    mock.patch.object(dist, "check_update", return_value={
                        "updateAvailable": True, "availableVersion": current_version}), \
                    mock.patch.object(dist, "update_tool"), \
                    mock.patch.object(subprocess, "call", return_value=31) as reexec:
                self.assertEqual(cli._automatic_update(args, REPO, ["start"]), 31)
                self.assertEqual(dict(os.environ), caller)
                self.assertEqual(reexec.call_args.kwargs["env"], {**caller, "HARNESS_NO_UPDATE_CHECK": "1"})


if __name__ == "__main__":
    unittest.main()
