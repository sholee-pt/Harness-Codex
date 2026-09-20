"""Test graph reconciliation must preserve dependencies and release bytes."""
import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from build.native_ui.run_tests import run_tests


class NativeTestSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        cargo = self.root / 'codex-rs'
        (cargo / 'tui/tests/common').mkdir(parents=True)
        self.manifest, self.lock = cargo / 'Cargo.toml', cargo / 'Cargo.lock'
        self.manifest.write_bytes(b'[workspace]\r\nmembers = ["tui"]\r\n[workspace.package]\r\nversion = "0.154.0"\r\n')
        (cargo / 'tui/Cargo.toml').write_text('[package]\nname = "codex-tui"\nversion.workspace = true\n'
                                            '[dev-dependencies]\ncore_test_support = { path = "tests/common" }\n')
        (cargo / 'tui/tests/common/Cargo.toml').write_text('[package]\nname = "core_test_support"\nversion.workspace = true\n')
        self.lock.write_text('[[package]]\nname = "codex-tui"\nversion = "0.154.0"\n'
                             '[[package]]\nname = "core_test_support"\nversion = "0.154.0"\n'
                             '[[package]]\nname = "external"\nversion = "0.154.0"\nsource = "registry+fixture"\nchecksum = "abc"\n')
        self.before = {path: path.read_bytes() for path in (self.manifest, self.lock)}
        self.target = 'x86_64-unknown-linux-musl'

    def assert_restored(self):
        self.assertEqual({path: path.read_bytes() for path in self.before}, self.before)

    def cargo_reconcile(self, command, **kwargs):
        self.assertEqual(command[:2], ['cargo', 'metadata'])
        self.assertIn('--all-features', command)
        self.assertIn('--offline', command)
        self.assertNotIn('--locked', command)
        self.assertEqual(command[command.index('--filter-platform') + 1], self.target)
        self.assertEqual(tomllib.loads(self.manifest.read_text())['workspace']['package']['version'], '0.0.0')
        # Simulate Cargo handling both explicit and implicit path members.
        content = self.lock.read_text().split('[[package]]')
        self.lock.write_text('[[package]]'.join(
            block.replace('version = "0.154.0"', 'version = "0.0.0"') if 'source =' not in block else block
            for block in content))
        return subprocess.CompletedProcess(command, 0)

    def test_implicit_members_are_reconciled_before_locked_tests_and_restored_after_failure(self):
        def invoke(command, **kwargs):
            if command[1] == 'metadata':
                return self.cargo_reconcile(command, **kwargs)
            packages = tomllib.loads(self.lock.read_text())['package']
            self.assertEqual([p['version'] for p in packages], ['0.0.0', '0.0.0', '0.154.0'])
            self.assertIn('--locked', command)
            self.assertIn('--no-fail-fast', command)
            self.assertEqual(command[command.index('--cargo-profile') + 1], 'ci-test')
            self.assertEqual(kwargs['env']['INSTA_UPDATE'], 'no')
            return subprocess.CompletedProcess(command, 7)

        with patch('build.native_ui.run_tests.subprocess.run', side_effect=invoke) as calls, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_tests(self.root, self.target), 7)
        self.assertEqual(calls.call_count, 2)
        self.assert_restored()

    def test_external_version_source_checksum_addition_and_removal_block_tests(self):
        for drift in ('version', 'source', 'checksum', 'added', 'removed'):
            with self.subTest(drift=drift):
                def invoke(command, **kwargs):
                    self.cargo_reconcile(command, **kwargs)
                    blocks = self.lock.read_text().split('[[package]]')
                    if drift == 'added':
                        blocks.append('\nname = "new-external"\nversion = "1.0.0"\nsource = "registry+fixture"\nchecksum = "xyz"\n')
                    elif drift == 'removed':
                        blocks.pop()
                    else:
                        old, new = {'version': ('"0.154.0"', '"0.154.1"'),
                                    'source': ('"registry+fixture"', '"registry+other"'),
                                    'checksum': ('"abc"', '"def"')}[drift]
                        blocks[-1] = blocks[-1].replace(old, new)
                    self.lock.write_text('[[package]]'.join(blocks))
                    return subprocess.CompletedProcess(command, 0)
                with patch('build.native_ui.run_tests.subprocess.run', side_effect=invoke) as calls, contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(ValueError, 'external dependency change'):
                        run_tests(self.root, self.target)
                self.assertEqual(calls.call_count, 1)
                self.assert_restored()

    def test_metadata_preflight_requires_locked_graph_without_starting_tests(self):
        for result in (0, 102):
            with self.subTest(result=result):
                def invoke(command, **kwargs):
                    self.assertEqual(command[:2], ['cargo', 'metadata'])
                    if '--locked' not in command:
                        return self.cargo_reconcile(command, **kwargs)
                    self.assertIn('--offline', command)
                    self.assertIn('--all-features', command)
                    self.assertEqual(command[command.index('--filter-platform') + 1], self.target)
                    return subprocess.CompletedProcess(command, result)
                with patch('build.native_ui.run_tests.subprocess.run', side_effect=invoke) as calls, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(run_tests(self.root, self.target, metadata_only=True), result)
                self.assertEqual(calls.call_count, 2)
                self.assert_restored()

    def test_metadata_launch_failure_restores_release_bytes(self):
        with patch('build.native_ui.run_tests.subprocess.run', side_effect=OSError('cannot execute')):
            with self.assertRaises(OSError):
                run_tests(self.root, self.target)
        self.assert_restored()

    def test_reviewed_version_comes_from_metadata_and_mismatch_preserves_files(self):
        self.manifest.write_bytes(self.before[self.manifest].replace(b'0.154.0', b'99.42.7'))
        self.before[self.manifest] = self.manifest.read_bytes()
        with self.assertRaisesRegex(ValueError, 'upstream.json'):
            run_tests(self.root, self.target, metadata_only=True)
        self.assert_restored()
        def invoke(command, **kwargs):
            self.assertEqual(tomllib.loads(self.manifest.read_text())['workspace']['package']['version'], '0.0.0')
            self.assertIn('--locked', command)
            return subprocess.CompletedProcess(command, 0)
        with patch('build.native_ui.run_tests.json.loads', return_value={'version': '99.42.7'}), \
                patch('build.native_ui.run_tests.reconcile'), \
                patch('build.native_ui.run_tests.subprocess.run', side_effect=invoke), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_tests(self.root, self.target, metadata_only=True), 0)
        self.assert_restored()

    def test_helper_download_uses_reviewed_tag_metadata(self):
        from build.native_ui.package import prepare
        with patch('build.native_ui.package.json.loads', return_value={'tag': 'rust-v99.42.7'}), \
                patch('build.native_ui.package.download', side_effect=OSError('offline fixture')) as download:
            with self.assertRaises(OSError):
                prepare(self.root / 'package', 'linux-x86_64')
        self.assertIn('/rust-v99.42.7/codex-package-x86_64-unknown-linux-musl.tar.gz', download.call_args.args[0])
