"""Reinstall choices, ownership receipts and bounded runtime cleanup."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from harness_cli import distribution as dist, footprint, main, setup, shell, paths
from test_cli_distribution import files, source


class ShellRuntimeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.bash = shutil.which('bash')
        if os.name == 'nt':
            candidate = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/bin/bash.exe'
            self.bash = str(candidate) if candidate.is_file() else None
        if not self.bash:
            self.skipTest('Bash is unavailable')
        temporary = tempfile.TemporaryDirectory(prefix='harness-runtime-recovery-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.data = self.base / 'tool data'
        self.runtime = self.base / 'tool data-runtime'
        self.prefix = self.runtime / 'envs/harness'
        self.prefix.mkdir(parents=True)
        self.data.mkdir()
        self.marker = self.runtime / '.harness-runtime-owner'
        self.marker.write_text('harness-codex runtime v1\n' + self.posix(self.data) + '\n', encoding='utf-8', newline='\n')
        (self.runtime / '.harness-runtime-files.json').write_text('{"oldReceipt":true}\n')
        (self.prefix / 'user-file').write_text('preserve these bytes\n')
        self.source = self.base / 'source'
        (self.source / 'installer').mkdir(parents=True)
        (self.source / 'harness_cli').mkdir()
        root = Path(__file__).resolve().parents[1]
        for relative in ('installer/install.sh', 'harness_cli/prepare_conda.sh'):
            (self.source / relative).write_bytes((root / relative).read_bytes())
        (self.source / 'harness.py').write_text('# The fixture interpreter does not run Python.\n')
        self.binary = self.base / 'bin'
        self.binary.mkdir()
        self.manager = self.binary / 'conda'
        self.script(self.manager, '''printf '%s\n' "$*" >> "$HOME/manager-calls"
case "$1" in
  env) printf '{"envs":[]}\n' ;;
  create)
    [[ ! -f "$HOME/fail-create" ]] || exit 23
    prefix=$3
    mkdir -p "$prefix/conda-meta" "$prefix/bin"
    touch "$prefix/conda-meta/history"
    printf '#!/bin/bash\nexit 0\n' > "$prefix/bin/python"
    chmod +x "$prefix/bin/python" ;;
  run) shift 4; "$@" ;;
esac
''')

    @staticmethod
    def posix(path):
        value = Path(path).as_posix()
        return '/' + value[0].lower() + value[2:] if os.name == 'nt' else value

    @staticmethod
    def script(path, body):
        path.write_text('#!/bin/bash\nset -eu\n' + body, encoding='utf-8', newline='\n')
        path.chmod(0o755)

    def install(self):
        environment = {**os.environ, 'HOME': self.posix(self.base), 'TMPDIR': self.posix(self.base),
                       'CONDA_EXE': self.posix(self.manager), 'TERM': 'dumb'}
        command = 'export PATH="$HOME/bin:/usr/bin:/bin:$PATH"; bash "$1" --data-dir "$2" --no-modify-path --activate skip'
        result = subprocess.run([self.bash, '-c', command, 'fixture', self.posix(self.source / 'installer/install.sh'),
                                 self.posix(self.data)], env=environment, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
        logs = list(self.base.glob('harness-codex-install-log.*'))
        return result, '\n'.join(path.read_text() for path in logs)

    def test_orphan_with_old_receipt_is_preserved_and_reinstall_is_idempotent(self):
        before = files(self.runtime)
        result, log = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + log)
        backups = list(self.base.glob('tool data-runtime.recovery.*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(files(backups[0] / 'runtime'), before)
        self.assertTrue((self.prefix / 'conda-meta/history').is_file())
        self.assertFalse((self.runtime / '.harness-runtime-files.json').exists())
        self.assertIn('Preserved incomplete Harness runtime:', result.stdout)
        self.assertIn(self.posix(backups[0] / 'runtime'), log)
        result, log = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + log)
        self.assertEqual(list(self.base.glob('tool data-runtime.recovery.*')), backups)
        self.assertEqual((self.base / 'manager-calls').read_text().count('create '), 1)
        self.assertEqual(files(backups[0] / 'runtime'), before)

    def test_failed_recreation_keeps_backup_and_reports_it(self):
        before = files(self.runtime)
        (self.base / 'fail-create').touch()
        result, log = self.install()
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr + log)
        backup = next(self.base.glob('tool data-runtime.recovery.*'))
        self.assertEqual(files(backup / 'runtime'), before)
        self.assertIn('Preserved incomplete Harness runtime:', result.stderr)
        self.assertNotIn('Installation complete.', result.stdout)
        self.assertFalse((self.base / 'tool data-runtime.bootstrap-lock').exists())

    def test_orphan_receipt_without_environment_is_not_reused(self):
        (self.prefix / 'user-file').unlink()
        self.prefix.rmdir()
        before = files(self.runtime)
        result, log = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + log)
        backup = next(self.base.glob('tool data-runtime.recovery.*'))
        self.assertEqual(files(backup / 'runtime'), before)
        self.assertTrue((self.prefix / 'conda-meta/history').is_file())
        self.assertFalse((self.runtime / '.harness-runtime-files.json').exists())

    def test_incomplete_miniforge_without_environment_or_receipt_is_preserved(self):
        (self.prefix / 'user-file').unlink()
        self.prefix.rmdir()
        (self.runtime / '.harness-runtime-files.json').unlink()
        partial = self.runtime / 'conda/partial'
        partial.mkdir(parents=True)
        (partial / 'retained.txt').write_text('incomplete Miniforge extraction\n')
        before = files(self.runtime)
        result, log = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + log)
        backup = next(self.base.glob('tool data-runtime.recovery.*'))
        self.assertEqual(files(backup / 'runtime'), before)
        self.assertTrue((self.prefix / 'conda-meta/history').is_file())
        self.assertFalse((self.runtime / 'conda').exists())

    def test_active_reference_or_unowned_runtime_stops_before_conda(self):
        for state in ('active.json', 'runtime.json', '.install.lock', 'unowned'):
            with self.subTest(state=state):
                path = self.data / state if state != 'unowned' else self.marker
                original = path.read_bytes() if path.exists() else None
                path.write_text('unrecognized state')
                before = files(self.runtime)
                try:
                    result, log = self.install()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('harness:', result.stderr)
                    self.assertIn(self.posix(self.runtime), log)
                    self.assertEqual(files(self.runtime), before)
                    self.assertFalse((self.base / 'manager-calls').exists())
                    self.assertFalse(list(self.base.glob('tool data-runtime.recovery.*')))
                finally:
                    if original is None:
                        path.unlink()
                    else:
                        path.write_bytes(original)

    def test_concurrent_installer_lock_is_preserved(self):
        lock = self.base / 'tool data-runtime.bootstrap-lock'
        lock.mkdir()
        result, log = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Runtime setup lock exists', log)
        self.assertTrue(lock.is_dir())
        self.assertFalse((self.base / 'manager-calls').exists())
        self.assertFalse(list(self.base.glob('tool data-runtime.recovery.*')))

    @unittest.skipUnless(os.name == 'posix', 'Native symbolic links')
    def test_runtime_link_is_preserved(self):
        outside = self.base / 'unrelated'
        self.prefix.rename(outside)
        self.prefix.symlink_to(outside, target_is_directory=True)
        result, log = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Runtime path is a symlink', log)
        self.assertEqual((outside / 'user-file').read_text(), 'preserve these bytes\n')
        self.assertFalse((self.base / 'manager-calls').exists())


class InstallIntegrationTests(unittest.TestCase):
    def test_new_linux_install_prepares_codex_without_a_project(self):
        from types import SimpleNamespace
        from harness_cli import codex_integration
        root = Path(__file__).resolve().parents[1]
        args = SimpleNamespace(no_modify_path=False, no_codex_integration=False, data_dir=Path('tool'))
        with mock.patch.object(setup.sys, 'platform', 'linux'), mock.patch.object(codex_integration, 'read', return_value=None), mock.patch.object(codex_integration, 'install', return_value={}) as install, contextlib.redirect_stdout(io.StringIO()):
            setup.prepare_integration(args, root)
        install.assert_called_once_with(args.data_dir, root)

    def test_tool_only_and_other_platform_installs_do_not_fetch_codex(self):
        from types import SimpleNamespace
        from harness_cli import codex_integration
        for platform, no_path, no_integration in [('linux', True, False), ('linux', False, True), ('win32', False, False)]:
            with self.subTest(platform=platform, no_path=no_path, no_integration=no_integration):
                args = SimpleNamespace(no_modify_path=no_path, no_codex_integration=no_integration, data_dir=Path('tool'))
                with mock.patch.object(setup.sys, 'platform', platform), mock.patch.object(codex_integration, 'install') as install:
                    setup.prepare_integration(args, Path('unused'))
                install.assert_not_called()


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
                with self.assertRaisesRegex(ValueError, 'path parent'):
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
            with mock.patch('builtins.input', side_effect=['\x1b', '\x1b[C', 'invalid', '']):
                self.assertEqual(setup.choose(self.data, self.binary, 'ask')[0], 'reuse')
            with mock.patch('builtins.input', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    setup.choose(self.data, self.binary, 'ask')
            with mock.patch('builtins.input', side_effect=EOFError):
                with self.assertRaisesRegex(ValueError, '--existing'):
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

    def test_large_runtime_receipt_preflight_reinstall_and_cleanup(self):
        receipt = self.runtime / footprint.RECEIPT
        # JSON whitespace exercises the actual byte limit without creating
        # thousands of redundant package files in every regression run.
        payload = receipt.read_bytes().ljust(4 * 1024 * 1024 + 1, b' ')
        receipt.write_bytes(payload)
        self.reference['receiptSha256'] = hashlib.sha256(payload).hexdigest()
        (self.data / 'runtime.json').unlink()
        self.data.rmdir()
        before = receipt.read_bytes(), receipt.stat().st_mtime_ns
        with self.assertRaisesRegex(dist.DistributionError, 'metadata is too large'):
            dist._read_json(receipt)
        with mock.patch.object(sys, 'prefix', str(self.prefix)):
            self.assertEqual(footprint.record(self.runtime, self.data, attach=False), self.reference)
            self.assertFalse(self.data.exists(), 'Preflight must not publish CLI state')
            self.data.mkdir()
            self.assertEqual(footprint.record(self.runtime, self.data), self.reference)
            self.assertEqual(footprint.record(self.runtime, self.data), self.reference)
        self.assertEqual((receipt.read_bytes(), receipt.stat().st_mtime_ns), before)
        self.assertEqual(footprint.cleanup(self.plan()), [])
        self.assertFalse(self.runtime.exists())
        self.assertEqual(self.profile.read_bytes(), (str(self.other) + '\r\n').encode())

    def test_oversized_runtime_receipt_is_refused_without_writes(self):
        receipt = self.runtime / footprint.RECEIPT
        payload = receipt.read_bytes().ljust(dist.MAX_FILE_BYTES + 1, b' ')
        receipt.write_bytes(payload)
        self.reference['receiptSha256'] = hashlib.sha256(payload).hexdigest()
        before = files(self.runtime), files(self.data)
        with mock.patch.object(sys, 'prefix', str(self.prefix)):
            for operation in (lambda: footprint.record(self.runtime, self.data), self.plan,
                              lambda: footprint.cleanup({**self.reference, 'dataRoot': str(self.data)})):
                with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, 'too large'):
                    operation()
                self.assertEqual((files(self.runtime), files(self.data)), before)

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
