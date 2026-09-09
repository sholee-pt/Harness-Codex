"""Versioned source completeness, early rejection, and installation preservation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from harness_cli import distribution as dist
from build import build_release, source as build_source


REPO = Path(__file__).resolve().parents[1]
# Independent fixture of the published v9.2/v9.3 source contract. Do not derive
# it from current required files: doing so could hide a compatibility regression.
LEGACY_FILES = {
    "harness.py", "install.py", "harness_cli/__init__.py", "harness_cli/main.py",
    "harness_cli/project.py", "harness_cli/distribution.py",
    ".agents/skills/harness/SKILL.md", ".agents/skills/harness/scripts/harness_metadata.py",
}


def snapshot(root):
    return {path.relative_to(root).as_posix(): (
        path.read_bytes() if path.is_file() else None,
        path.stat().st_mtime_ns, path.stat().st_mode & 0o7777,
    ) for path in root.rglob("*")}


def write_source(root, contents):
    root.mkdir()
    for name, data in contents.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def contract_source(root, version):
    contents = {name: b"pass\n" if name.endswith(".py") else b"Harness\n" for name in LEGACY_FILES}
    if tuple(map(int, version.split("."))) >= (9, 4):
        contents["harness_cli/lifecycle.py"] = b"pass\n"
    if tuple(map(int, version.split("."))) >= (9, 5):
        contents["harness_cli/environment.py"] = b"pass\n"
    if tuple(map(int, version.split("."))) >= (9, 7):
        contents["harness_cli/shell.py"] = b"pass\n"
        contents["harness_cli/prepare_conda.sh"] = b"# fixture\n"
    if tuple(map(int, version.split("."))) >= (9, 8):
        contents["harness_cli/windows_path.py"] = b"pass\n"
    contents[dist.METADATA] = f'HARNESS_VERSION = "{version}"\n'.encode()
    return write_source(root, contents)


class SourceContractTests(unittest.TestCase):
    def test_current_release_requires_the_native_runtime_cleanup_helper(self):
        source = write_source(self.base / 'missing-cleanup', dist._snapshot(REPO))
        (source / 'harness_cli/runtime_cleanup.ps1').unlink()
        self.assert_rejected_before_writes(source, r'harness_cli/runtime_cleanup\.ps1')

    def test_refactored_source_requires_actual_imported_modules_before_writes(self):
        for name in ("project_installer.py", "paths.py"):
            with self.subTest(module=name):
                source = write_source(self.base / name, dist._snapshot(REPO))
                (source / "harness_cli" / name).unlink()
                self.assert_rejected_before_writes(source, name.replace(".", r"\."))

    def test_absolute_and_relative_transitive_imports_are_checked_without_execution(self):
        imports = ("from .helper import probe", "from . import helper",
                   "import harness_cli.helper", "from harness_cli import helper")
        for index, statement in enumerate(imports):
            with self.subTest(statement=statement):
                source = contract_source(self.base / f"imports-{index}", "9.8")
                (source / "harness_cli/main.py").write_text(statement + "\n", encoding="utf-8")
                (source / "harness_cli/helper.py").write_text("from .missing import probe\n", encoding="utf-8")
                self.assert_rejected_before_writes(source, r"harness_cli/missing\.py")
                (source / "harness_cli/missing.py").write_text("raise RuntimeError('Must never execute during validation')\n", encoding="utf-8")
                before = snapshot(source)
                self.assertEqual(dist._source_info(dist._snapshot(source))[0], "9.8")
                self.assertEqual(snapshot(source), before)

    def test_v98_requires_windows_path_before_install_creates_state(self):
        source = contract_source(self.base / 'source', '9.8')
        (source / 'harness_cli/windows_path.py').unlink()
        self.assert_rejected_before_writes(source, r'harness_cli/windows_path\.py')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def install(self, source, data=None, binary=None):
        return dist.install_tool(source, data or self.base / "tool data",
                                 binary or self.base / "tool bin", sys.executable,
                                 auto_update="off")

    def assert_rejected_before_writes(self, source, missing):
        data, binary = self.base / "tool data", self.base / "tool bin"
        before = snapshot(self.base)
        with mock.patch.object(dist, "_launchers") as launchers, \
                mock.patch.object(dist, "_write_json") as write, \
                mock.patch.object(dist, "_activate") as activate:
            with self.assertRaisesRegex(dist.DistributionError, missing):
                self.install(source, data, binary)
            launchers.assert_not_called()
            write.assert_not_called()
            activate.assert_not_called()
        self.assertEqual(snapshot(self.base), before)
        self.assertFalse(data.exists())
        self.assertFalse(binary.exists())

    def test_v94_and_v95_require_lifecycle_before_install_creates_state(self):
        for version in ("9.4", "9.5"):
            with self.subTest(version=version):
                source = contract_source(self.base / version, version)
                (source / "harness_cli/lifecycle.py").unlink()
                self.assert_rejected_before_writes(source, r"harness_cli/lifecycle\.py")

    def test_v95_requires_environment_before_install_creates_state(self):
        source = contract_source(self.base / "source", "9.5")
        (source / "harness_cli/environment.py").unlink()
        self.assert_rejected_before_writes(source, r"harness_cli/environment\.py")

    def test_legacy_source_and_installation_contracts_remain_valid(self):
        for version in ("9.2", "9.3", "9.4"):
            with self.subTest(version=version):
                source = contract_source(self.base / version, version)
                self.assertFalse((source / "harness_cli/environment.py").exists())
                self.assertEqual((source / "harness_cli/lifecycle.py").exists(), version == "9.4")
                data, binary = self.base / (version + " data"), self.base / (version + " bin")
                installed = self.install(source, data, binary)
                self.assertEqual(installed["version"], version)
                self.assertEqual(installed["schema"], 1)
                receipt = data / "receipts" / (installed["releaseId"] + ".json")
                self.assertEqual(json.loads(receipt.read_bytes())["schema"], 1)
                # Older tools did not always write the additive runtime marker.
                for path in (data / "active.json", receipt):
                    value = json.loads(path.read_bytes())
                    value.pop("runtime", None)
                    path.write_text(json.dumps(value), encoding="utf-8")
                before = snapshot(data)
                self.assertEqual(dist.installed_status(data)["version"], version)
                self.assertEqual(snapshot(data), before)
                self.assertEqual(self.install(source, data, binary)["releaseId"], installed["releaseId"])

    def test_missing_source_file_preserves_user_owned_install_paths(self):
        source = contract_source(self.base / "source", "9.4")
        (source / "harness_cli/lifecycle.py").unlink()
        data, binary = self.base / "tool data", self.base / "tool bin"
        data.mkdir()
        binary.mkdir()
        (data / "notes.txt").write_bytes(b"User-owned data\r\n")
        (binary / "harness").write_bytes(b"User-owned executable\r\n")
        before = snapshot(self.base)
        with self.assertRaisesRegex(dist.DistributionError, "lifecycle"):
            self.install(source, data, binary)
        self.assertEqual(snapshot(self.base), before)

    def test_missing_source_file_preserves_modified_managed_installation(self):
        installed = self.install(contract_source(self.base / "old source", "9.3"))
        (Path(installed["release_root"]) / "harness.py").write_bytes(b"# Preserve this user edit\n")
        candidate = contract_source(self.base / "candidate", "9.5")
        (candidate / "harness_cli/lifecycle.py").unlink()
        before = snapshot(self.base)
        with self.assertRaisesRegex(dist.DistributionError, "lifecycle"):
            self.install(candidate)
        self.assertEqual(snapshot(self.base), before)

    def test_complete_source_still_preserves_modified_managed_installation(self):
        source = contract_source(self.base / "source", "9.5")
        installed = self.install(source)
        (Path(installed["release_root"]) / "harness_cli/lifecycle.py").write_bytes(b"# Local change\n")
        before = snapshot(self.base)
        with self.assertRaisesRegex(dist.DistributionError, "local changes"):
            self.install(source)
        self.assertEqual(snapshot(self.base), before)

    def test_complete_real_source_installs_and_runs_remove_reset_previews(self):
        source = write_source(self.base / "real source", dist._snapshot(REPO))
        installed = self.install(source)
        project = self.base / "user project"
        project.mkdir()
        (project / "README.md").write_bytes(b"# Keep this project\r\n")
        (project / ".git").mkdir()
        (project / ".git/config").write_bytes(b"Git metadata sentinel\n")
        environment = os.environ.copy()
        environment["HARNESS_NO_UPDATE_CHECK"] = "1"
        before = snapshot(self.base)
        for command in ("remove", "reset"):
            with self.subTest(command=command):
                result = subprocess.run(
                    [sys.executable, "-B", str(Path(installed["dataRoot"]) / "launcher.py"),
                     command, "--json", "--agent", "codex", "--project", str(project), "--dry-run"],
                    capture_output=True, text=True, encoding="utf-8", env=environment, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                value, _ = json.JSONDecoder().raw_decode(result.stdout.lstrip())
                self.assertTrue(value["dryRun"])
                self.assertEqual(snapshot(self.base), before)

    def test_development_release_build_rejects_missing_lifecycle_without_output(self):
        source = write_source(self.base / "build source", dist._snapshot(REPO))
        (source / "installer").mkdir()
        for path in (REPO / "installer").iterdir():
            (source / "installer" / path.name).write_bytes(path.read_bytes())
        (source / "harness_cli/lifecycle.py").unlink()
        output = self.base / "build output"
        before = snapshot(self.base)

        def dirty_git(arguments, **kwargs):
            value = "a" * 40 + "\n" if "rev-parse" in arguments else " D harness_cli/lifecycle.py\n"
            return subprocess.CompletedProcess(arguments, 0, value, "")

        with mock.patch.object(build_source.subprocess, "run", side_effect=dirty_git):
            with self.assertRaisesRegex(ValueError, "lifecycle"):
                build_release.build(source, output, allow_dirty=True)
        self.assertFalse(output.exists())
        self.assertEqual(snapshot(self.base), before)


if __name__ == "__main__":
    unittest.main()
