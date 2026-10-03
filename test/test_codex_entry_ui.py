"""Prelaunch progress and native alternatives without network or Codex processes."""
import io
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest import mock

from harness_cli import auto_relay, codex_entry as entry, codex_integration, main, presentation, workspace_context


class EntryUiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project $cash's work"
        self.project.mkdir()
        self.output = io.StringIO()
        self.enterContext(mock.patch.object(sys, 'stderr', self.output))
        self.enterContext(mock.patch.object(sys.stdin, 'isatty', return_value=True))
        self.enterContext(mock.patch.object(sys.stdout, 'isatty', return_value=True))
        self.enterContext(mock.patch.dict(os.environ, {'TERM': 'dumb', 'HARNESS_NO_UPDATE_CHECK': '0', 'HARNESS_CODEX_NATIVE': '0'}))

    def test_release_progress_precedes_both_probes_and_failure_is_not_success(self):
        def codex(*args, **kwargs):
            self.assertIn('Checking Codex and Harness updates', self.output.getvalue())
            self.assertEqual(kwargs['timeout'], 5)
            raise TimeoutError('fixture unavailable')
        def harness(*args, **kwargs):
            self.assertIn('Checking Codex and Harness updates', self.output.getvalue())
            return {'updateAvailable': False}
        with mock.patch.object(entry.dist, 'installed_status', return_value={'auto_update': 'compatible', 'branch': None}), \
             mock.patch.object(entry.official_codex, 'check', side_effect=codex), \
             mock.patch.object(entry.release_updates, 'check', side_effect=harness), \
             mock.patch.object(entry.official_codex, 'install') as install:
            self.assertFalse(entry.update_choices(self.root))
        self.assertIn('continuing with installed files', self.output.getvalue())
        self.assertIn('partly unavailable', self.output.getvalue())
        self.assertNotIn(': finished', self.output.getvalue())
        install.assert_not_called()

    def test_disabled_update_channels_stay_quiet_and_offline(self):
        for policy, environment in (('off', '0'), ('compatible', '1')):
            with self.subTest(policy=policy, environment=environment), \
                 mock.patch.object(entry.dist, 'installed_status', return_value={'auto_update': policy}), \
                 mock.patch.dict(os.environ, {'HARNESS_NO_UPDATE_CHECK': environment}), \
                 mock.patch.object(entry.official_codex, 'check') as codex, \
                 mock.patch.object(entry.release_updates, 'check') as harness:
                self.assertFalse(entry.update_choices(self.root))
                codex.assert_not_called()
                harness.assert_not_called()
        self.assertEqual(self.output.getvalue(), '')

    def launch(self, args, *, native=False, failure=None):
        with mock.patch.object(main, 'default_data_root', return_value=self.root), \
             mock.patch.object(codex_integration, 'read', return_value={'schema': 2}), \
             mock.patch.object(entry, 'update_choices', return_value=False) as updates, \
             mock.patch.object(entry.official_codex, 'binary', return_value=self.root / 'codex'), \
             mock.patch.object(entry.official_codex, 'read', return_value={'mode': 'native'} if native else {}), \
             mock.patch.object(workspace_context, 'PATH', 'fixture-no-context.json'), \
             mock.patch.object(entry, 'compatible', side_effect=failure) as compatible, \
             mock.patch.object(entry, 'choose', return_value=0), \
             mock.patch.object(auto_relay, 'run') as relay, \
             mock.patch.object(entry.os, 'execve', side_effect=RuntimeError('native executed')) as execute:
            with self.assertRaisesRegex(RuntimeError, 'native executed'):
                entry.main(args)
            relay.assert_not_called()
        return updates, compatible, execute

    def test_all_interactive_native_routes_show_selected_project_commands(self):
        base = ['--cd', str(self.project), '--sandbox', 'read-only', '--ask-for-approval', 'on-request']
        for kind in ('saved-native', 'profile', 'environment', 'unsupported'):
            with self.subTest(kind=kind):
                self.output.seek(0)
                self.output.truncate()
                args = base + (['--profile', 'work'] if kind == 'profile' else [])
                with mock.patch.dict(os.environ, {'HARNESS_CODEX_NATIVE': '1' if kind == 'environment' else '0'}):
                    _, compatible, execute = self.launch(args, native=kind == 'saved-native',
                        failure=ValueError('fixture unsupported capability') if kind == 'unsupported' else None)
                output = self.output.getvalue()
                self.assertIn('Harness Auto and /harness/ management are unavailable', output)
                for action in ('status', 'init', 'config'):
                    expected = presentation.command(['harness-codex', action, '--project', str(self.project)])
                    self.assertIn(expected, output)
                    if os.name == 'posix':
                        self.assertEqual(shlex.split(expected), ['harness-codex', action, '--project', str(self.project)])
                expected_args = ['-c', 'check_for_update_on_startup=false', *args] if kind == 'unsupported' else args
                self.assertEqual(execute.call_args.args[1], [str(self.root / 'codex'), *expected_args])
                if kind != 'unsupported':
                    compatible.assert_not_called()

    def test_compatibility_progress_starts_before_probe_and_stops_before_native_choice(self):
        observed = []
        def probe(binary, args, *, progress):
            self.assertIn('Checking Auto compatibility', self.output.getvalue())
            self.assertFalse(progress.stop.is_set())
            observed.append(progress)
            raise ValueError('fixture unsupported capability')
        self.launch(['--cd', str(self.project)], failure=probe)
        self.assertEqual(len(observed), 1)
        self.assertTrue(observed[0].stop.is_set())
        output = self.output.getvalue()
        self.assertLess(output.index('Checking Auto compatibility: stopped'), output.index('Auto compatibility check failed'))

    def test_help_and_automation_do_not_add_guidance_or_checks(self):
        for args in (['--help'], ['exec', 'fixture task'], ['login'], ['resume', '--remote', 'ws://fixture']):
            with self.subTest(args=args), mock.patch.dict(os.environ, {'HARNESS_CODEX_NATIVE': '1'}):
                updates, compatible, execute = self.launch(args)
                updates.assert_not_called()
                compatible.assert_not_called()
                self.assertEqual(execute.call_args.args[1], [str(self.root / 'codex'), *args])
        self.assertEqual(self.output.getvalue(), '')

    def test_native_install_offer_has_management_alternatives_without_applying_a_choice(self):
        with mock.patch.object(entry, 'choose', return_value=0):
            self.assertFalse(entry.choose_native_install('0.159.0', ValueError('fixture unsupported'), project=self.project))
        self.assertIn('/harness/ management are unavailable', self.output.getvalue())
        self.assertIn(presentation.command(['harness-codex', 'init', '--project', str(self.project)]), self.output.getvalue())


if __name__ == '__main__':
    unittest.main()
