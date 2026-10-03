"""Preserve source bytes and ownership across reviewed project generation."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from test_harness_tools import (
    harness_apply, harness_state, harness_transaction, inventory, minimal_plan,
    validate_harness,
)
import harness_instruction_audit

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harness_cli import lifecycle


class GenerationReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def apply(self, plan):
        return harness_apply.apply_application(harness_apply.build_application(self.root, plan))

    def legacy(self, plan):
        self.apply(plan)
        path = self.root / '.harness/manifest.json'
        manifest = json.loads(path.read_bytes())
        manifest['schemaVersion'] = 4
        manifest['generator']['version'] = '4.0'
        manifest.pop('artifactContractVersion')
        path.write_text(json.dumps(manifest), encoding='utf-8')
        return path, manifest

    def test_crlf_artifacts_and_pointer_validate_repeat_and_remove_without_user_changes(self):
        user = b'# User instructions\r\nKeep the original line endings.'
        path = self.root / 'AGENTS.md'
        path.write_bytes(user)
        plan = minimal_plan(self.root)
        plan['artifacts'][0]['content'] = plan['artifacts'][0]['content'].replace('\n', '\r\n')
        plan['instruction']['managedBlock'] = plan['instruction']['managedBlock'].replace('\n', '\r\n')
        self.apply(plan)
        report = validate_harness.Validator(self.root).run()
        self.assertTrue(report['valid'], report['errors'])
        self.assertEqual(harness_state.instruction_user_content(path.read_bytes()), user)
        self.assertEqual((self.root / plan['artifacts'][0]['path']).read_bytes(), plan['artifacts'][0]['content'].encode())
        before = {item: (item.read_bytes(), item.stat().st_mtime_ns) for item in self.root.rglob('*') if item.is_file()}
        self.assertEqual(self.apply(plan)['writes'], 0)
        self.assertEqual(before, {item: (item.read_bytes(), item.stat().st_mtime_ns) for item in self.root.rglob('*') if item.is_file()})
        manifest = json.loads((self.root / '.harness/manifest.json').read_bytes())
        pointer = next(item for item in manifest['managedFiles'] if item['path'] == 'AGENTS.md')
        self.assertEqual(pointer['sha256'], harness_state.digest_bytes(harness_state.content_for_entry(path, 'managed-block')))
        self.assertEqual(lifecycle.remove_project(self.root, source_root=REPO, dry_run=False)['state'], 'removed')
        self.assertEqual(path.read_bytes(), user)

    def test_legacy_normalized_pointer_hash_remains_readable_and_removable(self):
        user = b'# User\r\nPreserve these bytes.\r\n'
        path = self.root / 'AGENTS.md'
        path.write_bytes(user)
        plan = minimal_plan(self.root)
        plan['instruction']['managedBlock'] = plan['instruction']['managedBlock'].replace('\n', '\r\n')
        self.apply(plan)
        manifest_path = self.root / '.harness/manifest.json'
        manifest = json.loads(manifest_path.read_bytes())
        pointer = next(item for item in manifest['managedFiles'] if item['path'] == 'AGENTS.md')
        block = harness_state.content_for_entry(path, 'managed-block')
        pointer['sha256'] = harness_state.digest_bytes(block.replace(b'\r\n', b'\n').replace(b'\r', b'\n'))
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        self.assertEqual(harness_state.entry_status(self.root, pointer)['state'], 'unchanged')
        self.assertTrue(validate_harness.Validator(self.root).run()['valid'])
        original = path.read_bytes()
        path.write_bytes(original.replace(b'## Project Harness', b'## User changed pointer'))
        self.assertEqual(harness_state.entry_status(self.root, pointer)['state'], 'modified')
        with self.assertRaisesRegex(ValueError, 'modified'):
            lifecycle.remove_project(self.root, source_root=REPO, dry_run=False)
        path.write_bytes(original)
        lifecycle.remove_project(self.root, source_root=REPO, dry_run=False)
        self.assertEqual(path.read_bytes(), user)

    def test_crlf_pointer_interruption_rolls_back_exact_user_bytes(self):
        path = self.root / 'AGENTS.md'
        user = b'# User policy\r\nKeep the bytes.\r\n'
        path.write_bytes(user)
        plan = minimal_plan(self.root)
        plan['instruction']['managedBlock'] = plan['instruction']['managedBlock'].replace('\n', '\r\n')
        application = harness_apply.build_application(self.root, plan)
        write = harness_state.atomic_write_bytes
        def interrupt(target, content, **kwargs):
            if target == self.root / '.harness/manifest.json':
                raise OSError('injected manifest interruption')
            return write(target, content, **kwargs)
        with mock.patch.object(harness_state, 'atomic_write_bytes', side_effect=interrupt):
            with self.assertRaisesRegex(harness_transaction.TransactionError, 'rolled back'):
                harness_apply.apply_application(application)
        self.assertEqual(path.read_bytes(), user)
        self.assertIsNone(harness_state.transaction_status(self.root))

    def test_schema4_reanalysis_accepts_replaced_source_without_resealing_old_evidence(self):
        plan = minimal_plan(self.root)
        self.legacy(plan)
        (self.root / 'pyproject.toml').unlink()
        current = self.root / 'CURRENT.toml'
        current.write_text('[project]\nname = "current-project"\n', encoding='utf-8')
        revised = copy.deepcopy(plan)
        revised['project']['evidence'][0].update(path=current.name, sha256=harness_state.digest_bytes(current.read_bytes()))
        revised['topology']['boundaries'][0]['readScopes'] = [current.name]
        self.assertGreater(self.apply(revised)['writes'], 0)
        self.assertTrue(validate_harness.Validator(self.root).run()['valid'])
        self.assertEqual(self.apply(revised)['writes'], 0)

    def test_schema4_reanalysis_keeps_current_evidence_and_old_ownership_checks(self):
        plan = minimal_plan(self.root)
        self.legacy(plan)
        (self.root / 'pyproject.toml').write_text('[project]\nname = "updated"\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed after analysis'):
            self.apply(plan)
        current = minimal_plan(self.root)
        target = self.root / current['artifacts'][0]['path']
        target.write_bytes(target.read_bytes() + b'\nUser edit\n')
        before = target.read_bytes()
        with self.assertRaisesRegex(ValueError, 'modified'):
            self.apply(current)
        self.assertEqual(target.read_bytes(), before)
        self.assertIsNone(harness_state.transaction_status(self.root))

    def test_schema4_old_evidence_shape_and_reserved_paths_are_still_validated(self):
        plan = minimal_plan(self.root)
        path, original = self.legacy(plan)
        for changes, message in (({'sha256': 'bad'}, 'SHA-256'),
                                 ({'lines': {'start': 2, 'end': 1}}, '1 <= start <= end'),
                                 ({'path': '.git/config'}, 'reserved control namespace')):
            with self.subTest(changes=changes):
                manifest = copy.deepcopy(original)
                manifest['project']['evidence'][0].update(changes)
                path.write_text(json.dumps(manifest), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, message):
                    self.apply(plan)
                self.assertIsNone(harness_state.transaction_status(self.root))

    def fallback(self, name='PROJECT.md'):
        (self.root / '.codex').mkdir()
        (self.root / '.codex/config.toml').write_text('project_doc_fallback_filenames = ' + json.dumps([name]) + '\n', encoding='utf-8')
        path = self.root / name
        path.write_bytes(b'# Configured project instructions\r\nUse this project policy.\r\n')
        return path

    def test_inventory_fallback_is_selected_even_after_the_file_budget_stops(self):
        path = self.fallback()
        (self.root / 'AAA.txt').write_text('First inventory file.', encoding='utf-8')
        report = inventory.build_inventory(self.root, max_files=1)
        self.assertTrue(report['truncated'])
        self.assertEqual(report['existingActiveRootInstruction'], path.name)
        self.assertEqual(report['plannedRootInstruction'], harness_state.active_instruction_relative(self.root))
        self.assertIn(path.name, report['instructions'])
        self.assertEqual(report['instructionSelectionErrors'], [])

    def test_inventory_empty_override_and_empty_base_use_actual_selector(self):
        path = self.fallback()
        (self.root / 'AGENTS.override.md').write_text(' \n', encoding='utf-8')
        (self.root / 'AGENTS.md').write_text('# Base instructions\n', encoding='utf-8')
        self.assertEqual(inventory.build_inventory(self.root, 20)['existingActiveRootInstruction'], 'AGENTS.md')
        (self.root / 'AGENTS.md').write_text('', encoding='utf-8')
        self.assertEqual(inventory.build_inventory(self.root, 20)['existingActiveRootInstruction'], path.name)

    def test_inventory_invalid_instruction_config_does_not_claim_a_selected_file(self):
        self.fallback()
        (self.root / '.codex/config.toml').write_text('project_doc_fallback_filenames = [', encoding='utf-8')
        report = inventory.build_inventory(self.root, 20)
        self.assertIsNone(report['existingActiveRootInstruction'])
        self.assertIsNone(report['plannedRootInstruction'])
        self.assertTrue(report['instructionSelectionErrors'])

    def test_inventory_instruction_selection_is_bounded_without_guessing_a_fallback(self):
        self.fallback()
        (self.root / 'AGENTS.override.md').write_bytes(b' ' * (inventory.INSTRUCTION_SELECTION_MAX_BYTES + 1))
        report = inventory.build_inventory(self.root, 20)
        self.assertIsNone(report['existingActiveRootInstruction'])
        self.assertIsNone(report['plannedRootInstruction'])
        self.assertIn('inventory byte budget', report['instructionSelectionErrors'][0])

    def test_audit_includes_configured_manifest_instruction_with_its_loading_surface(self):
        path = self.fallback('PROJECT.toml')
        report = harness_instruction_audit.inspect(self.root, {'instructionFile': path.name, 'managedFiles': []})
        surface = next(item for item in report['surfaces'] if item['path'] == path.name)
        self.assertEqual(surface['kind'], 'root-instructions')
        self.assertEqual(surface['bytes'], len(path.read_bytes()))
        report = harness_instruction_audit.inspect(self.root, {'instructionFile': 'private.txt', 'managedFiles': []})
        self.assertEqual(report['files'], 0)
        self.assertIn('not a configured root instruction', report['skipped'][0]['reason'])

    def test_audit_fallback_respects_existing_byte_budget(self):
        path = self.fallback()
        path.write_bytes(b'x' * (harness_instruction_audit.MAX_FILE_BYTES + 1))
        report = harness_instruction_audit.inspect(self.root, {'instructionFile': path.name})
        self.assertEqual(report['files'], 0)
        self.assertEqual(report['skipped'][0]['path'], path.name)
        self.assertIn('byte budget', report['skipped'][0]['reason'])

    def test_validator_reuses_one_root_scan_per_run_without_cross_run_cache(self):
        self.apply(minimal_plan(self.root))
        validator = validate_harness.Validator(self.root)
        with mock.patch.object(inventory, 'inspect_root_context', wraps=inventory.inspect_root_context) as scan:
            self.assertTrue(validator.run()['valid'])
            self.assertEqual(scan.call_count, 1)
            self.assertTrue(validator.run()['valid'])
            self.assertEqual(scan.call_count, 2)


if __name__ == '__main__':
    unittest.main()
