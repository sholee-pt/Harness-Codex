"""Observe caller/helper/child isolation and recover real launcher interruptions."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import venv
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harness_cli import distribution as dist, environment, main, project
from test_cli_distribution import source, files


OBSERVATION = '''import json,os,shutil,sys
print(json.dumps({"executable":sys.executable,"prefix":sys.prefix,"resolvedPython":shutil.which("python"),
"path":os.environ.get("PATH"),"condaPrefix":os.environ.get("CONDA_PREFIX"),
"condaDefault":os.environ.get("CONDA_DEFAULT_ENV"),"virtualEnv":os.environ.get("VIRTUAL_ENV"),
"codexHome":os.environ.get("CODEX_HOME"),"marker":os.environ.get("HARNESS_LAUNCHER_ENVIRONMENT")}))
'''


class EnvironmentTests(unittest.TestCase):
    def test_main_validates_real_interpreter_without_changing_caller_environment(self):
        for active in (False, True):
            caller = os.environ.copy()
            caller.pop("CONDA_PREFIX", None)
            caller.pop("CONDA_DEFAULT_ENV", None)
            if active:
                caller.update(CONDA_PREFIX="/project/environment with spaces", CONDA_DEFAULT_ENV="project")
            with self.subTest(active=active), mock.patch.dict(os.environ, caller, clear=True):
                before = os.environ.copy()
                main._environment()
                self.assertEqual(dict(os.environ), before)

    def test_actual_helper_uses_harness_python_without_changing_parent(self):
        with mock.patch.dict(os.environ, {"CONDA_PREFIX": "/project/env", "CONDA_DEFAULT_ENV": "project"}):
            before = dict(os.environ)
            helper = environment.helper_environment()
            result = subprocess.run([sys.executable, "-B", "-c", OBSERVATION], env=helper,
                                    capture_output=True, text=True, check=True, timeout=20)
            observed = json.loads(result.stdout)
            self.assertEqual(observed["executable"], sys.executable)
            self.assertEqual(Path(observed["condaPrefix"]), Path(sys.prefix))
            self.assertEqual(observed["condaDefault"], "harness")
            self.assertEqual(Path(observed["resolvedPython"]).resolve(), Path(sys.executable).resolve())
            self.assertEqual(dict(os.environ), before)

    def test_real_codex_substitute_inherits_project_settings_and_not_private_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root / "fake_codex.py"
            output = root / "observation.json"
            fake.write_text(OBSERVATION.replace("print(json.dumps(", "from pathlib import Path\nPath(os.environ['OBSERVATION_FILE']).write_text(json.dumps("), encoding="utf-8")
            caller = {"CONDA_PREFIX": "/project/env", "CONDA_DEFAULT_ENV": "project",
                      "VIRTUAL_ENV": "/project/venv", "CODEX_HOME": "/project/codex-home",
                      environment.LAUNCHER_MARKER: environment.PRESERVED_ENVIRONMENT,
                      "OBSERVATION_FILE": str(output)}
            with mock.patch.dict(os.environ, caller):
                before = dict(os.environ)
                self.assertEqual(project._launch([sys.executable, "-B", str(fake)], root, "inert probe"), 0)
                observed = json.loads(output.read_text())
                self.assertEqual(observed["path"], before["PATH"])
                self.assertEqual(observed["condaPrefix"], before["CONDA_PREFIX"])
                self.assertEqual(observed["condaDefault"], before["CONDA_DEFAULT_ENV"])
                self.assertEqual(observed["virtualEnv"], before["VIRTUAL_ENV"])
                self.assertEqual(observed["codexHome"], before["CODEX_HOME"])
                self.assertIsNone(observed["marker"])
                self.assertEqual(dict(os.environ), before)

    def test_direct_conda_run_caller_state_is_not_reconstructed_or_deactivated(self):
        code = 'from harness_cli.main import _environment; _environment(); ' + OBSERVATION
        observed = subprocess.run([sys.executable, "-B", "-c", code], cwd=REPO,
                                  capture_output=True, text=True, check=True, timeout=20)
        value = json.loads(observed.stdout)
        self.assertEqual(value["condaPrefix"], os.environ.get("CONDA_PREFIX"))
        self.assertEqual(value["condaDefault"], os.environ.get("CONDA_DEFAULT_ENV"))
        self.assertEqual(value["path"], os.environ.get("PATH"))

    def test_managed_release_change_cannot_bypass_caller_environment_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            old, current = data / "releases/old", data / "releases/current"
            args = SimpleNamespace(command="start", dry_run=False)
            with mock.patch.dict(os.environ, {"HARNESS_TOOL_HOME": str(data)}):
                with mock.patch.object(dist, "launcher_status", return_value={"sourceRoot": str(current), "state": "current"}):
                    with self.assertRaisesRegex(ValueError, "active Harness release changed"):
                        main._launcher_environment_gate(args, old)

    def test_codex_substitute_runs_actual_project_python_selected_on_path(self):
        with tempfile.TemporaryDirectory(prefix="h-env-") as temporary:
            root = Path(temporary)
            virtual = root / "project-venv"
            venv.EnvBuilder(with_pip=False).create(virtual)
            binary = virtual / ("Scripts" if os.name == "nt" else "bin")
            output = root / "observed.json"
            fake = root / "codex_probe.py"
            # The Windows substitute itself is Python: CreateProcess may search
            # that parent's executable directory before PATH. Select the PATH
            # executable explicitly there, as the real Codex launcher does.
            # POSIX runs the bare command to observe native PATH search too.
            fake.write_text("import subprocess,os,shutil\nfrom pathlib import Path\n"
                            "options={'executable':shutil.which('python')} if os.name=='nt' else {}\n"
                            "result=subprocess.run(['python','-B','-c'," + repr(OBSERVATION) + "],capture_output=True,text=True,check=True,**options)\n"
                            "Path(os.environ['OBSERVATION_FILE']).write_text(result.stdout)\n", encoding="utf-8")
            caller = os.environ.copy()
            caller.pop("CONDA_PREFIX", None)
            caller.pop("CONDA_DEFAULT_ENV", None)
            caller.update(PATH=str(binary) + os.pathsep + caller.get("PATH", ""),
                          VIRTUAL_ENV=str(virtual), OBSERVATION_FILE=str(output))
            with mock.patch.dict(os.environ, caller, clear=True):
                main._environment()
                self.assertEqual(project._launch([sys.executable, "-B", str(fake)], root, "probe only"), 0)
                child = json.loads(output.read_text())
                self.assertEqual(Path(child["prefix"]).resolve(), virtual.resolve())
                self.assertEqual(Path(child["executable"]).absolute().parent, binary.absolute())
                self.assertEqual(child["virtualEnv"], str(virtual))
                self.assertEqual(child["path"], caller["PATH"])
                self.assertIsNone(child["condaPrefix"])
                helper = subprocess.run([sys.executable, "-B", "-c", OBSERVATION],
                                        env=environment.helper_environment(), capture_output=True,
                                        text=True, check=True, timeout=20)
                observed_helper = json.loads(helper.stdout)
                self.assertEqual(Path(observed_helper["prefix"]).resolve(), Path(sys.prefix).resolve())
                self.assertNotEqual(Path(observed_helper["prefix"]).resolve(), virtual.resolve())
                self.assertEqual(dict(os.environ), caller)


class LauncherEnvironmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = source(self.root / "source")
        self.data, self.bin = self.root / "data", self.root / "bin"
        (self.source / "harness.py").write_text(
            OBSERVATION + "import subprocess\nsubprocess.run([sys.executable,'-B','-c'," + repr(OBSERVATION) + "],check=True)\n",
            encoding="utf-8")
        self.installation = dist.install_tool(self.source, self.data, self.bin, sys.executable)

    def legacy(self):
        launcher = self.data / "launcher.py"
        launcher.write_bytes(dist._legacy_launcher_source().encode())
        active = json.loads((self.data / "active.json").read_bytes())
        active["launchers"][str(launcher)] = hashlib.sha256(launcher.read_bytes()).hexdigest()
        (self.data / "active.json").write_text(json.dumps(active), encoding="utf-8")

    def test_new_launcher_and_inert_child_preserve_active_and_inactive_caller(self):
        for active in (False, True):
            caller = os.environ.copy()
            caller.pop("CONDA_PREFIX", None)
            caller.pop("CONDA_DEFAULT_ENV", None)
            caller["PATH"] = str(self.root / "caller bin") + os.pathsep + caller["PATH"]
            if active:
                caller.update(CONDA_PREFIX=str(self.root / "project env"), CONDA_DEFAULT_ENV="project")
            with self.subTest(active=active):
                process = subprocess.run([sys.executable, "-B", str(self.data / "launcher.py")], env=caller,
                                         capture_output=True, text=True, check=True, timeout=20)
                observations = [json.loads(line) for line in process.stdout.splitlines()]
                self.assertEqual(len(observations), 2)
                for observed in observations:
                    self.assertEqual(observed["path"], caller["PATH"])
                    self.assertEqual(observed["condaPrefix"], caller.get("CONDA_PREFIX"))
                    self.assertEqual(observed["condaDefault"], caller.get("CONDA_DEFAULT_ENV"))
                    self.assertEqual(observed["executable"], sys.executable)
                    self.assertEqual(observed["resolvedPython"], shutil.which("python", path=caller["PATH"]))

    def test_legacy_probe_observably_changes_conda_labels_but_keeps_caller_path(self):
        self.legacy()
        caller = {**os.environ, "CONDA_PREFIX": "/project/env", "CONDA_DEFAULT_ENV": "project"}
        process = subprocess.run([sys.executable, "-B", str(self.data / "launcher.py")], env=caller,
                                 capture_output=True, text=True, check=True, timeout=20)
        for observed in [json.loads(line) for line in process.stdout.splitlines()]:
            self.assertEqual(observed["path"], caller["PATH"])
            self.assertNotEqual(observed["condaPrefix"], caller["CONDA_PREFIX"])
            self.assertEqual(observed["condaDefault"], "harness")

    def test_legacy_status_is_readonly_and_repair_is_idempotent(self):
        self.legacy()
        before = files(self.data)
        self.assertEqual(dist.launcher_status(self.data)["state"], "legacy")
        self.assertEqual(files(self.data), before)
        result = dist.repair_launcher(self.data)
        self.assertTrue(result["repaired"])
        self.assertEqual(dist.launcher_status(self.data)["state"], "current")
        repaired = files(self.data)
        self.assertEqual(dist.repair_launcher(self.data)["state"], "unchanged")
        self.assertEqual(files(self.data), repaired)
        for name, value in before.items():
            if name.startswith(("releases/", "receipts/")):
                self.assertEqual(repaired[name], value)

    def test_edited_owned_launcher_is_preserved_without_creating_migration(self):
        self.legacy()
        (self.data / "launcher.py").write_bytes(b"user launcher edit")
        before = files(self.data)
        with self.assertRaises(ValueError):
            dist.repair_launcher(self.data)
        self.assertEqual(files(self.data), before)

    def test_edit_during_temporary_launcher_write_is_preserved(self):
        self.legacy()
        actual_fsync = os.fsync
        launcher = self.data / "launcher.py"
        edited = False

        def concurrent_edit(descriptor):
            nonlocal edited
            if not edited and list(self.data.glob(".launcher-write-*")):
                edited = True
                launcher.write_bytes(b"user edit during staging")
            return actual_fsync(descriptor)

        with mock.patch.object(dist.os, "fsync", side_effect=concurrent_edit):
            with self.assertRaisesRegex(ValueError, "migration is incomplete"):
                dist.repair_launcher(self.data)
        self.assertTrue(edited)
        self.assertEqual(launcher.read_bytes(), b"user edit during staging")
        self.assertTrue((self.data / ".launcher-migration.json").is_file())
        self.assertFalse(list(self.data.glob(".launcher-write-*")))

    def test_original_update_lock_is_never_reclaimed(self):
        self.legacy()
        lock = self.data / ".install.lock"
        lock.write_bytes(b"123456")
        with self.assertRaisesRegex(ValueError, "another installation"):
            dist.repair_launcher(self.data)
        self.assertEqual(lock.read_bytes(), b"123456")
        self.assertEqual(dist.launcher_status(self.data)["state"], "legacy")

    def fail_metadata_once(self):
        actual = dist._write_json
        def write(path, value):
            if path.name == "active.json":
                raise OSError("injected metadata write failure")
            return actual(path, value)
        with mock.patch.object(dist, "_write_json", side_effect=write):
            with self.assertRaisesRegex(ValueError, "migration is incomplete"):
                dist.repair_launcher(self.data)

    def test_metadata_failure_is_recoverable_without_overwriting_source(self):
        self.legacy()
        before = files(Path(self.installation["sourceRoot"]))
        self.fail_metadata_once()
        self.assertEqual(dist.launcher_status(self.data)["state"], "repair-pending")
        self.assertFalse((self.data / ".install.lock").exists())
        self.assertEqual(dist.repair_launcher(self.data)["state"], "repaired")
        self.assertEqual(files(Path(self.installation["sourceRoot"])), before)

    def test_recovery_preserves_launcher_edits_after_interruption(self):
        self.legacy()
        self.fail_metadata_once()
        (self.data / "launcher.py").write_bytes(b"new user work")
        before = files(self.data)
        with self.assertRaises(ValueError):
            dist.repair_launcher(self.data)
        self.assertEqual(files(self.data), before)

    def test_recovery_rejects_journal_attempt_to_change_unrelated_active_state(self):
        self.legacy()
        self.fail_metadata_once()
        path = self.data / ".launcher-migration.json"
        journal = json.loads(path.read_bytes())
        journal["after"]["repository"] = "https://example.invalid/untrusted.git"
        path.write_text(json.dumps(dist._migration_seal(journal)), encoding="utf-8")
        before = files(self.data)
        with self.assertRaises(ValueError):
            dist.repair_launcher(self.data)
        self.assertEqual(files(self.data), before)

    def test_actual_process_crash_releases_os_lock_and_recovers_only_own_lock(self):
        self.legacy()
        code = '''import os,sys
from pathlib import Path
from harness_cli import distribution as dist
original=dist._write_json
def interrupted(path,value):
    if path.name == 'active.json':
        os._exit(77)
    return original(path,value)
dist._write_json=interrupted
dist.repair_launcher(Path(sys.argv[1]))
'''
        result = subprocess.run([sys.executable, "-B", "-c", code, str(self.data)], cwd=REPO,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 77, result.stderr)
        self.assertTrue((self.data / ".install.lock").exists())
        self.assertEqual(dist.launcher_status(self.data)["state"], "repair-pending")
        self.assertEqual(dist.repair_launcher(self.data)["state"], "repaired")
        self.assertFalse((self.data / ".install.lock").exists())
        self.assertFalse((self.data / ".launcher-migration.json").exists())

    def test_crash_after_journal_removal_recovers_own_install_lock(self):
        self.legacy()
        code = '''import os,sys
from pathlib import Path
from harness_cli import distribution as dist
original=Path.unlink
def interrupted(path,*args,**kwargs):
    result=original(path,*args,**kwargs)
    if path.name == '.launcher-migration.json':
        os._exit(78)
    return result
Path.unlink=interrupted
dist.repair_launcher(Path(sys.argv[1]))
'''
        result = subprocess.run([sys.executable, "-B", "-c", code, str(self.data)], cwd=REPO,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertTrue((self.data / ".install.lock").exists())
        self.assertFalse((self.data / ".launcher-migration.json").exists())
        self.assertEqual(dist.launcher_status(self.data)["state"], "repair-pending")
        dist.repair_launcher(self.data)
        self.assertFalse((self.data / ".install.lock").exists())
        self.assertEqual(dist.launcher_status(self.data)["state"], "current")

    def test_old_payload_never_receives_preserved_marker_even_if_inherited(self):
        caller = {**os.environ, environment.LAUNCHER_MARKER: environment.PRESERVED_ENVIRONMENT}
        result = subprocess.run([sys.executable, "-B", str(self.data / "launcher.py")], env=caller,
                                capture_output=True, text=True, check=True, timeout=20)
        self.assertEqual(self.installation["version"], "9.2")
        for observed in [json.loads(line) for line in result.stdout.splitlines()]:
            self.assertIsNone(observed["marker"])

    def test_current_payload_receives_marker_after_launcher_integrity_checks(self):
        candidate = source(self.root / "candidate", "9.5", "b" * 40)
        for minimum, required in dist.VERSION_REQUIRED:
            if minimum <= (9, 5):
                for name in required:
                    (candidate / name).write_text("pass\n", encoding="utf-8")
        (candidate / "harness.py").write_text(OBSERVATION, encoding="utf-8")
        dist.install_tool(candidate, self.data, self.bin, sys.executable)
        result = subprocess.run([sys.executable, "-B", str(self.data / "launcher.py")],
                                capture_output=True, text=True, check=True, timeout=20)
        self.assertEqual(json.loads(result.stdout)["marker"], environment.PRESERVED_ENVIRONMENT)

    def test_reinstall_repairs_an_older_owned_launcher(self):
        self.legacy()
        dist.install_tool(self.source, self.data, self.bin, sys.executable)
        self.assertEqual(dist.launcher_status(self.data)["state"], "current")


if __name__ == "__main__":
    unittest.main()
