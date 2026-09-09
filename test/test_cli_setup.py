"""Reinstall choices, ownership receipts and bounded runtime cleanup."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from harness_cli import distribution as dist, footprint, main, setup, shell
from test_cli_distribution import files, source


class ReinstallTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.data, self.binary = self.base / 'tool', self.base / 'bin'
        self.source = source(self.base / 'source', '9.9')
        dist.install_tool(self.source, self.data, self.binary, python_executable=sys.executable, branch='codex/v9.9', auto_update='off')

    def test_reuse_keeps_preferences_reset_clears_only_tool_check_cache(self):
        dist.mark_check(self.data)
        common = ['install', '--data-dir', str(self.data), '--bin-dir', str(self.binary), '--no-modify-path']
        before = files(self.data)
        with mock.patch.object(main, '_environment'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main.main([*common, '--existing', 'reuse'], source_root=self.source), 0)
            self.assertEqual(files(self.data), before)
            self.assertEqual(main.main([*common, '--existing', 'reset'], source_root=self.source), 0)
        status = dist.installed_status(self.data)
        self.assertIsNone(status['branch'])
        self.assertEqual(status['auto_update'], 'compatible')
        self.assertFalse((self.data / 'last-check.json').exists())
        self.assertEqual(files(self.data / 'releases'), {name.removeprefix('releases/'): value for name, value in before.items() if name.startswith('releases/')})

    def test_interactive_choice_and_cancellation_do_not_write(self):
        before = files(self.data)
        with mock.patch.object(sys.stdin, 'isatty', return_value=True), mock.patch.object(sys.stdout, 'isatty', return_value=True):
            for answer in ('reuse', 'reset'):
                with mock.patch('builtins.input', return_value=answer):
                    self.assertEqual(setup.choose(self.data, self.binary, 'ask')[0], answer)
            with mock.patch('builtins.input', return_value=''):
                with self.assertRaisesRegex(ValueError, 'cancelled'):
                    setup.choose(self.data, self.binary, 'ask')
        self.assertEqual(files(self.data), before)

    def test_noninteractive_choice_is_explicit_and_unknown_files_are_preserved(self):
        with mock.patch.object(sys.stdin, 'isatty', return_value=False), mock.patch('builtins.open', side_effect=OSError('no terminal')):
            with self.assertRaisesRegex(ValueError, '--existing'):
                setup.choose(self.data, self.binary, 'ask')
        other = self.base / 'unowned'
        other.mkdir()
        (other / 'user.txt').write_text('keep')
        before = files(other)
        with self.assertRaises(ValueError):
            setup.choose(other, self.binary, 'reset')
        self.assertEqual(files(other), before)

    @unittest.skipUnless(os.name == 'posix', 'Bash registration')
    def test_reset_normalizes_duplicate_owned_blocks_without_touching_user_content(self):
        home = self.base / 'home'
        home.mkdir()
        profile = home / '.bashrc'
        block = shell._block(str(self.binary))
        user = b'export USER_SETTING=preserve\r\n# user code\r\n'
        profile.write_bytes(user + block + block)
        shell.reset_path(self.binary, home=home)
        self.assertEqual(profile.read_bytes(), user + block)
        before = profile.read_bytes(), profile.stat().st_mtime_ns
        shell.reset_path(self.binary, home=home)
        self.assertEqual((profile.read_bytes(), profile.stat().st_mtime_ns), before)
        profile.write_bytes(user + block.replace(b'esac', b'echo user-edit\nesac'))
        edited = profile.read_bytes()
        with self.assertRaises(ValueError):
            shell.reset_path(self.binary, home=home)
        self.assertEqual(profile.read_bytes(), edited)


class RuntimeOwnershipTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.data, self.runtime, self.home = (self.base / name for name in ('tool', 'runtime', 'home'))
        self.data.mkdir(); self.runtime.mkdir(); self.home.mkdir()
        self.prefix = self.runtime / 'envs/harness'
        self.prefix.mkdir(parents=True)
        (self.prefix / 'python.fixture').write_bytes(b'owned interpreter fixture')
        (self.runtime / footprint.MARKER).write_bytes(footprint.marker(self.data))
        self.profile = self.home / '.conda/environments.txt'
        self.profile.parent.mkdir()
        self.other = self.base / 'other'
        self.profile.write_bytes((str(self.other) + '\r\n' + str(self.prefix) + '\r\n').encode())
        with mock.patch.object(sys, 'prefix', str(self.prefix)), mock.patch.object(Path, 'home', return_value=self.home):
            self.reference = footprint.record(self.runtime, self.data)

    def plan(self):
        return footprint.inspect(self.reference, self.data)

    def test_record_is_idempotent_and_does_not_claim_later_files(self):
        before = files(self.data), (self.runtime / footprint.RECEIPT).read_bytes()
        (self.prefix / 'user.txt').write_bytes(b'preserve')
        with mock.patch.object(sys, 'prefix', str(self.prefix)):
            self.assertEqual(footprint.record(self.runtime, self.data), self.reference)
        self.assertEqual((files(self.data), (self.runtime / footprint.RECEIPT).read_bytes()), before)
        self.assertNotIn('envs/harness/user.txt', self.plan()['files'])

    def test_cleanup_removes_owned_files_and_only_its_conda_registration(self):
        self.assertEqual(footprint.cleanup(self.plan()), [])
        self.assertFalse(self.runtime.exists())
        self.assertEqual(self.profile.read_bytes(), (str(self.other) + '\r\n').encode())

    def test_changed_or_added_files_survive_runtime_cleanup(self):
        (self.prefix / 'python.fixture').write_bytes(b'user changed')
        (self.prefix / 'extra.txt').write_bytes(b'user added')
        self.assertTrue(footprint.cleanup(self.plan()))
        self.assertEqual((self.prefix / 'python.fixture').read_bytes(), b'user changed')
        self.assertEqual((self.prefix / 'extra.txt').read_bytes(), b'user added')
        self.assertIn(str(self.prefix).encode(), self.profile.read_bytes())

    def test_modified_receipt_or_marker_refuses_before_any_deletion(self):
        plan = self.plan()
        (self.runtime / footprint.MARKER).write_bytes(b'changed')
        before = files(self.runtime)
        with self.assertRaises(ValueError):
            footprint.cleanup(plan)
        self.assertEqual(files(self.runtime), before)

    @unittest.skipUnless(os.name == 'nt', 'Native Windows deferred cleanup')
    def test_windows_helper_removes_disposable_runtime_and_preserves_other_settings(self):
        plan = {**self.plan(), 'waitPid': 2147483647}
        job = self.base / 'job'
        job.mkdir()
        payload = json.dumps(plan).encode()
        (job / 'plan.json').write_bytes(payload)
        script = job / 'cleanup.ps1'
        script.write_bytes(Path(footprint.__file__).with_name('runtime_cleanup.ps1').read_bytes())
        command, environment = footprint._windows_command(script, hashlib.sha256(payload).hexdigest())
        result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr + ((job / 'error.txt').read_text(encoding='utf-8-sig') if (job / 'error.txt').exists() else ''))
        self.assertFalse(self.runtime.exists())
        self.assertFalse(job.exists())
        self.assertEqual(self.profile.read_bytes(), (str(self.other) + '\r\n').encode())


if __name__ == '__main__':
    unittest.main()
