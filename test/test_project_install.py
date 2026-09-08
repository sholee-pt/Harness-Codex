"""Observe project-local generator ownership, no-op updates, and rollback."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from harness_cli import project_installer as installer


def state(root):
    return {
        path.relative_to(root).as_posix(): (None if path.is_dir() else path.read_bytes(), path.stat().st_mtime_ns, stat.S_IMODE(path.stat().st_mode))
        for path in root.rglob("*")
    }


def directory_metadata(path):
    info = path.stat()
    return stat.S_IMODE(info.st_mode), info.st_mtime_ns


class ProjectInstallTests(unittest.TestCase):
    def test_legacy_entrypoint_from_copied_source_is_readonly_without_python_flags(self):
        release = self.base / "copied release"
        (release / "harness_cli").mkdir(parents=True)
        for name in ("install.py", "harness_cli/__init__.py", "harness_cli/project_installer.py"):
            shutil.copyfile(REPO_ROOT / name, release / name)
        shutil.copytree(self.source, release / ".agents/skills/harness")
        environment = os.environ.copy()
        environment.pop("PYTHONDONTWRITEBYTECODE", None)
        before = state(self.base)
        process = subprocess.run([sys.executable, str(release / "install.py"), "--root", str(self.root), "--dry-run"],
                                 cwd=self.base, env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        report = json.loads(process.stdout)
        self.assertTrue(report["valid"] and report["dryRun"])
        self.assertEqual(report["generatorVersion"], "8.1")
        self.assertEqual(state(self.base), before)

    def test_release_loader_uses_selected_source_and_default_generator_path(self):
        for label in ("first", "second", "first"):
            release = self.base / label
            if not release.exists():
                (release / "harness_cli").mkdir(parents=True)
                text = (REPO_ROOT / "harness_cli/project_installer.py").read_text(encoding="utf-8")
                (release / "harness_cli/project_installer.py").write_text(text + f'\nRELEASE_SENTINEL = "{label}"\n', encoding="utf-8")
                shutil.copytree(self.source, release / ".agents/skills/harness")
            before = state(self.base)
            selected = installer.load_installer(release)
            self.addCleanup(sys.modules.pop, selected.__name__, None)
            self.assertEqual(selected.RELEASE_SENTINEL, label)
            self.assertEqual(Path(selected.__file__).parent.parent, release)
            result = selected.install(self.root, dry_run=True)
            self.assertEqual(result["generatorVersion"], "8.1")
            self.assertTrue(result["valid"])
            self.assertEqual(state(self.base), before)

    def test_missing_selected_installer_never_falls_back_to_loaded_release(self):
        before = state(self.base)
        with self.assertRaises(FileNotFoundError):
            installer.load_installer(self.base / "missing release")
        self.assertEqual(state(self.base), before)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "source"
        self.source.mkdir()
        for name in installer.COMPONENTS[1:]:
            (self.source / name).mkdir()
        (self.source / "SKILL.md").write_text("---\nname: harness\n---\nInstructions\n", encoding="utf-8")
        (self.source / "scripts/harness_metadata.py").write_text('HARNESS_VERSION = "8.1"\n', encoding="utf-8")
        (self.source / "references/readme.md").write_text("original", encoding="utf-8")
        (self.source / "assets/template.md").write_text("template", encoding="utf-8")
        self.root = self.base / "project"
        self.root.mkdir()
        self.target = self.root / ".agents/skills/harness"

    def install(self, **kwargs):
        return installer.install(self.root, source=self.source, **kwargs)

    def link(self, target, path, *, directory=False):
        try:
            path.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            self.skipTest(f"symlink creation is unavailable: {exc}")

    def test_dry_run_install_and_repeated_install_preserve_bytes_and_mtimes(self):
        (self.root / "README.md").write_text("user project")
        before = state(self.root)
        planned = self.install(dry_run=True)
        self.assertEqual(planned["mode"], "install")
        self.assertGreater(planned["writes"], 0)
        self.assertEqual(state(self.root), before)
        applied = self.install()
        self.assertEqual(applied["writes"], planned["writes"])
        self.assertFalse(applied["gitMetadataTouched"])
        self.assertFalse((self.root / ".harness").exists())
        self.assertEqual((self.target / "SKILL.md").read_bytes(), (self.source / "SKILL.md").read_bytes())
        after = state(self.root)
        for dry_run in (True, False):
            report = self.install(dry_run=dry_run)
            self.assertEqual(report["writes"], 0)
            self.assertEqual(report["removes"], 0)
            self.assertEqual(state(self.root), after)

    def test_git_and_multiple_nested_git_metadata_are_never_touched(self):
        for prefix in ("", "one/", "two/"):
            git = self.root / prefix / ".git"
            git.mkdir(parents=True)
            (git / "config").write_text("sentinel remote configuration")
        before = {name: value for name, value in state(self.root).items() if ".git" in name}
        self.install()
        after = {name: value for name, value in state(self.root).items() if ".git" in name}
        self.assertEqual(before, after)

    def test_selected_root_inside_git_metadata_is_refused_without_writes(self):
        root = self.root / ".GiT/objects"
        root.mkdir(parents=True)
        (root / "sentinel").write_text("keep metadata")
        before = state(self.root)
        for selected in (root, root.parent):
            for dry_run in (True, False):
                with self.assertRaisesRegex(installer.InstallError, "Git metadata"):
                    installer.install(selected, source=self.source, dry_run=dry_run)
                self.assertEqual(state(self.root), before)

    def test_safe_update_removes_only_owned_files_and_preserves_unmanaged_content(self):
        self.install()
        (self.target / "notes.txt").write_text("user notes")
        (self.target / "references/user.md").write_text("user documentation")
        preserved = {name: value for name, value in state(self.target).items() if name in {"notes.txt", "references/user.md", "SKILL.md"}}
        (self.source / "references/readme.md").unlink()
        (self.source / "scripts/harness_metadata.py").write_text('HARNESS_VERSION = "next-test-release"\n')
        (self.source / "assets/template.md").write_text("updated template")
        (self.source / "references/new.md").write_text("new documentation")
        before = state(self.root)
        planned = self.install(dry_run=True)
        self.assertEqual(state(self.root), before)
        self.assertEqual(planned["removes"], 1)
        report = self.install()
        self.assertEqual(report["mode"], "update")
        self.assertFalse((self.target / "references/readme.md").exists())
        self.assertEqual((self.target / "assets/template.md").read_text(), "updated template")
        self.assertEqual({name: state(self.target)[name] for name in preserved}, preserved)
        receipt = json.loads((self.target / installer.RECEIPT).read_text())
        self.assertEqual(receipt["generatorVersion"], "next-test-release")
        self.assertNotIn("notes.txt", receipt["files"])
        self.assertEqual(self.install()["writes"], 0)

    def test_unmanaged_destination_is_refused_even_if_source_bytes_match(self):
        self.target.mkdir(parents=True)
        (self.target / "SKILL.md").write_bytes((self.source / "SKILL.md").read_bytes())
        before = state(self.root)
        for dry_run in (True, False):
            with self.assertRaisesRegex(installer.InstallError, "unmanaged destination"):
                self.install(dry_run=dry_run)
            self.assertEqual(state(self.root), before)

    def test_modified_or_missing_managed_file_is_preserved(self):
        self.install()
        managed = self.target / "SKILL.md"
        for change in (lambda: managed.write_text("user edit"), managed.unlink):
            change()
            before = state(self.root)
            for dry_run in (True, False):
                with self.assertRaisesRegex(installer.InstallError, "modified or removed"):
                    self.install(dry_run=dry_run)
                self.assertEqual(state(self.root), before)

    def test_new_source_file_cannot_claim_existing_user_file(self):
        self.install()
        (self.target / "references/user.md").write_text("user-owned")
        (self.source / "references/user.md").write_text("user-owned")
        before = state(self.root)
        with self.assertRaisesRegex(installer.InstallError, "unmanaged path"):
            self.install()
        self.assertEqual(state(self.root), before)

    def test_receipt_traversal_and_invalid_schema_cannot_escape_destination(self):
        self.install()
        receipt_path = self.target / installer.RECEIPT
        original = json.loads(receipt_path.read_text())
        for name in ("../../outside.txt", "/outside.txt", "scripts/../../outside.txt", "scripts\\outside.txt", "scripts/./outside.txt", "scripts/.. /outside.txt", "scripts/file:stream", "scripts/CON.txt", "scripts/name.", ".git/config", installer.RECEIPT):
            with self.subTest(name=name):
                changed = dict(original, files=dict(original["files"]))
                changed["files"][name] = "0" * 64
                receipt_path.write_text(json.dumps(changed))
                before = state(self.root)
                with self.assertRaises(installer.InstallError):
                    self.install()
                self.assertEqual(state(self.root), before)
        receipt_path.write_text(json.dumps(dict(original, schemaVersion=True)))
        with self.assertRaisesRegex(installer.InstallError, "schema"):
            self.install()

    def test_source_caches_and_metadata_are_not_distributed(self):
        for folder in ("scripts/__pycache__", "scripts/.git"):
            (self.source / folder).mkdir()
            (self.source / folder / "ignored").write_text("excluded")
        (self.source / "scripts/ignored.pyc").write_bytes(b"cache")
        (self.source / installer.RECEIPT).write_text("unrelated metadata")
        self.install()
        self.assertFalse((self.target / "scripts/__pycache__").exists())
        self.assertFalse((self.target / "scripts/.git").exists())
        self.assertFalse((self.target / "scripts/ignored.pyc").exists())
        self.assertEqual(json.loads((self.target / installer.RECEIPT).read_text())["schemaVersion"], 1)

    def test_source_destination_and_parent_symlinks_are_refused(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "sentinel.txt").write_text("keep")
        self.link(outside, self.source / "references/link", directory=True)
        with self.assertRaisesRegex(installer.InstallError, "symlink"):
            self.install()
        (self.source / "references/link").unlink()
        self.link(outside, self.root / ".agents", directory=True)
        with self.assertRaisesRegex(installer.InstallError, "symlink"):
            self.install()
        (self.root / ".agents").unlink()
        self.install()
        self.link(outside / "sentinel.txt", self.target / "user-link")
        with self.assertRaisesRegex(installer.InstallError, "symlink"):
            self.install()
        self.assertEqual((outside / "sentinel.txt").read_text(), "keep")

    def test_source_equal_destination_is_a_receipt_free_no_op(self):
        before = state(REPO_ROOT / ".agents/skills/harness")
        report = installer.install(REPO_ROOT, dry_run=False)
        self.assertEqual(report["mode"], "self")
        self.assertEqual(report["writes"], 0)
        self.assertEqual(state(REPO_ROOT / ".agents/skills/harness"), before)

    def test_failed_initial_promotion_removes_staging_and_new_parent_folders(self):
        before = state(self.root)
        with mock.patch.object(installer.os, "replace", side_effect=OSError("injected promotion failure")):
            with self.assertRaisesRegex(OSError, "injected"):
                self.install()
        self.assertEqual(state(self.root), before)

    def test_failed_update_promotion_restores_original_files(self):
        self.install()
        (self.target / "notes.txt").write_text("user notes")
        (self.source / "SKILL.md").write_text("updated")
        before = state(self.target)
        original_replace = os.replace

        def fail_promotion(source, destination):
            if Path(source).name.startswith(".harness-install-stage-"):
                raise OSError("injected promotion failure")
            return original_replace(source, destination)

        with mock.patch.object(installer.os, "replace", side_effect=fail_promotion):
            with self.assertRaisesRegex(OSError, "injected"):
                self.install()
        self.assertEqual(state(self.target), before)
        self.assertEqual(sorted(path.name for path in self.target.parent.iterdir()), ["harness"])

    def test_destination_change_during_staging_is_preserved_and_refused(self):
        self.install()
        (self.source / "SKILL.md").write_text("updated")
        original_populate = installer.populate

        def concurrent_edit(folder, entries):
            original_populate(folder, entries)
            (self.target / "SKILL.md").write_text("concurrent user edit")

        with mock.patch.object(installer, "populate", side_effect=concurrent_edit):
            with self.assertRaisesRegex(installer.InstallError, "changed during preparation"):
                self.install()
        self.assertEqual((self.target / "SKILL.md").read_text(), "concurrent user edit")
        self.assertEqual(sorted(path.name for path in self.target.parent.iterdir()), ["harness"])

    def test_destination_root_mtime_change_during_staging_is_preserved_and_refused(self):
        self.install()
        (self.source / "SKILL.md").write_text("updated")
        before = state(self.target)
        original_populate = installer.populate
        changed_mtime = self.target.stat().st_mtime_ns - 2_000_000_000

        def concurrent_edit(folder, entries):
            original_populate(folder, entries)
            os.utime(self.target, ns=(changed_mtime, changed_mtime))

        with mock.patch.object(installer, "populate", side_effect=concurrent_edit):
            with self.assertRaisesRegex(installer.InstallError, "changed during preparation"):
                self.install()
        self.assertEqual(state(self.target), before)
        self.assertEqual(self.target.stat().st_mtime_ns, changed_mtime)
        self.assertEqual(sorted(path.name for path in self.target.parent.iterdir()), ["harness"])

    @unittest.skipUnless(os.name == "posix", "requires POSIX directory permission semantics")
    def test_directory_modes_survive_initial_install_update_and_repeat(self):
        os.chmod(self.source, 0o751)
        os.chmod(self.source / "references", 0o500)
        os.chmod(self.source / "scripts", 0o750)
        source_root_metadata = directory_metadata(self.source)
        self.install()
        self.assertEqual(directory_metadata(self.target), source_root_metadata)
        self.assertEqual(stat.S_IMODE((self.target / "references").stat().st_mode), 0o500)
        self.assertEqual(stat.S_IMODE((self.target / "scripts").stat().st_mode), 0o750)
        private = self.target / "private"
        private.mkdir()
        (private / "empty").mkdir()
        (private / "note.txt").write_text("user-owned private file")
        os.chmod(private / "empty", 0o500)
        os.chmod(private, 0o500)
        os.chmod(self.target / "assets", 0o710)
        os.chmod(self.target, 0o750)
        preserved_root = directory_metadata(self.target)
        preserved = state(self.target)
        (self.source / "SKILL.md").write_text("updated")
        new_directory = self.source / "assets/new"
        new_directory.mkdir()
        (new_directory / "nested").mkdir()
        (new_directory / "nested/new.txt").write_text("new asset")
        os.chmod(new_directory / "nested", 0o500)
        os.chmod(new_directory, 0o550)
        before = state(self.target)
        self.install(dry_run=True)
        self.assertEqual(state(self.target), before)
        self.assertEqual(directory_metadata(self.target), preserved_root)
        report = self.install()
        self.assertEqual(report["mode"], "update")
        self.assertEqual(report["warnings"], [])
        self.assertEqual(directory_metadata(self.target), preserved_root)
        for name in ("private", "private/empty", "private/note.txt", "references", "assets", "scripts"):
            self.assertEqual(state(self.target)[name], preserved[name], name)
        self.assertEqual(stat.S_IMODE((self.target / "assets/new").stat().st_mode), 0o550)
        self.assertEqual(stat.S_IMODE((self.target / "assets/new/nested").stat().st_mode), 0o500)
        self.assertEqual((self.target / "assets/new/nested/new.txt").read_text(), "new asset")
        after = state(self.target)
        repeated = self.install()
        self.assertEqual((repeated["writes"], repeated["removes"], repeated["directoriesCreated"]), (0, 0, 0))
        self.assertEqual(state(self.target), after)
        self.assertEqual(directory_metadata(self.target), preserved_root)
        self.assertEqual(sorted(path.name for path in self.target.parent.iterdir()), ["harness"])

    @unittest.skipUnless(os.name == "posix", "requires POSIX directory permission semantics")
    def test_new_empty_directory_is_installed_without_changing_existing_directory_modes(self):
        self.install()
        os.chmod(self.target / "references", 0o500)
        existing_root = directory_metadata(self.target)
        before = state(self.target)
        new_directory = self.source / "references/empty"
        new_directory.mkdir()
        os.chmod(new_directory, 0o500)
        planned = self.install(dry_run=True)
        self.assertEqual(planned["writes"], 0)
        self.assertEqual(planned["directoriesCreated"], 1)
        self.assertEqual(state(self.target), before)
        applied = self.install()
        self.assertEqual(applied["mode"], "update")
        self.assertEqual(applied["warnings"], [])
        self.assertTrue((self.target / "references/empty").is_dir())
        self.assertEqual(stat.S_IMODE((self.target / "references/empty").stat().st_mode), 0o500)
        self.assertEqual(stat.S_IMODE((self.target / "references").stat().st_mode), 0o500)
        self.assertEqual(directory_metadata(self.target), existing_root)
        after = state(self.target)
        repeated = self.install()
        self.assertEqual((repeated["mode"], repeated["writes"], repeated["directoriesCreated"]), ("unchanged", 0, 0))
        self.assertEqual(state(self.target), after)

    @unittest.skipUnless(os.name == "posix", "requires POSIX directory permission semantics")
    def test_destination_root_mode_change_during_staging_is_preserved_and_refused(self):
        self.install()
        os.chmod(self.target, 0o755)
        before = state(self.target)
        original_root_mtime = self.target.stat().st_mtime_ns
        (self.source / "SKILL.md").write_text("updated")
        original_populate = installer.populate

        def concurrent_edit(folder, entries):
            original_populate(folder, entries)
            os.chmod(self.target, 0o700)

        with mock.patch.object(installer, "populate", side_effect=concurrent_edit):
            with self.assertRaisesRegex(installer.InstallError, "changed during preparation"):
                self.install()
        self.assertEqual(directory_metadata(self.target), (0o700, original_root_mtime))
        self.assertEqual(state(self.target), before)
        self.assertEqual(sorted(path.name for path in self.target.parent.iterdir()), ["harness"])

    @unittest.skipUnless(os.name == "posix", "requires POSIX directory permission semantics")
    def test_failed_update_with_restrictive_modes_restores_root_and_nested_directories(self):
        self.install()
        private = self.target / "private"
        private.mkdir()
        (private / "note.txt").write_text("preserve user content")
        os.chmod(private, 0o500)
        os.chmod(self.target / "assets", 0o500)
        os.chmod(self.target, 0o550)
        (self.source / "SKILL.md").write_text("updated")
        before_root = directory_metadata(self.target)
        before = state(self.target)
        original_replace = os.replace

        def fail_promotion(source, destination):
            if Path(source).name.startswith(".harness-install-stage-"):
                raise OSError("injected promotion failure")
            return original_replace(source, destination)

        with mock.patch.object(installer.os, "replace", side_effect=fail_promotion):
            with self.assertRaisesRegex(OSError, "injected promotion failure"):
                self.install()
        self.assertEqual(state(self.target), before)
        self.assertEqual(directory_metadata(self.target), before_root)
        self.assertEqual(sorted(path.name for path in self.target.parent.iterdir()), ["harness"])

    def test_real_cli_copies_current_source_and_reports_errors_as_json(self):
        command = [sys.executable, "-B", str(REPO_ROOT / "install.py"), "--root", str(self.root)]
        before = state(self.root)
        dry_run = subprocess.run(command + ["--dry-run"], capture_output=True, text=True)
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        self.assertTrue(json.loads(dry_run.stdout)["valid"])
        self.assertEqual(state(self.root), before)
        applied = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        after = state(self.root)
        repeat = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(json.loads(repeat.stdout)["writes"], 0)
        self.assertEqual(state(self.root), after)
        (self.target / "SKILL.md").write_text("user edit")
        before_error = state(self.root)
        refused = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(refused.returncode, 2)
        self.assertFalse(json.loads(refused.stdout)["valid"])
        self.assertEqual(state(self.root), before_error)


if __name__ == "__main__":
    unittest.main()
