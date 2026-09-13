"""Exercise owned deletion, byte-preserving pointers, and interrupted recovery."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harness_cli import lifecycle
from test_harness_tools import (
    harness_apply, harness_metadata, harness_state, harness_transaction,
    minimal_plan, validate_harness,
)


def files(root):
    return {path.relative_to(root).as_posix(): (
        path.read_bytes(), stat.S_IMODE(path.stat().st_mode), path.stat().st_mtime_ns,
    ) for path in root.rglob("*") if path.is_file()}


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "project with spaces"
        self.root.mkdir()

    def generate(self):
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))

    def install(self):
        lifecycle._helpers(REPO)[0].install(self.root, source=REPO / lifecycle.GENERATOR)

    def remove(self, **kwargs):
        return lifecycle.remove_project(self.root, source_root=REPO, **kwargs)

    def recover(self, **kwargs):
        return lifecycle.recover_removal(self.root, source_root=REPO, **kwargs)

    def read_manifest(self):
        return json.loads((self.root / ".harness/manifest.json").read_bytes())

    def write_manifest(self, manifest):
        (self.root / ".harness/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def interrupt(self, *, rollback_fails=True, destination_index=1):
        original = os.replace
        failed = False

        def replace(source, destination):
            nonlocal failed
            source, destination = Path(source), Path(destination)
            if destination.name == f"backup-{destination_index:06d}" and not failed:
                failed = True
                raise OSError("injected move interruption")
            if rollback_fails and failed and source.name.startswith("backup-"):
                raise OSError("injected rollback interruption")
            return original(source, destination)

        with mock.patch.object(lifecycle.os, "replace", side_effect=replace):
            with self.assertRaises(lifecycle.LifecycleError):
                self.remove(dry_run=False)

    def test_missing_harness_is_explicit_noop_without_directories(self):
        before = list(self.root.iterdir())
        self.assertEqual(self.remove(dry_run=False)["state"], "unchanged")
        self.assertEqual(self.recover(dry_run=False)["state"], "unchanged")
        self.assertEqual(lifecycle.removal_status(self.root, source_root=REPO)["state"], "none")
        self.assertEqual(list(self.root.iterdir()), before)

    def test_default_preview_preserves_all_files_and_metadata(self):
        self.generate()
        before = files(self.root)
        result = self.remove()
        self.assertTrue(result["dryRun"])
        self.assertEqual(result["state"], "preview")
        self.assertEqual(result["writes"], 0)
        self.assertEqual(len(result["actions"]), 3)
        self.assertEqual(files(self.root), before)

    def test_remove_preserves_generator_user_files_and_git_metadata(self):
        self.install()
        self.generate()
        (self.root / ".git").mkdir()
        (self.root / ".git/config").write_bytes(b"user-owned git configuration\r\n")
        user = self.root / ".agents/skills/project-harness/notes.txt"
        user.write_bytes(b"user notes")
        before = files(self.root)
        result = self.remove(dry_run=False)
        self.assertEqual(result["state"], "removed")
        self.assertFalse(result["gitMetadataTouched"])
        self.assertFalse((self.root / ".harness/manifest.json").exists())
        self.assertFalse((self.root / ".agents/skills/project-harness/SKILL.md").exists())
        for name, value in before.items():
            if name.startswith(lifecycle.GENERATOR + "/") or name in {".git/config", "pyproject.toml", user.relative_to(self.root).as_posix()}:
                self.assertEqual(files(self.root)[name], value)
        self.assertNotIn(harness_state.BEGIN_MARKER.encode(), (self.root / "AGENTS.md").read_bytes())
        self.assertFalse((self.root / lifecycle.JOURNAL).exists())

    def test_pointer_removal_preserves_outside_bytes_crlf_and_mtime(self):
        self.generate()
        pointer = self.root / "AGENTS.md"
        block = harness_state.extract_managed_block(pointer.read_text()).replace("\n", "\r\n").encode()
        prefix, suffix = b"# User instructions\r\n\r\n", b"\r\nKeep this ending.\r\n"
        pointer.write_bytes(prefix + block + suffix)
        before = pointer.stat()
        self.remove(dry_run=False)
        self.assertEqual(pointer.read_bytes(), prefix + suffix)
        self.assertEqual(pointer.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(stat.S_IMODE(pointer.stat().st_mode), stat.S_IMODE(before.st_mode))

    def test_user_owned_explicit_skill_instruction_is_untouched(self):
        pointer = self.root / 'AGENTS.md'
        for content in (b'# User instructions\r\nDo not replace these.\r\n', b'No final newline', b''):
            pointer.write_bytes(content)
            self.generate()
            self.remove(dry_run=False)
            self.assertEqual(pointer.read_bytes(), content)

    def test_include_generator_removes_only_receipt_owned_files(self):
        self.install()
        self.generate()
        generator = self.root / lifecycle.GENERATOR
        extra = generator / "scripts/__pycache__/user.pyc"
        extra.parent.mkdir()
        extra.write_bytes(b"user cache")
        notes = generator / "references/notes.txt"
        notes.write_bytes(b"unlisted notes")
        before = {name: value for name, value in files(self.root).items() if name.endswith(("user.pyc", "notes.txt"))}
        result = self.remove(include_generator=True, dry_run=False)
        self.assertEqual(result["state"], "removed")
        self.assertEqual(result["retainedGeneratorFiles"], ["references/notes.txt", "scripts/__pycache__/user.pyc"])
        self.assertIn("before reinstalling", result["warning"])
        self.assertFalse((generator / ".harness-install.json").exists())
        self.assertFalse((generator / "SKILL.md").exists())
        for name, value in before.items():
            self.assertEqual(files(self.root)[name], value)

    def test_generator_only_removal_supports_clean_reinstall(self):
        self.install()
        self.assertFalse((self.root / ".harness").exists())
        self.assertEqual(self.remove(include_generator=True, dry_run=False)["state"], "removed")
        self.assertFalse((self.root / lifecycle.GENERATOR).exists())
        self.assertFalse((self.root / ".harness").exists())
        self.install()
        self.assertTrue((self.root / lifecycle.GENERATOR / "SKILL.md").is_file())

    def test_stale_and_deleted_source_evidence_do_not_change_owned_deletion(self):
        for deleted in (False, True):
            with self.subTest(deleted=deleted):
                (self.root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
                self.generate()
                source = self.root / "pyproject.toml"
                source.unlink() if deleted else source.write_text("changed project source", encoding="utf-8")
                self.assertEqual(self.remove(dry_run=False)["state"], "removed")

    def test_all_supported_v9_release_manifests_can_be_removed(self):
        for version in sorted(harness_metadata.ARTIFACT_COMPATIBLE_GENERATOR_VERSIONS):
            with self.subTest(version=version):
                self.generate()
                manifest = self.read_manifest()
                manifest["generator"]["version"] = version
                self.write_manifest(manifest)
                self.assertEqual(self.remove(dry_run=False)["state"], "removed")

    def test_modified_managed_file_refuses_every_deletion(self):
        self.install()
        self.generate()
        (self.root / ".agents/skills/project-harness/SKILL.md").write_text("user edit", encoding="utf-8")
        before = files(self.root)
        with self.assertRaises(ValueError):
            self.remove(include_generator=True, dry_run=False)
        self.assertEqual(files(self.root), before)

    @unittest.skipIf(os.name == "nt", "Windows permission bits do not express POSIX ownership modes")
    def test_modified_managed_mode_refuses_every_deletion(self):
        self.generate()
        (self.root / ".agents/skills/project-harness/SKILL.md").chmod(0o600)
        before = files(self.root)
        with self.assertRaises(ValueError):
            self.remove(dry_run=False)
        self.assertEqual(files(self.root), before)

    def test_modified_generator_refuses_before_generated_files_are_removed(self):
        self.install()
        self.generate()
        (self.root / lifecycle.GENERATOR / "SKILL.md").write_bytes(b"user generator edit")
        before = files(self.root)
        with self.assertRaises(ValueError):
            self.remove(include_generator=True, dry_run=False)
        self.assertEqual(files(self.root), before)

    def test_future_contract_runtime_and_malformed_manifest_fail_closed(self):
        self.generate()
        original = self.read_manifest()
        for key, value in (("artifactContractVersion", 900), ("schemaVersion", 900), ("runtime", "claude"), ("managedFiles", "invalid")):
            with self.subTest(key=key):
                altered = json.loads(json.dumps(original))
                if key == "runtime":
                    altered["generator"][key] = value
                else:
                    altered[key] = value
                self.write_manifest(altered)
                before = files(self.root)
                with self.assertRaises(ValueError):
                    self.remove(dry_run=False)
                self.assertEqual(files(self.root), before)

    def test_generator_receipt_unknown_version_is_not_accepted(self):
        self.install()
        receipt_path = self.root / lifecycle.GENERATOR / ".harness-install.json"
        receipt = json.loads(receipt_path.read_bytes())
        receipt["generatorVersion"] = "999.0"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        before = files(self.root)
        with self.assertRaises(ValueError):
            self.remove(include_generator=True, dry_run=False)
        self.assertEqual(files(self.root), before)

    def test_missing_manifest_never_authorizes_router_deletion(self):
        self.generate()
        (self.root / ".harness/manifest.json").unlink()
        before = files(self.root)
        with self.assertRaises(ValueError):
            self.remove(dry_run=False)
        self.assertEqual(files(self.root), before)

    def test_application_transaction_and_orphaned_backups_block_removal(self):
        self.generate()
        journal = self.root / lifecycle.JOURNAL
        journal.write_text('{"schemaVersion":2,"state":"preparing"}', encoding="utf-8")
        before = files(self.root)
        with self.assertRaises(ValueError):
            self.remove(dry_run=False)
        with self.assertRaises(ValueError):
            self.recover(dry_run=False)
        self.assertEqual(files(self.root), before)
        journal.unlink()
        (self.root / lifecycle.WORKSPACES).mkdir()
        with self.assertRaises(ValueError):
            self.remove(dry_run=False)
        with self.assertRaises(ValueError):
            self.recover(dry_run=False)

    def test_generated_hash_is_rechecked_after_manifest_validation(self):
        self.generate()
        actual = harness_apply.existing_manifest_state
        managed = self.root / ".agents/skills/project-harness/SKILL.md"

        def validated_then_changed(root):
            result = actual(root)
            managed.write_bytes(b"concurrent user edit")
            return result

        with mock.patch.object(harness_apply, "existing_manifest_state", side_effect=validated_then_changed):
            with self.assertRaisesRegex(ValueError, "changed during preparation"):
                self.remove(dry_run=False)
        self.assertEqual(managed.read_bytes(), b"concurrent user edit")
        self.assertTrue((self.root / ".harness/manifest.json").is_file())
        self.assertFalse((self.root / lifecycle.JOURNAL).exists())

    def test_move_failure_rolls_back_original_bytes_modes_and_mtimes(self):
        self.generate()
        before = files(self.root)
        self.interrupt(rollback_fails=False)
        self.assertEqual(files(self.root), before)
        self.assertFalse((self.root / lifecycle.WORKSPACES).exists())

    def test_generator_failure_rolls_back_generator_and_project_together(self):
        self.install()
        self.generate()
        before = files(self.root)
        replace = os.replace
        failed = False

        def fail(source, destination):
            nonlocal failed
            if Path(destination).name == "backup-000003" and not failed:
                failed = True
                raise OSError("generator move failed")
            return replace(source, destination)

        with mock.patch.object(lifecycle.os, "replace", side_effect=fail):
            with self.assertRaises(lifecycle.LifecycleError):
                self.remove(include_generator=True, dry_run=False)
        self.assertEqual(files(self.root), before)

    def test_interrupted_removal_has_separate_journal_and_recovers_exactly(self):
        self.generate()
        before = files(self.root)
        self.interrupt()
        journal_path = self.root / lifecycle.JOURNAL
        journal = json.loads(journal_path.read_bytes())
        self.assertEqual(journal["removalSchemaVersion"], 1)
        self.assertNotIn("schemaVersion", journal)
        self.assertEqual(journal["state"], "remove-recovery-required")
        pending = files(self.root)
        self.assertTrue(lifecycle.removal_status(self.root, source_root=REPO)["recoverable"])
        self.assertEqual(self.recover()["state"], "rollback-preview")
        self.assertEqual(files(self.root), pending)
        with self.assertRaises(ValueError):
            harness_transaction.recover_transaction(self.root)
        self.assertEqual(files(self.root), pending)
        with self.assertRaises(ValueError):
            harness_transaction.ensure_no_pending_transaction(self.root)
        validator = validate_harness.Validator(self.root)
        report = validator.run()
        self.assertFalse(report["valid"])
        self.assertEqual(self.recover(dry_run=False)["state"], "rolled-back")
        self.assertEqual(files(self.root), before)

    def test_recovery_preserves_conflicting_new_user_file_before_any_restore(self):
        self.generate()
        self.interrupt()
        path = self.root / ".agents/skills/project-harness/SKILL.md"
        path.write_bytes(b"new user work after interruption")
        before = files(self.root)
        with self.assertRaises(ValueError):
            self.recover(dry_run=False)
        self.assertEqual(files(self.root), before)

    def test_interruption_after_pointer_change_restores_user_instruction_bytes(self):
        self.generate()
        pointer = self.root / "AGENTS.md"
        pointer.write_bytes(b"# User prefix\r\n" + pointer.read_bytes() + b"User suffix\r\n")
        before = files(self.root)
        self.interrupt(destination_index=2)
        self.assertEqual(pointer.read_bytes(), b"# User prefix\r\n\nUser suffix\r\n")
        self.assertEqual(self.recover(dry_run=False)["state"], "rolled-back")
        self.assertEqual(files(self.root), before)

    def test_recovery_rejects_backup_tampering_without_partial_restore(self):
        self.generate()
        self.interrupt()
        backup = next((self.root / lifecycle.WORKSPACES).glob("*/backup-*"))
        backup.write_bytes(b"modified backup")
        before = files(self.root)
        with self.assertRaises(ValueError):
            self.recover(dry_run=False)
        self.assertEqual(files(self.root), before)

    def test_recovery_rejects_bad_seal_and_path_injection(self):
        self.generate()
        self.interrupt()
        journal_path = self.root / lifecycle.JOURNAL
        valid = json.loads(journal_path.read_bytes())
        for reseal in (False, True):
            changed = json.loads(json.dumps(valid))
            changed["operations"][0]["path"] = ".git/config"
            if reseal:
                changed = lifecycle._seal(changed)
            journal_path.write_text(json.dumps(changed), encoding="utf-8")
            before = files(self.root)
            with self.assertRaises(ValueError):
                self.recover(dry_run=False)
            self.assertEqual(files(self.root), before)

    def test_nontext_journal_state_is_rejected_without_unhandled_type_error(self):
        self.generate()
        self.interrupt()
        journal_path = self.root / lifecycle.JOURNAL
        journal = json.loads(journal_path.read_bytes())
        journal["state"] = ["remove-applying"]
        journal_path.write_text(json.dumps(lifecycle._seal(journal)), encoding="utf-8")
        before = files(self.root)
        with self.assertRaises(ValueError):
            self.recover(dry_run=False)
        self.assertEqual(files(self.root), before)

    def test_committed_cleanup_failure_recovers_by_cleanup_without_restore(self):
        self.generate()
        with mock.patch.object(lifecycle, "_cleanup", side_effect=OSError("cleanup unavailable")):
            result = self.remove(dry_run=False)
        self.assertEqual(result["state"], "removed-cleanup-required")
        self.assertFalse((self.root / ".harness/manifest.json").exists())
        self.assertEqual(self.recover()["state"], "cleanup-preview")
        self.assertEqual(self.recover(dry_run=False)["state"], "cleaned")
        self.assertFalse((self.root / lifecycle.JOURNAL).exists())
        self.assertFalse((self.root / ".agents/skills/project-harness/SKILL.md").exists())

    def test_committed_cleanup_does_not_delete_backup_when_new_file_appears(self):
        self.generate()
        with mock.patch.object(lifecycle, "_cleanup", side_effect=OSError("cleanup unavailable")):
            self.remove(dry_run=False)
        (self.root / ".agents/skills/project-harness/SKILL.md").write_bytes(b"new work")
        before = files(self.root)
        with self.assertRaises(ValueError):
            self.recover(dry_run=False)
        self.assertEqual(files(self.root), before)

    def test_cleanup_retry_accepts_already_removed_backup_directories_on_posix(self):
        self.generate()
        unlink = Path.unlink
        journal = self.root / lifecycle.JOURNAL

        def fail_final_unlink(path, *args, **kwargs):
            if path == journal:
                raise OSError("journal unlink temporarily unavailable")
            return unlink(path, *args, **kwargs)

        def require_existing_directory(path):
            if not path.is_dir():
                raise FileNotFoundError(str(path))
            return True

        with mock.patch.object(Path, "unlink", autospec=True, side_effect=fail_final_unlink):
            result = self.remove(dry_run=False)
        self.assertEqual(result["state"], "removed-cleanup-required")
        self.assertTrue(journal.is_file())
        self.assertFalse((self.root / lifecycle.WORKSPACES).exists())
        with mock.patch.object(harness_state, "sync_directory", side_effect=require_existing_directory):
            self.assertEqual(self.recover(dry_run=False)["state"], "cleaned")
        self.assertFalse(journal.exists())

    def test_symlink_owned_file_is_rejected_before_mutation(self):
        self.generate()
        managed = self.root / ".agents/skills/project-harness/SKILL.md"
        outside = self.root.parent / "outside.txt"
        outside.write_bytes(managed.read_bytes())
        managed.unlink()
        try:
            managed.symlink_to(outside)
        except OSError:
            self.skipTest("Creating symlinks requires a platform privilege")
        before = outside.read_bytes()
        with self.assertRaises(ValueError):
            self.remove(dry_run=False)
        self.assertEqual(outside.read_bytes(), before)
        self.assertTrue(managed.is_symlink())
        self.assertFalse((self.root / lifecycle.JOURNAL).exists())

    def test_fresh_generation_after_removal_is_valid(self):
        self.generate()
        self.remove(dry_run=False)
        self.generate()
        validator = validate_harness.Validator(self.root)
        self.assertTrue(validator.run()["valid"])


if __name__ == "__main__":
    unittest.main()
