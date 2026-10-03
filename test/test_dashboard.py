"""Offline prerequisite reporting and project-specific command guidance."""
import copy
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_harness_tools import harness_apply, minimal_plan
from harness_cli import dashboard, maintenance, presentation, project
import harness_maintenance

REPO = Path(__file__).resolve().parents[1]


class DashboardTests(unittest.TestCase):
    def setUp(self):
        token = presentation.JSON_MODE.set(False)
        self.addCleanup(presentation.JSON_MODE.reset, token)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "project with spaces ' $HOME `name`"
        self.root.mkdir()
        self.home = self.base / 'codex'
        self.home.mkdir()
        self.environment = mock.patch.dict(os.environ, {'CODEX_HOME': str(self.home)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def hooks(self, *, trust=True):
        command = 'fixture-maintenance-handler'
        definitions = {'hooks': {event: [{'hooks': [maintenance.hook_definition(event, command)]}]
                                 for event in maintenance.EVENTS}}
        saved = {'owner': 'harness-maintenance-v1', 'command': command}
        config = ''
        if trust:
            saved['trust'] = {}
            for index in range(len(maintenance.EVENTS)):
                key = 'owned-' + str(index)
                expected = {'enabled': True, 'trusted_hash': 'fixture-' + str(index)}
                fragment = '[hooks.state."' + key + '"]\nenabled = true\ntrusted_hash = "fixture-' + str(index) + '"\n'
                config += fragment
                saved['trust'][key] = {'before': None, 'after': fragment, 'expected': expected}
        (self.home / 'hooks.json').write_text(json.dumps(definitions))
        (self.home / 'harness-maintenance-hooks.json').write_text(json.dumps(saved))
        (self.home / 'config.toml').write_text(config)
        return definitions, saved

    def test_hook_status_distinguishes_registration_and_unconfirmed_native_trust(self):
        absent = dashboard.hooks_status()
        self.assertEqual(absent['state'], 'not-installed')
        self.assertEqual(absent['definitions'], 0)
        self.hooks(trust=False)
        report = dashboard.hooks_status()
        self.assertEqual(report['state'], 'registered')
        self.assertEqual(report['trust'], 'unconfirmed')
        self.assertEqual(report['definitions'], len(maintenance.EVENTS))
        self.hooks()
        report = dashboard.hooks_status()
        self.assertEqual(report['trust'], 'recorded-matches')
        self.assertEqual(report['recordedTrustMatches'], len(maintenance.EVENTS))
        self.assertEqual(report['nativeTrust'], 'not-tested')
        self.assertEqual(report['runtime'], 'not-tested')

    def test_hook_status_reports_missing_modified_duplicate_and_disabled_definitions(self):
        definitions, saved = self.hooks()
        missing, modified, duplicate = maintenance.EVENTS[:3]
        del definitions['hooks'][missing]
        definitions['hooks'][modified][0]['matcher'] = 'not-all-events'
        definitions['hooks'][duplicate].append(copy.deepcopy(definitions['hooks'][duplicate][0]))
        (self.home / 'hooks.json').write_text(json.dumps(definitions))
        with (self.home / 'config.toml').open('a') as stream:
            stream.write('\n[features]\nhooks = false\n')
        report = dashboard.hooks_status()
        self.assertEqual(report['state'], 'incomplete')
        self.assertIn(missing, report['missingDefinitions'])
        self.assertIn(modified, report['modifiedDefinitions'])
        self.assertIn(duplicate, report['duplicateDefinitions'])
        self.assertEqual(report['localPolicy'], 'user-hooks-disabled')
        saved['trust']['owned-0']['after'] = None
        (self.home / 'harness-maintenance-hooks.json').write_text(json.dumps(saved))
        self.assertEqual(dashboard.hooks_status()['trust'], 'unconfirmed')

    def test_malformed_hook_groups_are_unavailable_instead_of_registered(self):
        definitions, _ = self.hooks()
        definitions['hooks'][maintenance.EVENTS[0]] = {'invalid': True}
        (self.home / 'hooks.json').write_text(json.dumps(definitions))
        with self.assertRaisesRegex(ValueError, 'groups'):
            dashboard.hooks_status()

    def test_maintenance_setting_stays_separate_from_observed_pause_and_native_execution(self):
        self.hooks()
        hooks = dashboard.hooks_status()
        manager = {'mode': 'auto', 'pending': 1}
        result = dashboard.maintenance_availability(manager, hooks)
        self.assertEqual(result['state'], 'static-prerequisites-met')
        self.assertEqual(result['runtime'], 'not-tested')
        for field, detail in (('trackingIncomplete', 'tracking'), ('applicationMarkerPresent', 'marker'),
                              ('historyCapacityBlocked', 'history')):
            with self.subTest(field=field):
                result = dashboard.maintenance_availability({**manager, field: True}, hooks)
                self.assertEqual(result['state'], 'paused')
                self.assertIn(detail, ' '.join(result['reasons']))
        blocked = {**manager, 'scheduling': {'budgetBlocked': True, 'unmeasuredReviewsLastDay': 1}}
        result = dashboard.maintenance_availability(blocked, hooks)
        self.assertIn('unmeasured reviews', ' '.join(result['reasons']))
        self.assertEqual(dashboard.maintenance_availability({**blocked, 'mode': 'off'}, hooks)['state'], 'off')
        self.assertEqual(manager['mode'], 'auto')

    def test_partial_context_does_not_hide_other_eligible_candidates(self):
        self.hooks()
        manager = {'mode': 'suggest', 'pending': 2, 'contextRequired': 1, 'reviewExpired': True}
        result = dashboard.maintenance_availability(manager, dashboard.hooks_status())
        self.assertEqual(result['state'], 'static-prerequisites-met')
        self.assertIn('context', ' '.join(result['notes']))
        result = dashboard.maintenance_availability({**manager, 'contextRequired': 2}, dashboard.hooks_status())
        self.assertEqual(result['state'], 'waiting')
        result = dashboard.maintenance_availability({**manager, 'blockingSessions': [{'ref': 'opaque'}]}, dashboard.hooks_status())
        self.assertEqual(result['state'], 'waiting')

    def test_display_separates_adaptive_evidence_from_current_auto_selection(self):
        rows = []
        report = {'state': 'configured', 'features': {'maintenance': {'mode': 'off', 'pending': 0},
                  'routing': {'enabled': True}, 'hooks': {'state': 'not-installed'},
                  'jev': {'mode': 'shadow', 'keyAvailable': True, 'key': 'never-print-private-key'}}}
        with mock.patch.object(presentation, 'box', side_effect=lambda value, **kwargs: rows.extend(value)):
            dashboard.display(report, self.root, 'test')
        text = '\n'.join(rows)
        self.assertIn('Adaptive evidence setting: on', text)
        self.assertIn('Session model / Auto selection: not observed', text)
        self.assertIn('Maintenance availability: off', text)
        self.assertIn('Runtime loading: not-tested', text)
        self.assertIn('Task quality: not-measured', text)
        self.assertNotIn('inspect /hooks', text)
        self.assertNotIn('Maintenance details:', text)
        self.assertNotIn('never-print-private-key', text)

    @unittest.skipIf(os.name == 'nt', 'POSIX command parsing; PowerShell quoting is tested separately')
    def test_next_commands_name_selected_project_from_another_directory(self):
        installer = project.load_installer(REPO)
        absent = project.project_status(REPO, self.root, installer)
        self.assertEqual(shlex.split(absent['nextCommand']), ['harness-codex', 'init', '--project', str(self.root)])
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))
        before = Path.cwd()
        try:
            os.chdir(self.base)
            configured = project.project_status(REPO, self.root, installer)
        finally:
            os.chdir(before)
        self.assertEqual(shlex.split(configured['nextCommand']), ['codex', '--cd', str(self.root)])
        (self.root / '.harness/transaction.json').write_text(json.dumps({'operation': 'remove'}))
        pending = project.project_status(REPO, self.root, installer)
        self.assertEqual(shlex.split(pending['nextCommand']), ['harness-codex', 'remove', '--project', str(self.root), '--recover'])

    @unittest.skipIf(os.name == 'nt', 'POSIX shell execution')
    def test_posix_command_keeps_shell_metacharacters_literal(self):
        value = str(self.root / '$(touch unwanted); & "end"')
        command = presentation.command([sys.executable, '-B', '-c', 'import json,sys;print(json.dumps(sys.argv[1:]))', value])
        result = subprocess.run(command, shell=True, cwd=self.base, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [value])
        self.assertFalse((self.base / 'unwanted').exists())

    def test_windows_commands_use_powershell_literal_arguments(self):
        self.assertEqual(presentation.command(['codex', '--cd', "C:\\a b\\O'Brien $HOME `x`"], windows=True),
                         "& 'codex' '--cd' 'C:\\a b\\O''Brien $HOME `x`'")


