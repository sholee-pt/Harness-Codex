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

from harness_cli import distribution as dist, footprint, main, setup, shell, paths
from test_cli_distribution import files, source


class ReinstallTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.data, self.binary = self.base / 'tool', self.base / 'bin'
        self.source = source(self.base / 'source', '9.10')
        dist.install_tool(self.source, self.data, self.binary, python_executable=sys.executable, branch='codex/v9.10', auto_update='off')

    @unittest.skipUnless(os.name == 'posix', 'POSIX external storage aliases')
    def test_alias_home_install_reuse_and_managed_link_rejection(self):
        alias = self.base / 'home-alias'
        alias.symlink_to(self.base, target_is_directory=True)
        profile = self.base / '.bashrc'
        profile.write_text('# user content\n')
        before = files(self.data)
        with mock.patch.object(main, '_environment'), mock.patch.object(Path, 'home', return_value=alias):
            with contextlib.redirect_stdout(io.StringIO()):
                result = main.main(['install', '--data-dir', str(alias / 'tool'), '--bin-dir', str(alias / 'bin'),
                                    '--existing', 'reuse'], source_root=self.source)
            self.assertEqual(result, 0)
            self.assertEqual(files(self.data), before)
            self.assertEqual(shell.register_path(self.binary)['writes'], 0)
            self.assertEqual(shell.unregister_path(self.binary)['writes'], 1)
        self.assertEqual(profile.read_text(), '# user content\n')
        self.assertEqual(paths.storage_location(alias / 'new/tool'), self.base / 'new/tool')
        target = self.base / 'user-owned'
        target.mkdir()
        link = self.base / 'redirected'
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            paths.storage_location(alias / 'redirected')
        (self.data / 'redirected').symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            paths.checked_path(self.data / 'redirected/file')
        self.assertEqual(list(target.iterdir()), [])

    def test_location_resolution_leaves_managed_leaf_for_strict_check(self):
        value = self.base / 'outer/tool'
        physical = self.base / 'physical'
        with mock.patch.object(paths, 'os', mock.Mock(wraps=os, name='posix')) as platform:
            platform.name = 'posix'
            with mock.patch.object(Path, 'resolve', return_value=physical) as resolve:
                with mock.patch.object(paths, 'checked_path', return_value=physical / 'tool') as check:
                    self.assertEqual(paths.storage_location(value), physical / 'tool')
                resolve.assert_called_once_with()
                check.assert_called_once_with(physical / 'tool')
            with mock.patch.object(Path, 'resolve', side_effect=RuntimeError('Symlink loop')):
                with self.assertRaisesRegex(ValueError, 'installation parent'):
                    paths.storage_location(value)
                with self.assertRaisesRegex(ValueError, 'account home'):
                    paths.user_home(self.base)

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

    def test_beta_reinstall_retires_legacy_pin_and_preserves_other_preferences(self):
        previous = source(self.base / 'previous source', '0.10.0-beta', commit='b' * 40)
        dist.install_tool(previous, self.data, self.binary, python_executable=sys.executable,
                          repository='git@github.com:sholee-pt/Harness.git', branch='codex/v0.10.0-beta', auto_update='off')
        candidate = source(self.base / 'beta source', '0.11.0-beta', commit='c' * 40)
        with mock.patch.object(main, '_environment'), contextlib.redirect_stdout(io.StringIO()):
            result = main.main(['install', '--data-dir', str(self.data), '--bin-dir', str(self.binary),
                                '--no-modify-path', '--existing', 'reuse'], source_root=candidate)
        self.assertEqual(result, 0)
        status = dist.installed_status(self.data)
        self.assertIsNone(status['branch'])
        self.assertEqual(status['auto_update'], 'off')
        self.assertEqual(status['version'], '0.11.0-beta')
        self.assertEqual(status['repository'], 'git@github.com:sholee-pt/Harness-Codex.git')

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

    @unittest.skipUnless(os.name == 'posix', 'Native Unix package filenames')
    def test_native_runtime_names_do_not_inherit_windows_archive_restrictions(self):
        runtime, data = self.base / 'native-runtime', self.base / 'native-tool'
        prefix = runtime / 'envs/harness'
        prefix.mkdir(parents=True)
        (runtime / footprint.MARKER).write_bytes(footprint.marker(data))
        for name in ('con', 'native:package.'):
            (prefix / name).write_bytes(b'native package file')
        with mock.patch.object(sys, 'prefix', str(prefix)), mock.patch.object(Path, 'home', return_value=self.home):
            reference = footprint.record(runtime, data, attach=False)
        plan = footprint.inspect(reference, data)
        self.assertIn('envs/harness/native:package.', plan['files'])
        self.assertFalse(data.exists(), 'Runtime validation must precede CLI state creation')
        for name in ('../outside', '/outside', 'envs/../../outside', 'envs//file'):
            with self.assertRaises(ValueError):
                footprint._relative(name)

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

    def test_missing_recorded_receipt_does_not_reclaim_user_files_on_reinstall(self):
        (self.runtime / footprint.RECEIPT).unlink()
        (self.prefix / 'user-added.txt').write_bytes(b'keep')
        before = files(self.runtime)
        with mock.patch.object(sys, 'prefix', str(self.prefix)), self.assertRaisesRegex(ValueError, 'missing'):
            footprint.record(self.runtime, self.data)
        self.assertEqual(files(self.runtime), before)

    def windows_cleanup(self):
        plan = {**self.plan(), 'waitPid': 2147483647}
        job = self.base / 'job'
        job.mkdir()
        payload = json.dumps(plan).encode()
        (job / 'plan.json').write_bytes(payload)
        script = job / 'cleanup.ps1'
        script.write_bytes(Path(footprint.__file__).with_name('runtime_cleanup.ps1').read_bytes())
        command, environment = footprint._windows_command(script, hashlib.sha256(payload).hexdigest())
        result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr + ((job / 'error.txt').read_text(encoding='utf-8-sig') if (job / 'error.txt').exists() else ''))
        return job

    @unittest.skipUnless(os.name == 'nt', 'Native Windows deferred cleanup')
    def test_windows_helper_removes_disposable_runtime_and_preserves_other_settings(self):
        job = self.windows_cleanup()
        self.assertFalse(self.runtime.exists())
        self.assertFalse(job.exists())
        self.assertEqual(self.profile.read_bytes(), (str(self.other) + '\r\n').encode())

    @unittest.skipUnless(os.name == 'nt', 'Native Windows deferred cleanup')
    def test_windows_package_tree_cleanup_completes_within_native_process_deadline(self):
        # Exercise actual file IO/provider costs rather than mocking deletion.
        for directory in range(20):
            folder = self.prefix / f'Lib/site-packages/package{directory}/nested/data'
            folder.mkdir(parents=True)
            for index in range(100):
                (folder / f'file{index}.txt').write_bytes(b'package content')
        (self.runtime / footprint.RECEIPT).unlink()
        (self.data / 'runtime.json').unlink()
        with mock.patch.object(sys, 'prefix', str(self.prefix)), mock.patch.object(Path, 'home', return_value=self.home):
            self.reference = footprint.record(self.runtime, self.data)
        (self.prefix / 'python.fixture').chmod(0o444)
        job = self.windows_cleanup()
        self.assertFalse(self.runtime.exists())
        self.assertFalse(job.exists())
        self.assertEqual(self.profile.read_bytes(), (str(self.other) + '\r\n').encode())

    @unittest.skipUnless(os.name == 'nt', 'Native Windows deferred cleanup')
    def test_windows_helper_preserves_same_size_changes_added_files_and_junction_target(self):
        original = (self.prefix / 'python.fixture').read_bytes()
        (self.prefix / 'python.fixture').write_bytes(b'x' * len(original))
        (self.prefix / 'extra.txt').write_bytes(b'user added')
        outside = self.base / 'external'
        outside.mkdir()
        (outside / 'precious.txt').write_bytes(b'keep external')
        link = self.prefix / 'user-link'
        result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.addCleanup(lambda: link.rmdir() if link.is_dir() else None)
        # Even a recorded file path whose parent later becomes a junction must
        # not be followed. Use the separately hashed fixture plan transport.
        plan = self.plan()
        plan['files']['envs/harness/user-link/precious.txt'] = footprint._entry(outside / 'precious.txt')
        with mock.patch.object(self, 'plan', return_value=plan):
            job = self.windows_cleanup()
        self.assertTrue((job / 'remaining.json').exists())
        self.assertEqual((self.prefix / 'python.fixture').read_bytes(), b'x' * len(original))
        self.assertEqual((self.prefix / 'extra.txt').read_bytes(), b'user added')
        self.assertEqual((outside / 'precious.txt').read_bytes(), b'keep external')


if __name__ == '__main__':
    unittest.main()
