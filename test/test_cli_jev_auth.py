"""Credential storage, interactive setup and provider failures cannot leak secrets."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.error
import warnings

from harness_cli import jev, jev_auth as auth, jev_client, main, project, graft

REPO = Path(__file__).resolve().parents[1]
SECRET = 'fixture-secret-not-a-real-key'


class JevAuthTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.root = self.base / 'credentials'
        self.stack = self.enterContext(contextlib.ExitStack())
        self.stack.enter_context(mock.patch.dict(os.environ, {'HARNESS_CREDENTIAL_HOME': str(self.root), 'TYPESAFE_API_KEY': ''}))
        # Storage semantics run locally too; real POSIX ownership tests run on Linux.
        if os.name != 'posix':
            self.stack.enter_context(mock.patch.object(auth, '_supported', return_value=True))
            self.stack.enter_context(mock.patch.object(auth, '_private'))

    def login(self, *, answer='p', key=SECRET, verification='valid', **kwargs):
        with mock.patch.object(auth.sys.stdin, 'isatty', return_value=True), mock.patch.object(auth.sys.stdout, 'isatty', return_value=True):
            with mock.patch('builtins.input', return_value=answer), mock.patch.object(auth.getpass, 'getpass', return_value=key):
                with mock.patch.object(auth, 'validate', return_value=verification) as validate, contextlib.redirect_stdout(io.StringIO()) as out:
                    with mock.patch.object(auth.sys.stdout, 'isatty', return_value=True):
                        result = auth.login(jev.MODEL, **kwargs)
                self.assertNotIn(SECRET, out.getvalue() + repr(result))
                return result, validate

    def test_store_reuse_and_environment_precedence_without_shell_changes(self):
        shell = self.base / '.bashrc'
        shell.write_text('export EXISTING=value\n')
        auth.save(SECRET)
        self.assertEqual(auth.resolve(), SECRET)
        path = self.root / 'typesafe.json'
        before = path.read_bytes(), path.stat().st_mtime_ns
        auth.save(SECRET)
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        result, validate = self.login()
        self.assertEqual(result['state'], 'stored')
        validate.assert_not_called()
        with mock.patch.dict(os.environ, {'TYPESAFE_API_KEY': 'override'}):
            self.assertEqual(auth.resolve(), 'override')
            self.assertEqual(auth.login(jev.MODEL)['state'], 'environment')
        self.assertEqual(shell.read_text(), 'export EXISTING=value\n')
        self.assertNotIn(SECRET, json.dumps(jev._result(None)))

    def test_invalid_or_foreign_storage_is_preserved(self):
        self.root.mkdir(mode=0o700)
        path = self.root / 'typesafe.json'
        for data in ('{broken', json.dumps({'owner': 'someone-else', 'apiKey': SECRET}), 'x' * (auth.MAX_BYTES + 1)):
            path.write_text(data)
            path.chmod(0o600)
            self.assertIsNone(auth.resolve())
            with self.assertRaises(ValueError):
                auth.save('replacement')
            self.assertEqual(path.read_text(), data)
            with self.assertRaises(ValueError):
                auth.forget()

    def test_relative_storage_and_invalid_environment_are_not_used(self):
        with mock.patch.dict(os.environ, {'HARNESS_CREDENTIAL_HOME': 'project-relative'}):
            self.assertIsNone(auth.resolve())
            with self.assertRaisesRegex(ValueError, 'absolute'):
                auth.save(SECRET)
        with mock.patch.dict(os.environ, {'TYPESAFE_API_KEY': 'not\na\nkey'}):
            self.assertEqual(auth.login(jev.MODEL)['state'], 'invalid')
        self.assertFalse(self.root.exists())

    def test_atomic_write_failure_preserves_old_key_and_removes_temporary_file(self):
        auth.save(SECRET)
        with mock.patch.object(auth.os, 'replace', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError):
                auth.save('replacement')
        self.assertEqual(auth.resolve(), SECRET)
        self.assertEqual([p.name for p in self.root.iterdir()], ['typesafe.json'])

    def test_login_stores_new_key_and_rejects_invalid_replacement(self):
        result, validate = self.login()
        self.assertEqual(result['verification'], 'valid')
        validate.assert_called_once_with(SECRET, jev.MODEL)
        self.assertEqual(auth.resolve(), SECRET)
        result, _ = self.login(key='invalid-new-key', verification='invalid', replace=True)
        self.assertEqual(result['state'], 'invalid')
        self.assertEqual(auth.resolve(), SECRET)

    def test_unavailable_provider_saves_with_unverified_state(self):
        result, _ = self.login(verification='unverified')
        self.assertEqual(result['verification'], 'unverified')
        self.assertEqual(auth.resolve(), SECRET)

    def test_skip_blank_and_noninteractive_never_probe_or_save(self):
        for options in ({'answer': 's'}, {'key': ''}, {'interactive': False}):
            result, validate = self.login(**options)
            self.assertIn(result['state'], {'skipped', 'missing'})
            validate.assert_not_called()
            self.assertFalse(self.root.exists())
        with mock.patch.object(auth.sys.stdin, 'isatty', return_value=False), mock.patch.object(auth.getpass, 'getpass') as prompt:
            self.assertEqual(auth.login(jev.MODEL)['state'], 'missing')
            prompt.assert_not_called()

    def test_ssh_prints_link_without_launching_server_browser(self):
        with mock.patch.dict(os.environ, {'SSH_CONNECTION': 'fixture', 'BROWSER': '', 'DISPLAY': '', 'WAYLAND_DISPLAY': ''}), mock.patch.object(auth.subprocess, 'run') as browser:
            result, _ = self.login(answer='')
        self.assertEqual(result['state'], 'saved')
        browser.assert_not_called()

    def test_browser_timeout_still_allows_key_entry(self):
        with mock.patch.dict(os.environ, {'SSH_CONNECTION': '', 'SSH_TTY': '', 'SSH_CLIENT': ''}):
            with mock.patch.object(auth.subprocess, 'run', side_effect=subprocess.TimeoutExpired('browser', 3)) as browser:
                result, _ = self.login(answer='')
        self.assertEqual(result['state'], 'saved')
        self.assertEqual(browser.call_args.kwargs['timeout'], 3)

    def test_remote_browser_connections_and_failed_launches_report_truthfully(self):
        for connection in ('BROWSER', 'DISPLAY', 'WAYLAND_DISPLAY'):
            for code in (0, 1):
                with self.subTest(connection=connection, code=code):
                    environment = {'SSH_CONNECTION': 'fixture', 'BROWSER': '', 'DISPLAY': '', 'WAYLAND_DISPLAY': '', connection: 'fixture'}
                    with mock.patch.dict(os.environ, environment), contextlib.redirect_stdout(io.StringIO()) as out:
                        with mock.patch.object(auth.subprocess, 'run', return_value=mock.Mock(returncode=code)) as browser:
                            self.assertEqual(auth.open_key_page(), code == 0)
                    self.assertEqual(browser.call_args.kwargs['timeout'], 3)
                    self.assertIn(auth.KEY_URL, out.getvalue())
                    self.assertEqual('Browser request sent' in out.getvalue(), code == 0)

    def test_plain_ssh_client_has_explicit_fallback_and_can_still_save_key(self):
        environment = {'SSH_CONNECTION': '', 'SSH_TTY': '', 'SSH_CLIENT': 'fixture', 'BROWSER': '', 'DISPLAY': '', 'WAYLAND_DISPLAY': ''}
        with mock.patch.dict(os.environ, environment), mock.patch.object(auth.subprocess, 'run') as browser:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertFalse(auth.open_key_page())
            self.assertIn('no browser connection', out.getvalue())
            self.assertIn(auth.KEY_URL, out.getvalue())
            self.assertEqual(self.login(answer='')[0]['state'], 'saved')
        browser.assert_not_called()

    def test_browser_child_propagates_launch_failure_and_requests_new_tab(self):
        import runpy
        for opened in (True, False):
            with self.subTest(opened=opened), mock.patch.object(auth.sys, 'argv', ['jev_auth', '--open']):
                with mock.patch.object(auth.webbrowser, 'open', return_value=opened) as browser:
                    with self.assertRaises(SystemExit) as result:
                        with warnings.catch_warnings():
                            warnings.filterwarnings('ignore', message=".*harness_cli.jev_auth.*found in sys.modules", category=RuntimeWarning)
                            runpy.run_module('harness_cli.jev_auth', run_name='__main__')
                self.assertEqual(result.exception.code, 0 if opened else 1)
                browser.assert_called_once_with(auth.KEY_URL, new=2)

    def test_insecure_getpass_fallback_is_rejected(self):
        def insecure(*args):
            warnings.warn('Cannot hide input', auth.getpass.GetPassWarning)
            self.fail('Visible input must never be read')
        with mock.patch.object(auth.sys.stdin, 'isatty', return_value=True), contextlib.redirect_stdout(io.StringIO()) as out:
            with mock.patch.object(auth.sys.stdout, 'isatty', return_value=True), mock.patch('builtins.input', return_value='p'):
                with mock.patch.object(auth.getpass, 'getpass', side_effect=insecure):
                    self.assertEqual(auth.login(jev.MODEL)['state'], 'unavailable')
        self.assertNotIn(SECRET, out.getvalue())
        self.assertFalse(self.root.exists())

    def test_probe_deadline_and_transport_never_use_secret_in_arguments(self):
        with mock.patch.object(auth.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='valid\n')) as run:
            self.assertEqual(auth.validate(SECRET, jev.MODEL), 'valid')
        self.assertNotIn(SECRET, repr(run.call_args.args))
        self.assertEqual(json.loads(run.call_args.kwargs['input'])['key'], SECRET)
        self.assertEqual(run.call_args.kwargs['timeout'], 4)
        with mock.patch.object(auth.subprocess, 'run', side_effect=subprocess.TimeoutExpired('probe', 4)):
            self.assertEqual(auth.validate(SECRET, jev.MODEL), 'unverified')

    def test_saved_key_reaches_real_transport_without_environment_export(self):
        auth.save(SECRET)
        stream = mock.MagicMock()
        stream.__enter__.return_value.read.return_value = b'{}'
        with mock.patch.object(jev_client.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = stream
            jev_client.fetch({'state': 'fixture'})
            self.assertEqual(opener.return_value.open.call_args.args[0].get_header('Authorization'), 'Bearer ' + SECRET)
        self.assertEqual(os.environ['TYPESAFE_API_KEY'], '')

    def test_probe_distinguishes_authentication_from_provider_errors(self):
        for code, expected in ((401, 'invalid'), (429, 'unverified'), (529, 'unverified')):
            error = urllib.error.HTTPError(jev_client.ENDPOINT, code, SECRET, {}, None)
            with mock.patch.object(jev_client, 'fetch', side_effect=error):
                self.assertEqual(jev_client.check_key({'key': SECRET, 'model': jev.MODEL}), expected)
        with mock.patch.object(jev_client, 'fetch', return_value={}) as fetch:
            self.assertEqual(jev_client.check_key({'key': SECRET, 'model': jev.MODEL}), 'valid')
            self.assertEqual(fetch.call_args.args[0]['state'], 'Harness credential check.')

    def test_logout_confirmation_and_unrelated_file_preservation(self):
        auth.save(SECRET)
        unrelated = self.root / 'unrelated.txt'
        unrelated.write_text('keep')
        parser = main.build_parser(REPO)
        args = parser.parse_args(['jev', 'logout', '--json'])
        with self.assertRaisesRegex(ValueError, '--yes'):
            auth.run(args, jev.MODEL)
        self.assertEqual(auth.resolve(), SECRET)
        args.yes = True
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(auth.run(args, jev.MODEL), 0)
        self.assertNotIn(SECRET, out.getvalue())
        self.assertIsNone(auth.resolve())
        self.assertEqual(unrelated.read_text(), 'keep')

    def test_init_only_offers_login_for_enabled_missing_key(self):
        args = main.build_parser(REPO).parse_args(['init', '--project', str(self.base)])
        with mock.patch.object(graft, 'automatic', return_value={'state': 'enabled'}), mock.patch.object(auth, 'login', return_value={'state': 'skipped'}) as login:
            for mode, available, expected in [('shadow', False, 1), ('off', False, 0), ('shadow', True, 0)]:
                login.reset_mock()
                with mock.patch.object(jev, 'automatic', return_value={'mode': mode, 'model': jev.MODEL, 'keyAvailable': available}):
                    with contextlib.redirect_stdout(io.StringIO()):
                        project._configure_retrieval(args, REPO, self.base)
                self.assertEqual(login.call_count, expected)

    @unittest.skipUnless(os.name == 'posix', 'Real owner/mode enforcement requires Linux')
    def test_linked_storage_parent_and_remote_browser_bridge(self):
        alias = self.base / 'linked-home'
        alias.symlink_to(self.base, target_is_directory=True)
        opener = self.base / 'browser-bridge'
        marker = self.base / 'opened-url'
        opener.write_text('#!/bin/sh\nprintf "%s" "$1" > "$TEST_BROWSER_MARKER"\n')
        opener.chmod(0o755)
        environment = {'HARNESS_CREDENTIAL_HOME': str(alias / 'credentials'), 'SSH_CONNECTION': 'fixture',
                       'BROWSER': str(opener), 'DISPLAY': '', 'WAYLAND_DISPLAY': '', 'TEST_BROWSER_MARKER': str(marker)}
        with mock.patch.dict(os.environ, environment), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(auth.open_key_page())
            self.assertEqual(marker.read_text(), auth.KEY_URL)
            auth.save(SECRET)
            self.assertEqual(auth.resolve(), SECRET)
            self.assertTrue(auth.forget())
            self.root.symlink_to(self.base, target_is_directory=True)
            with self.assertRaises(ValueError):
                auth.home()

    @unittest.skipUnless(os.name == 'posix', 'Real owner/mode enforcement requires Linux')
    def test_linux_permissions_links_and_hardlinks_are_enforced(self):
        auth.save(SECRET)
        path = self.root / 'typesafe.json'
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        child = subprocess.run([os.sys.executable, '-B', '-c', 'from harness_cli.jev_auth import resolve; print(bool(resolve()))'],
                               cwd=REPO, capture_output=True, text=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), 'True')
        for target, mode, restore in ((path, 0o644, 0o600), (self.root, 0o755, 0o700)):
            target.chmod(mode)
            self.assertIsNone(auth.resolve())
            with self.assertRaises(ValueError):
                auth.save('replacement')
            target.chmod(restore)
        os.link(path, self.base / 'alias')
        self.assertIsNone(auth.resolve())
        (self.base / 'alias').unlink()
        path.rename(self.base / 'original')
        path.symlink_to(self.base / 'original')
        self.assertIsNone(auth.resolve())
        with self.assertRaises(ValueError):
            auth.forget()
        self.assertEqual(json.loads((self.base / 'original').read_text())['apiKey'], SECRET)


if __name__ == '__main__':
    unittest.main()