class MaintenanceStatusScheduleTests(unittest.TestCase):
    def test_status_and_claim_share_review_limit_and_interval_without_status_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / 'project'
            root.mkdir()
            harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))
            now = [100000.0]
            manager = harness_maintenance.Maintenance(root, base / 'state', clock=lambda: now[0])
            manager.configure('auto', policy={'reviewsPerDay': 1})
            manager.signal('scope-changed', 'pyproject.toml', 'first')
            lease = manager.begin(evidence='pyproject.toml')
            self.assertEqual(lease['status'], 'claimed')
            manager.finish(lease['id'], 'deferred', tokens=10)
            now[0] += 1
            before = manager._location().read_bytes()
            schedule = manager.status()['scheduling']
            self.assertEqual(manager._location().read_bytes(), before)
            self.assertEqual(schedule['reviewsLastDay'], 1)
            self.assertTrue(schedule['reviewLimitReached'])
            self.assertGreater(schedule['intervalRemainingSeconds'], 0)
            self.assertEqual(manager.begin(evidence='pyproject.toml')['status'], 'deferred')
            now[0] += 86400
            schedule = manager.status()['scheduling']
            self.assertEqual(schedule['reviewsLastDay'], 0)
            self.assertFalse(schedule['reviewLimitReached'])
            self.assertEqual(schedule['intervalRemainingSeconds'], 0)
            manager.configure(policy={'reportedTokensPerDay': 4000})
            lease = manager.begin(evidence='pyproject.toml')
            self.assertEqual(lease['status'], 'claimed')
            now[0] = lease['deadline'] + 1
            before = manager._location().read_bytes()
            expired = manager.status()
            self.assertTrue(expired['reviewExpired'])
            self.assertTrue(expired['scheduling']['budgetBlocked'])
            self.assertEqual(expired['scheduling']['unmeasuredReviewsLastDay'], 1)
            self.assertEqual(manager._location().read_bytes(), before)
            self.assertEqual(manager.begin(evidence='pyproject.toml')['status'], 'deferred')
