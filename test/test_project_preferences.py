"""Init choices preserve opt-outs, cancellation, local state and unattended use."""
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from harness_cli import main, presentation, project_preferences as preferences
from test_harness_tools import harness_apply, minimal_plan

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.agents/skills/harness/scripts'))
import harness_maintenance
import harness_routing_evidence


class Terminal(io.StringIO):
    def isatty(self):
        return True


class ProjectPreferencesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root, self.store = self.base / 'project', self.base / 'state'
        self.root.mkdir()
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))
        self.maintenance = harness_maintenance.Maintenance(self.root, self.store)
        self.routing = harness_routing_evidence.RoutingEvidence(self.root, self.store)
        environment = mock.patch.dict(os.environ, {'HARNESS_STATE_HOME': str(self.store), 'CODEX_HOME': str(self.base / 'codex')})
        environment.start()
        self.addCleanup(environment.stop)
        helper = mock.patch.object(preferences.maintenance, 'helper', side_effect=lambda *args: self.maintenance.status())
        helper.start()
        self.addCleanup(helper.stop)
        enable = mock.patch.object(preferences.maintenance, 'enable', side_effect=lambda source, root, mode, **kwargs: self.maintenance.configure(mode))
        self.enable = enable.start()
        self.addCleanup(enable.stop)
        trust = mock.patch.object(preferences.hook_trust, 'prepare', return_value={'status': 'trusted', 'count': 7, 'changed': False})
        self.trust = trust.start()
        self.addCleanup(trust.stop)

    def run_choices(self, selections=(), *, tty=True, **settings):
        args = SimpleNamespace(**{'command': 'init', 'maintenance': None, 'adaptive': None, 'json': False, **settings})
        output = Terminal() if tty else io.StringIO()
        token = presentation.JSON_MODE.set(args.json)
        try:
            with mock.patch.object(sys, 'stdin', Terminal() if tty else io.StringIO()), contextlib.redirect_stdout(output), \
                    contextlib.redirect_stderr(output), mock.patch.object(preferences, 'choose', side_effect=selections) as select:
                preferences.configure(args, ROOT, self.root)
                return output.getvalue(), select.call_count
        finally:
            presentation.JSON_MODE.reset(token)

    def snapshot(self):
        return {str(path.relative_to(self.store)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.store.rglob('*') if path.is_file()}

    def test_both_modes_can_be_selected_and_changed_later_without_model_calls(self):
        output, count = self.run_choices([2, 1])
        self.assertEqual(count, 2)
        self.assertEqual(self.maintenance.status()['mode'], 'auto')
        self.assertTrue(self.routing.status()['enabled'])
        for text in ('--mode suggest', '--adaptive on', '--adaptive status', 'hook trust: ready', '/model', 'quality feedback'):
            self.assertIn(text, output)
        self.assertIn('reviews use conversation tokens', output)
        self.assertIn('no extra model call', output)
        for command in ('init', 'config', 'reset'):
            args = main.build_parser(ROOT).parse_args([command, '--maintenance', 'off', '--adaptive', 'off'])
            self.assertEqual((args.maintenance, args.adaptive), ('off', 'off'))

    def test_keeping_current_modes_preserves_lease_policy_and_observations_without_writes(self):
        self.maintenance.configure('auto', {'schedule': 'fixed'})
        self.maintenance.signal('scope-changed', 'pyproject.toml', 'known-change')
        lease = self.maintenance.begin()
        self.routing.configure(True, {'confidence': 0.9})
        before = self.snapshot()
        self.run_choices([0, 0])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.maintenance.status()['policy']['schedule'], 'fixed')
        self.assertTrue(self.maintenance.status()['reviewInProgress'])
        self.assertEqual(lease['status'], 'claimed')
        self.enable.assert_not_called()

    def test_cancel_second_menu_never_applies_first_choice(self):
        before = self.snapshot()
        with self.assertRaises(KeyboardInterrupt):
            self.run_choices([2, KeyboardInterrupt()])
        self.assertEqual(self.snapshot(), before)
        self.enable.assert_not_called()
        self.assertFalse(self.routing.status()['enabled'])
        self.trust.assert_not_called()

    def test_back_navigation_keeps_selection_and_can_restore_original_without_writes(self):
        before = self.snapshot()
        calls = []
        selections = iter([2, -1, 0, 0])
        def choose(*args, **kwargs):
            calls.append(kwargs)
            self.assertEqual(self.snapshot(), before)
            return next(selections)
        self.run_choices(choose)
        self.assertEqual([call.get('initial') for call in calls], [0, 0, 2, 0])
        self.assertTrue(calls[1]['back'])
        self.assertEqual(calls[1]['summary'], ['Maintenance: auto'])
        self.assertEqual(calls[3]['summary'], ['Maintenance: off'])
        self.assertEqual(self.snapshot(), before)
        self.enable.assert_not_called()

    def test_init_prepares_trust_even_when_both_modes_are_off_and_manual_is_explicit(self):
        output, _ = self.run_choices([0, 0])
        self.trust.assert_called_once_with(ROOT, self.root, binary='codex', mode='auto')
        self.assertEqual(self.snapshot(), {})
        self.assertNotIn('/hooks', output)
        self.assertIn('off remains off', output)
        self.trust.reset_mock()
        for command in ('configure', 'reset'):
            self.run_choices(command=command, tty=False)
        self.trust.assert_not_called()
        self.run_choices(tty=False, hook_trust='manual')
        self.assertEqual(self.trust.call_args.kwargs['mode'], 'manual')
        args = main.build_parser(ROOT).parse_args(['init', '--hook-trust', 'manual'])
        self.assertEqual(args.hook_trust, 'manual')

    def test_unattended_json_config_and_previews_never_prompt_or_enable(self):
        for settings in ({'tty': False}, {'json': True}, {'command': 'configure'}, {'dry_run': True}, {'install_only': True}):
            with self.subTest(settings=settings):
                self.trust.reset_mock()
                _, count = self.run_choices(**settings)
                self.assertEqual(count, 0)
                self.assertEqual(self.snapshot(), {})
                self.assertEqual(self.trust.called, settings in ({'tty': False}, {'json': True}))
        output, count = self.run_choices(tty=False, maintenance='suggest', adaptive='on')
        self.assertEqual(count, 0)
        self.assertEqual(self.maintenance.status()['mode'], 'suggest')
        self.assertTrue(self.routing.status()['enabled'])
        self.run_choices(tty=False, maintenance='off', adaptive='off')
        self.assertEqual(self.maintenance.status()['mode'], 'off')
        self.assertFalse(self.routing.status()['enabled'])

    def test_explicit_setting_only_skips_its_own_menu(self):
        _, count = self.run_choices([1], maintenance='suggest')
        self.assertEqual(count, 1)
        self.assertEqual(self.maintenance.status()['mode'], 'suggest')
        self.assertTrue(self.routing.status()['enabled'])
        before = self.snapshot()
        self.run_choices(maintenance='suggest', adaptive='on')
        self.assertEqual(self.snapshot(), before)

    def test_corrupt_state_is_preserved_and_explicit_requests_fail_clearly(self):
        self.routing.configure(True)
        self.routing.location().write_text('broken', encoding='utf-8')
        before = self.snapshot()
        output, count = self.run_choices()
        self.assertEqual(count, 0)
        self.assertIn('unavailable', output)
        with self.assertRaisesRegex(ValueError, 'existing settings were preserved'):
            self.run_choices(adaptive='off')
        self.assertEqual(self.snapshot(), before)
        self.enable.assert_not_called()
        self.trust.assert_not_called()
