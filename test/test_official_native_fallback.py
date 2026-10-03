"""Verified packages can be selected for native use without weakening Auto checks."""
import hashlib
import io
import os
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from harness_cli import auto_relay, codex_entry, codex_integration, main, official_codex, release_updates


class NativeFallbackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        executable = self.root / 'codex'
        executable.write_bytes(b'unchanged official fixture\n')
        executable.chmod(0o755)
        self.archive = self.root / 'package.tar.gz'
        with tarfile.open(self.archive, 'w:gz') as bundle:
            bundle.add(executable, arcname='bin/codex')
        self.asset = {'name': 'codex-package-x86_64-unknown-linux-musl.tar.gz',
            'url': 'https://api.github.com/repos/openai/codex/releases/assets/1',
            'digest': 'sha256:' + hashlib.sha256(self.archive.read_bytes()).hexdigest(), 'size': self.archive.stat().st_size}

    def install(self, version='0.158.0', *, error=None, fallback=None, corrupt=False, prefer_auto=False):
        selected = {'updateAvailable': True, 'release': {'tag_name': 'rust-v' + version, 'assets': [self.asset]}}
        with mock.patch.object(official_codex, 'target', return_value='x86_64-unknown-linux-musl'), \
             mock.patch.object(release_updates, 'request', side_effect=lambda *args, **kwargs: io.BytesIO(b'corrupt' if corrupt else self.archive.read_bytes())), \
             mock.patch.object(official_codex.subprocess, 'run', return_value=SimpleNamespace(stdout='codex-cli ' + version + '\n')), \
             mock.patch.object(codex_entry, 'compatible', side_effect=error):
            return official_codex.install(self.data, selected=selected, native_fallback=fallback, prefer_auto=prefer_auto)

    def test_unsupported_update_preserves_old_auto_until_native_is_selected(self):
        previous = self.install()
        pointer = self.data / official_codex.POINTER
        before = pointer.read_bytes()
        error = ValueError('unsupported Auto protocol')
        for fallback in (None, mock.Mock(return_value=False)):
            with self.subTest(fallback=fallback), self.assertRaisesRegex(ValueError, 'unsupported Auto'):
                self.install('0.159.0', error=error, fallback=fallback)
            self.assertEqual(pointer.read_bytes(), before)
            self.assertFalse((self.data / 'official-codex/0.159.0').exists())
        fallback = mock.Mock(return_value=True)
        current = self.install('0.159.0', error=error, fallback=fallback)
        fallback.assert_called_once_with('0.159.0', error)
        self.assertEqual(official_codex.read(self.data)['mode'], 'native')
        self.assertEqual(previous.read_bytes(), current.read_bytes())
        self.assertEqual(official_codex.binary(self.data), current)
        self.assertFalse(list((self.data / 'official-codex').rglob('.pending-*')))

    def test_initial_native_selection_and_integrity_failure_are_separate(self):
        fallback = mock.Mock(return_value=True)
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            self.install(error=ValueError('unsupported'), fallback=fallback, corrupt=True)
        fallback.assert_not_called()
        self.assertIsNone(official_codex.read(self.data))
        current = self.install(error=ValueError('unsupported'), fallback=fallback)
        self.assertEqual(official_codex.read(self.data), {'schema': 2, 'version': '0.158.0',
            'target': 'x86_64-unknown-linux-musl', 'mode': 'native'})
        self.assertTrue(current.is_file())

    def test_native_choice_is_retained_until_explicit_successful_auto_check(self):
        self.install(error=ValueError('unsupported'), fallback=lambda *args: True)
        self.install('0.159.0')
        self.assertEqual(official_codex.read(self.data)['mode'], 'native')
        selected = {'updateAvailable': False}
        with mock.patch.object(codex_entry, 'compatible') as compatible:
            official_codex.install(self.data, selected=selected)
            compatible.assert_not_called()
        before = (self.data / official_codex.POINTER).read_bytes()
        with mock.patch.object(codex_entry, 'compatible', side_effect=ValueError('still unsupported')):
            with self.assertRaisesRegex(ValueError, 'still unsupported'):
                official_codex.install(self.data, selected=selected, prefer_auto=True)
        self.assertEqual((self.data / official_codex.POINTER).read_bytes(), before)
        with mock.patch.object(codex_entry, 'compatible') as compatible:
            official_codex.install(self.data, selected=selected, prefer_auto=True)
            compatible.assert_called_once()
        self.assertEqual(official_codex.read(self.data)['schema'], 1)
        self.assertNotIn('mode', official_codex.read(self.data))

    def test_native_update_does_not_require_adapter_or_repeat_choice(self):
        previous = self.install(error=ValueError('unsupported'), fallback=lambda *args: True)
        fallback = mock.Mock(return_value=False)
        current = self.install('0.159.0', error=ValueError('still unsupported'), fallback=fallback)
        fallback.assert_not_called()
        self.assertEqual(official_codex.read(self.data), {'schema': 2, 'version': '0.159.0',
            'target': 'x86_64-unknown-linux-musl', 'mode': 'native'})
        self.assertEqual(official_codex.binary(self.data), current)
        self.assertTrue(previous.is_file())
        before = (self.data / official_codex.POINTER).read_bytes()
        with self.assertRaisesRegex(ValueError, 'still unsupported'):
            self.install('0.160.0', error=ValueError('still unsupported'), fallback=fallback, prefer_auto=True)
        self.assertEqual((self.data / official_codex.POINTER).read_bytes(), before)
        self.assertFalse((self.data / 'official-codex/0.160.0').exists())

    def test_selected_native_launch_does_not_probe_or_change_conversation_arguments(self):
        binary = self.install(error=ValueError('unsupported'), fallback=lambda *args: True)
        args = ['resume', 'thread-id', '--sandbox', 'read-only']
        with mock.patch.object(main, 'default_data_root', return_value=self.data), \
             mock.patch.object(codex_integration, 'read', return_value={'schema': 2}), \
             mock.patch.object(codex_entry, 'interactive', return_value=True), \
             mock.patch.object(codex_entry, 'update_choices', return_value=False), \
             mock.patch.object(codex_entry, 'compatible') as compatible, \
             mock.patch.object(auto_relay, 'run') as run, \
             mock.patch.object(codex_entry.os, 'execve', side_effect=RuntimeError('native executed')) as execute, \
             mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'native executed'):
                codex_entry.main(args)
        self.assertEqual(execute.call_args.args[0:2], (str(binary), [str(binary), *args]))
        compatible.assert_not_called()
        run.assert_not_called()

    def test_redirected_input_never_selects_native_installation(self):
        with mock.patch.object(sys.stdin, 'isatty', return_value=False), mock.patch.object(codex_entry, 'choose') as choose:
            self.assertFalse(codex_entry.choose_native_install('0.159.0', ValueError('unsupported')))
        choose.assert_not_called()


if __name__ == '__main__':
    unittest.main()
