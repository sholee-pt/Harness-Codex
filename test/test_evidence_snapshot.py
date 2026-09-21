"""Share source work without weakening apply/recovery or legacy validity gates."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_harness_tools import harness_apply, harness_state, minimal_plan, validate_harness


class EvidenceSnapshotTests(unittest.TestCase):
    def test_plan_shares_hash_and_reads_across_project_and_topology(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            plan['project']['evidence'] *= 20
            source = root / 'pyproject.toml'
            content = source.read_bytes()
            original_read = Path.read_bytes
            reads, digests = [], []
            original_digest = harness_state.digest_bytes
            def read(path):
                if path == source:
                    reads.append(path)
                return original_read(path)
            def digest(data):
                if data == content:
                    digests.append(data)
                return original_digest(data)
            with mock.patch.object(Path, 'read_bytes', read), mock.patch.object(harness_state, 'digest_bytes', digest):
                application = harness_apply.build_application(root, plan)
            self.assertEqual(len(digests), 1)
            self.assertEqual(len(reads), 2)  # Snapshot plus unconditional final byte check.
            self.assertTrue(harness_apply.application_actions(application))

    def test_same_size_timestamp_restoration_cannot_hide_changed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.py'
            path.write_bytes(b'original')
            snapshot = harness_state.EvidenceSnapshot()
            signature = snapshot.signature(path)
            with mock.patch.object(snapshot, 'signature', return_value=signature):
                snapshot.read(path)
                path.write_bytes(b'modified')
                os.utime(path, ns=(signature[-2], signature[-2]))
                snapshot.read(path)
                with self.assertRaisesRegex(OSError, 'changed during validation'):
                    snapshot.verify()

    def test_cache_budget_and_line_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.txt'
            path.write_bytes('a\r\nb\rc\u2028d\n'.encode())
            snapshot = harness_state.EvidenceSnapshot(limit=1)
            self.assertEqual(snapshot.line_count(path), 4)
            self.assertEqual(snapshot.files, {})
            self.assertEqual(snapshot.line_counts, {})
            path.write_bytes(b'\xff')
            with self.assertRaises(UnicodeError):
                snapshot.line_count(path)

    def test_drift_diagnostics_preserve_strict_validity_and_contract_independence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))
            (root / 'pyproject.toml').write_text('# source changed\n', encoding='utf-8')
            report = validate_harness.Validator(root).run()
            self.assertFalse(report['valid'])
            self.assertFalse(report['integrityValid'])  # Backward-compatible aggregate.
            self.assertTrue(report['managedIntegrityValid'])
            self.assertEqual(report['validationLayers']['artifactCompatibility']['status'], 'passed')
            self.assertEqual(report['validationLayers']['evidenceFreshness']['status'], 'failed')
            (root / '.agents/skills/project-harness/SKILL.md').write_text('user edit', encoding='utf-8')
            self.assertFalse(validate_harness.Validator(root).run()['managedIntegrityValid'])
