"""Tool uninstall confirmation, ownership, rollback and scoped PATH behavior."""
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

from harness_cli import distribution as dist, uninstall
from test_cli_distribution import source, files, A, B


class UninstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.enterContext(mock.patch.dict(os.environ, {'HARNESS_CREDENTIAL_HOME': str(self.base / 'credentials'), 'CODEX_HOME': str(self.base / 'codex')}))
        self.source = source(self.base / 'source', '9.8')
        self.data, self.bin = self.base / 'data', self.base / 'bin'
        self.state = dist.install_tool(self.source, self.data, self.bin, sys.executable)
        self.path = mock.patch.object(uninstall, '_path_action', return_value={'state': 'preserved', 'writes': 0})
        self.path_action = self.path.start()
        self.addCleanup(self.path.stop)

    def invoke(self, answer='yes', *, tty=True, dry_run=False):
        with redirect_stdout(io.StringIO()) as output, mock.patch.object(sys.stdin, 'isatty', return_value=tty), \
                mock.patch.object(sys.stdout, 'isatty', return_value=tty), mock.patch('builtins.input', return_value=answer) as prompt:
            result = uninstall.run(self.data, dry_run=dry_run)
        return result, output.getvalue(), prompt

    def complete_source(self):
        complete = self.base / 'complete'
        for name, data in dist._snapshot(Path(__file__).resolve().parents[1]).items():
            path = complete / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return complete

    def test_dry_run_cancel_eof_and_nonterminal_never_modify_installation(self):
        before = files(self.base)
        self.assertEqual(self.invoke(tty=False, dry_run=True)[0], 0)
        for answer in ('', 'no', 'y', 'YES', 'yes '):
            self.assertIn('cancelled', self.invoke(answer)[1])
        with self.assertRaisesRegex(ValueError, 'interactive terminal'):
            self.invoke(tty=False)
        with mock.patch.object(sys.stdin, 'isatty', return_value=True), redirect_stdout(io.StringIO()), \
                mock.patch.object(sys.stdout, 'isatty', return_value=True), mock.patch('builtins.input', side_effect=EOFError):
            self.assertEqual(uninstall.run(self.data), 0)
        self.assertEqual(files(self.base), before)

    def test_confirmed_removal_keeps_source_projects_conda_and_shared_commands(self):
        user = self.bin / 'another-command'
        user.write_text('keep me')
        project = self.base / 'project/.harness/manifest.json'
        project.parent.mkdir(parents=True)
        project.write_text('user project')
        before_source = files(self.source)
        status, output, prompt = self.invoke()
        self.assertEqual(status, 0)
        self.assertIn('Uninstalled harness-codex', output)
        prompt.assert_called_once()
        self.assertFalse(self.data.exists())
        for path in self.state['launchers']:
            self.assertFalse(Path(path).exists())
        self.assertEqual(user.read_text(), 'keep me')
        self.assertEqual(project.read_text(), 'user project')
        self.assertEqual(files(self.source), before_source)
        self.assertTrue(Path(sys.executable).is_file())
        self.path_action.assert_not_called()
        self.assertFalse(list(self.base.glob('.harness-uninstall-*')))
        self.assertFalse(list(self.bin.glob('.harness-uninstall-*')))

    def test_all_retained_releases_are_checked_and_removed(self):
        candidate = source(self.base / 'candidate', '9.9', B)
        dist.install_tool(candidate, self.data, self.bin, sys.executable)
        self.assertEqual(len(list((self.data / 'releases').iterdir())), 2)
        self.invoke()
        self.assertFalse(self.data.exists())

    def test_credential_removal_requires_completed_confirmed_uninstall(self):
        from harness_cli import jev_auth
        with mock.patch.object(jev_auth, 'forget', return_value=True) as forget:
            self.invoke(dry_run=True)
            self.invoke(answer='no')
            forget.assert_not_called()
            self.invoke()
            forget.assert_called_once()

    def hooks(self):
        from harness_cli import hook_state, maintenance
        maintenance.install_hooks(self.source, tool_home=self.data)
        home = self.base / 'codex'
        receipt = home / 'harness-maintenance-hooks.json'
        before = b'model = "preserve-user-choice"\n'
        after = before + b'\n[hooks.state.owned]\ntrusted_hash = "current"\nenabled = true\n'
        pending = hook_state.begin_trust(hook_state.receipt(receipt.read_bytes()), before,
                                        {'owned': {'trusted_hash': 'current', 'enabled': True}})
        receipt.write_bytes(hook_state.encoded(hook_state.finish_trust(pending, after, ['owned'])))
        (home / 'config.toml').write_bytes(after)
        return home

    def test_path_failure_restores_hooks_receipt_and_tool_together(self):
        home = self.hooks()
        before = {path: path.read_bytes() for path in home.iterdir()}
        from harness_cli.hook_state import file_metadata
        metadata = {path: file_metadata(path) for path in home.iterdir()}
        self.path_action.side_effect = lambda path, dry_run=True, **kwargs: ({'state': 'would-remove', 'writes': 1}
            if dry_run else (_ for _ in ()).throw(OSError('profile write failed')))
        with self.assertRaisesRegex(OSError, 'profile write failed'):
            self.invoke()
        self.assertEqual({path: path.read_bytes() for path in home.iterdir()}, before)
        self.assertEqual({path: file_metadata(path) for path in home.iterdir()}, metadata)
        self.assertEqual(dist.installed_status(self.data)['version'], '9.8')

    def test_receipt_deletion_failure_restores_already_removed_hooks(self):
        from harness_cli import hook_state
        home = self.hooks()
        before = {path: path.read_bytes() for path in home.iterdir()}
        replace = hook_state.replace_file
        def fail_receipt(path, original, desired):
            if path.name == 'harness-maintenance-hooks.json' and desired is None:
                raise OSError('receipt is busy')
            return replace(path, original, desired)
        with mock.patch.object(hook_state, 'replace_file', side_effect=fail_receipt), self.assertRaisesRegex(OSError, 'receipt is busy'):
            self.invoke()
        self.assertEqual({path: path.read_bytes() for path in home.iterdir()}, before)
        self.assertEqual(dist.installed_status(self.data)['version'], '9.8')

    def test_hook_edit_after_confirmation_is_preserved_before_removal(self):
        home = self.hooks()
        path = home / 'hooks.json'
        edited = path.read_bytes() + b'\n'
        def confirm(_):
            path.write_bytes(edited)
            return 'yes'
        with redirect_stdout(io.StringIO()), mock.patch.object(sys.stdin, 'isatty', return_value=True), \
                mock.patch.object(sys.stdout, 'isatty', return_value=True), mock.patch('builtins.input', side_effect=confirm):
            with self.assertRaisesRegex(ValueError, 'changed after the preview'):
                uninstall.run(self.data)
        self.assertEqual(path.read_bytes(), edited)
        self.assertEqual(dist.installed_status(self.data)['version'], '9.8')

    def test_concurrent_hook_edit_during_rollback_keeps_recovery_copy(self):
        home = self.hooks()
        path = home / 'hooks.json'
        original = path.read_text()
        def fail_path(pathname, dry_run=True, **kwargs):
            if dry_run:
                return {'state': 'would-remove', 'writes': 1}
            path.write_text('user edited hooks')
            raise OSError('profile write failed')
        self.path_action.side_effect = fail_path
        with self.assertRaisesRegex(ValueError, 'manual recovery'):
            self.invoke()
        self.assertEqual(path.read_text(), 'user edited hooks')
        recovery, = self.base.glob('.harness-uninstall-*/hook-recovery-*.json')
        import json
        self.assertEqual(json.loads(recovery.read_text())['before'], original)
        self.assertEqual(dist.installed_status(self.data)['version'], '9.8')

    def test_installed_cli_runs_confirmation_and_self_removal_in_a_fresh_process(self):
        # Real installed source and launcher; only terminal detection is adapted
        # in the confirmed child so this also runs on noninteractive Windows CI.
        complete = self.complete_source()
        data, binary = self.base / 'real-data', self.base / 'real-bin'
        dist.install_tool(complete, data, binary, sys.executable)
        (binary / 'another-command').write_text('preserve shared PATH')
        before = files(data)
        command = [sys.executable, '-B', str(data / 'launcher.py'), 'uninstall']
        preview = subprocess.run([*command, '--dry-run'], capture_output=True, text=True, timeout=60)
        self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
        rejected = subprocess.run(command, input='yes\n', capture_output=True, text=True, timeout=60)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('interactive terminal', rejected.stderr)
        self.assertEqual(files(data), before)
        adapted = ('import runpy,sys; sys.stdin.isatty=lambda:True; sys.stdout.isatty=lambda:True; '
                   'sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name="__main__")')
        confirmed = subprocess.run([sys.executable, '-B', '-c', adapted, str(data / 'launcher.py'), 'uninstall'],
                                   input='yes\n', capture_output=True, text=True, timeout=60)
        self.assertEqual(confirmed.returncode, 0, confirmed.stdout + confirmed.stderr)
        self.assertIn('Type yes', confirmed.stdout)
        self.assertIn('Uninstalled harness-codex', confirmed.stdout)
        self.assertNotIn('could not be cleaned', confirmed.stdout)
        self.assertFalse(data.exists())
        self.assertEqual([path.name for path in binary.iterdir()], ['another-command'])

    @unittest.skipUnless(os.name == 'nt', 'Native Windows batch self-cleanup')
    def test_windows_batch_launcher_finishes_its_own_cleanup_without_stderr(self):
        complete = self.complete_source()
        entry = complete / 'harness.py'
        text = entry.read_text()
        marker = 'from harness_cli.main import main'
        self.assertIn(marker, text)
        # Adapt terminal detection before binding the installation receipt, so
        # the native .cmd launcher, ownership checks and cleanup all remain real.
        entry.write_text(text.replace(marker, 'sys.stdin.isatty = lambda: True\nsys.stdout.isatty = lambda: True\n' + marker))
        data, binary = self.base / 'batch-data', self.base / 'batch-bin'
        dist.install_tool(complete, data, binary, sys.executable)
        command = binary / 'harness-codex.cmd'
        result = subprocess.run([str(command), 'uninstall'], input='yes\n', capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn('Uninstalled harness-codex', result.stdout)
        self.assertFalse(data.exists())
        self.assertEqual(list(binary.iterdir()), [])

    def test_recognized_completed_migration_lock_is_removed_and_unknown_lock_is_preserved(self):
        lock = self.data / '.launcher-migration.lock'
        lock.write_bytes(b'unknown')
        with self.assertRaisesRegex(ValueError, 'Unrecognized launcher migration lock'):
            uninstall.prepare(self.data)
        lock.write_bytes(b'Harness launcher migration lock v1\n')
        self.invoke()
        self.assertFalse(self.data.exists())

    def test_edits_unknown_files_journals_and_old_release_changes_block_before_prompt(self):
        candidate = source(self.base / 'candidate', '9.9', B)
        dist.install_tool(candidate, self.data, self.bin, sys.executable)
        for path in (self.data / 'releases' / A / 'harness.py', self.bin / 'harness-codex',
                     self.data / 'user.txt', self.data / '.launcher-migration.json',
                     self.data / 'receipts/orphan.json', self.data / 'releases' / B / 'user.txt'):
            with self.subTest(path=path):
                original = path.read_bytes() if path.exists() else None
                path.write_bytes(b'edited')
                before = files(self.base)
                with mock.patch('builtins.input') as prompt, self.assertRaises(ValueError):
                    uninstall.run(self.data)
                prompt.assert_not_called()
                self.assertEqual(files(self.base), before)
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)
        for name in ('unknown-empty', '.git'):
            directory = self.data / name
            directory.mkdir()
            with self.assertRaises(ValueError):
                uninstall.prepare(self.data)
            directory.rmdir()

    def test_lock_and_changed_confirmation_plan_prevent_mutation(self):
        plan = uninstall.prepare(self.data)
        lock = self.data / '.install.lock'
        lock.write_text('busy')
        with self.assertRaises(ValueError):
            uninstall.prepare(self.data)
        lock.unlink()
        dist.mark_check(self.data, now=123)
        before = files(self.base)
        with self.assertRaisesRegex(ValueError, 'changed after the preview'):
            uninstall.remove(plan)
        self.assertEqual(files(self.base), before)

    def test_staging_and_path_failures_restore_bytes_modes_and_mtimes(self):
        for operation in ('move', 'path'):
            with self.subTest(operation=operation):
                path_preview = {'state': 'would-remove', 'fingerprint': 'test', 'writes': 0}
                self.path_action.return_value = path_preview
                plan = uninstall.prepare(self.data)
                before = files(self.base)
                real_replace = os.replace
                count = 0
                def move(original, target):
                    nonlocal count
                    count += 1
                    if operation == 'move' and count == 3:
                        raise PermissionError('injected staging failure')
                    return real_replace(original, target)
                def path_action(*args, **kwargs):
                    if operation == 'path' and not kwargs.get('dry_run', True):
                        raise ValueError('injected PATH failure')
                    return path_preview
                with mock.patch.object(os, 'replace', side_effect=move), \
                        mock.patch.object(uninstall, '_path_action', side_effect=path_action), \
                        self.assertRaises((PermissionError, ValueError)):
                    uninstall.remove(plan)
                self.assertEqual(files(self.base), before)
                dist.installed_status(self.data)
                self.assertFalse(list(self.base.glob('.harness-uninstall-*')))

    def test_cleanup_failure_is_reported_and_retains_changed_staged_file(self):
        plan = uninstall.prepare(self.data)
        real_purge = uninstall._purge_files
        changed = []
        def purge(files, directories):
            path = next(path for path in files if path.name == 'harness.py')
            path.write_text('concurrent edit')
            changed.append(path)
            return real_purge(files, directories)
        with mock.patch.object(uninstall, '_purge_files', side_effect=purge):
            result = uninstall.remove(plan)
        self.assertEqual(result['state'], 'uninstalled')
        self.assertIn(str(changed[0]), result['cleanupRemaining'])
        self.assertEqual(changed[0].read_text(), 'concurrent edit')
        self.assertFalse(self.data.exists())

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink fixture')
    def test_symlink_inside_managed_storage_is_preserved(self):
        (self.data / 'linked').symlink_to(self.source, target_is_directory=True)
        before = files(self.source)
        with self.assertRaises(ValueError):
            uninstall.prepare(self.data)
        self.assertEqual(files(self.source), before)


if __name__ == '__main__':
    unittest.main()
