"""Test fixture versions must never leak into a published native executable."""
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from build.native_ui.run_tests import run_tests


class NativeTestSourceTests(unittest.TestCase):
    def test_ci_profile_keeps_all_assertions_and_restores_release_bytes_after_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cargo = root / 'codex-rs'
            (cargo / 'tui').mkdir(parents=True)
            manifest, lock = cargo / 'Cargo.toml', cargo / 'Cargo.lock'
            manifest.write_bytes(b'[workspace]\r\nmembers = ["tui"]\r\n[workspace.package]\r\nversion = "0.154.0"\r\n')
            (cargo / 'tui/Cargo.toml').write_text('[package]\nname = "codex-tui"\nversion.workspace = true\n')
            lock.write_text('[[package]]\nname = "codex-tui"\nversion = "0.154.0"\n'
                            '[[package]]\nname = "external"\nversion = "0.154.0"\nsource = "registry+fixture"\nchecksum = "abc"\n')
            before = {path: path.read_bytes() for path in (manifest, lock)}

            def invoke(command, **kwargs):
                self.assertEqual(tomllib.loads(manifest.read_text())['workspace']['package']['version'], '0.0.0')
                packages = tomllib.loads(lock.read_text())['package']
                self.assertEqual(packages[0]['version'], '0.0.0')
                self.assertEqual(packages[1], {'name': 'external', 'version': '0.154.0',
                                             'source': 'registry+fixture', 'checksum': 'abc'})
                self.assertIn('--locked', command)
                self.assertIn('--no-fail-fast', command)
                self.assertEqual(command[command.index('--cargo-profile') + 1], 'ci-test')
                self.assertEqual(kwargs['env']['INSTA_UPDATE'], 'no')
                return subprocess.CompletedProcess(command, 7)

            with patch('build.native_ui.run_tests.subprocess.run', side_effect=invoke):
                self.assertEqual(run_tests(root, 'x86_64-unknown-linux-musl'), 7)
            self.assertEqual({path: path.read_bytes() for path in before}, before)
            with patch('build.native_ui.run_tests.subprocess.run', side_effect=OSError('cannot execute')):
                with self.assertRaises(OSError):
                    run_tests(root, 'x86_64-unknown-linux-musl')
            self.assertEqual({path: path.read_bytes() for path in before}, before)
