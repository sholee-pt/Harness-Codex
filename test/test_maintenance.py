"""Behavioral checks for no-op cost, bounded updates and ownership protection."""
import copy
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.agents/skills/harness/scripts'))
import harness_apply
import harness_maintenance as maintenance
from test_harness_tools import minimal_plan
from harness_cli import versions
from harness_cli.maintenance import install_hooks


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'selected project'
        self.root.mkdir()
        self.plan = minimal_plan(self.root)
        harness_apply.apply_application(harness_apply.build_application(self.root, self.plan))
        self.now = 100000.0
        self.state = self.base / 'private state'
        self.manager = maintenance.Maintenance(self.root, self.state, clock=lambda: self.now)

    def snapshot(self):
        return {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def signal(self, reason='scope-changed', observation='turn-a'):
        return self.manager.signal(reason, 'pyproject.toml', observation)

    def hook(self, kind='UserPromptSubmit', session='session-a', **extra):
        return self.manager.hook({'hook_event_name': kind, 'session_id': session,
                                  'prompt': 'Never store this raw prompt', **extra})

    def lease(self):
        return self.manager._read(self.manager._location())['lease']

    def updated_plan(self, suffix='\nVerify the fixture schema before evaluation.\n'):
        plan = minimal_plan(self.root, skill_suffix=suffix)
        path = self.base / 'candidate.json'
        path.write_text(json.dumps(plan), encoding='utf-8')
        return path

    def test_disabled_turns_and_status_write_nothing_and_do_not_read_manifest(self):
        before = self.snapshot()
        with mock.patch.object(self.manager, 'manifest', side_effect=AssertionError('Unexpected scan')):
            self.assertEqual(self.manager.status()['mode'], 'off')
            for _ in range(20):
                self.assertEqual(self.hook(), '')
        self.assertFalse(self.state.exists())
        self.assertEqual(before, self.snapshot())

    def test_scope_growth_does_not_change_any_project_file_or_launch_model(self):
        self.manager.configure('auto')
        before = self.snapshot()
        with mock.patch('subprocess.Popen', side_effect=AssertionError('Unexpected model/process')):
            self.signal()
            self.assertIn('review', self.hook())
        self.assertEqual(before, self.snapshot())

    def test_suggest_notices_once_without_review(self):
        self.manager.configure('suggest')
        self.signal()
        self.assertIn('candidates', self.hook())
        self.hook('Stop')
        self.assertEqual(self.hook(), '')
        self.assertIsNone(self.lease())
        self.assertEqual(self.manager.status()['metrics']['reviews'], 0)

    def test_clear_disables_and_forgets_only_selected_project_records(self):
        self.manager.configure('auto')
        self.signal(); self.hook()
        before = self.snapshot()
        result = self.manager.clear()
        self.assertEqual(result['mode'], 'off')
        self.assertEqual(result['metrics']['reviews'], 0)
        self.assertEqual(self.manager._read(self.manager._location()), maintenance.default_state())
        self.assertEqual(before, self.snapshot())

    def test_real_cli_signal_native_hook_and_finish_share_local_state(self):
        environment = {**os.environ, 'HARNESS_STATE_HOME': str(self.state),
                       'CODEX_HOME': str(self.base / 'codex home'), 'HARNESS_NO_UPDATE_CHECK': '1'}
        environment.pop('HARNESS_TOOL_HOME', None)
        command = [sys.executable, '-B', str(ROOT / 'harness.py'), '--no-update-check',
                   'maintenance', '--project', str(self.root)]
        def run(*arguments, event=None):
            result = subprocess.run([*command, *arguments], env=environment,
                                    input=json.dumps(event) if event else None,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout) if result.stdout.strip() else None
        self.assertEqual(run('--json')['mode'], 'off')
        self.assertFalse(self.state.exists())
        self.assertEqual(run('--json', '--mode', 'auto')['mode'], 'auto')
        self.assertTrue(run('--json', 'signal', '--reason', 'scope-changed', '--evidence',
                            'pyproject.toml', '--observation', 'turn-1')['recorded'])
        notice = run('--hook', event={'cwd': str(self.root), 'session_id': 'live-fixture',
                                      'hook_event_name': 'UserPromptSubmit'})
        self.assertIn('review lease', notice['hookSpecificOutput']['additionalContext'].lower())
        lease = maintenance.Maintenance(self.root, self.state)._read(self.manager._location())['lease']
        self.assertEqual(run('--json', 'finish', '--lease', lease['id'], '--decision', 'unchanged')['status'], 'unchanged')
        self.assertEqual(run('--json', 'clear', '--yes')['mode'], 'off')

    def test_repeated_observation_is_not_independent_evidence(self):
        self.manager.configure('auto')
        for _ in range(5):
            self.signal('workflow-gap')
        self.assertEqual(self.manager.status()['pending'], 0)
        self.signal('workflow-gap', 'turn-b')
        self.assertEqual(self.manager.status()['pending'], 1)

    def test_no_change_is_suppressed_until_evidence_changes(self):
        self.manager.configure('auto')
        self.signal()
        self.hook()
        self.manager.finish(self.lease()['id'], 'unchanged')
        self.assertFalse(self.signal(observation='turn-new')['recorded'])
        self.hook('Stop')
        self.assertEqual(self.hook(), '')
        with (self.root / 'pyproject.toml').open('a') as stream:
            stream.write('# new responsibility\n')
        self.assertTrue(self.signal()['recorded'])

    def test_existing_skill_applies_and_same_session_gets_reload_once(self):
        self.manager.configure('auto')
        before = self.manager.manifest()['topology']
        self.signal()
        self.hook()
        result = self.manager.finish(self.lease()['id'], 'apply', plan=self.updated_plan())
        self.assertEqual(result['status'], 'apply')
        self.assertEqual(before, self.manager.manifest()['topology'])
        self.hook('Stop')
        self.assertIn('Re-read', self.hook())
        self.hook('Stop')
        self.assertEqual(self.hook(), '')

    def test_apply_rejects_user_edits_without_overwrite(self):
        self.manager.configure('auto')
        self.signal(); self.hook()
        path = self.root / '.agents/skills/project-harness/SKILL.md'
        path.write_text(path.read_text() + '\nUser content\n')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.manager.finish(self.lease()['id'], 'apply', plan=self.updated_plan())
        self.assertEqual(before, self.snapshot())

    def test_apply_rejects_topology_change_and_large_content(self):
        for change in ('topology', 'large'):
            with self.subTest(change=change):
                self.manager.configure('auto')
                self.signal(); self.hook()
                path = self.updated_plan('x' * 9000 if change == 'large' else '\nNew instruction\n')
                if change == 'topology':
                    plan = json.loads(path.read_text())
                    plan['topology']['classification']['rationale'] += ' New role design.'
                    path.write_text(json.dumps(plan))
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.manager.finish(self.lease()['id'], 'apply', plan=path)
                self.assertEqual(before, self.snapshot())
                self.now += 3700

    def test_conflicting_revision_timeout_and_suggest_mode_refuse_apply(self):
        self.manager.configure('suggest')
        self.signal()
        lease = self.manager.begin()['id']
        with self.assertRaisesRegex(ValueError, 'not enabled'):
            self.manager.finish(lease, 'apply', plan=self.updated_plan())
        self.manager.finish(lease, 'proposed')
        self.now += 3700
        self.manager.configure('auto')
        (self.root / 'evidence.txt').write_text('new')
        self.manager.signal('user-request', 'evidence.txt', 'b')
        lease = self.manager.begin()['id']
        self.now += 181
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'deadline'):
            self.manager.finish(lease, 'apply', plan=self.updated_plan())
        self.assertEqual(before, self.snapshot())

    def test_other_sessions_and_children_defer_review(self):
        self.manager.configure('auto')
        self.hook(session='other')
        self.signal()
        self.assertEqual(self.hook(), '')
        self.assertIsNone(self.lease())
        self.hook('Stop', session='other')
        self.hook('SubagentStart', agent_id='child')
        self.assertEqual(self.hook(), '')
        self.hook('SubagentStop', agent_id='child')
        self.assertIn('review', self.hook())

    def test_private_state_has_no_raw_project_session_or_prompt(self):
        self.manager.configure('auto')
        self.signal(); self.hook()
        data = self.manager._location().read_text()
        for raw in (str(self.root), 'selected project', 'pyproject.toml', 'session-a', 'turn-a', 'Never store'):
            self.assertNotIn(raw, data)

    def test_ignored_review_expires_without_repeating_the_same_work(self):
        self.manager.configure('auto')
        self.signal(); self.hook()
        self.assertIsNotNone(self.lease())
        self.now += 200
        self.hook('Stop')
        self.assertIsNone(self.lease())
        self.assertEqual(self.hook(), '')
        self.assertEqual(self.manager.status()['metrics']['unmeasuredReviews'], 1)

    def test_replaced_manifest_refuses_apply_and_keeps_newer_harness(self):
        self.manager.configure('auto')
        self.signal(); self.hook()
        newer = minimal_plan(self.root, skill_suffix='\nA concurrent verified update.\n')
        harness_apply.apply_application(harness_apply.build_application(self.root, newer))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'changed during review'):
            self.manager.finish(self.lease()['id'], 'apply', plan=self.updated_plan())
        self.assertEqual(before, self.snapshot())

    def test_hook_merge_preserves_unrelated_handlers_and_is_idempotent(self):
        home = self.base / 'codex home'; home.mkdir()
        original = {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'user-owned-tool'}]}]}, 'custom': 'keep'}
        path = home / 'hooks.json'; path.write_text(json.dumps(original))
        install_hooks(ROOT, codex_home=home)
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.assertFalse(install_hooks(ROOT, codex_home=home)['changed'])
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        value = json.loads(path.read_text())
        self.assertEqual(value['hooks']['Stop'][0], original['hooks']['Stop'][0])
        self.assertEqual(value['custom'], 'keep')


class BetaVersionTests(unittest.TestCase):
    def test_legacy_mapping_prerelease_order_and_feature_increment(self):
        self.assertEqual(versions.version_key('9.11'), versions.version_key('0.9.11-beta'))
        self.assertEqual(versions.display_version('8.7'), '0.8.7-beta')
        ordered = ['9.11', '0.10.0-beta', '0.10.0', '0.10.1-beta', '0.11.0-beta', '1.0.0-beta', '1.0.0']
        self.assertEqual(ordered, sorted(reversed(ordered), key=versions.version_key))
        self.assertEqual(versions.branch_version('codex/v0.10.0-beta'), '0.10.0-beta')
        for value in ('0.01.0-beta', '0.10.0-rc', '0.10.0-beta/evil', '0.10.0-beta\n'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                versions.version_key(value)


if __name__ == '__main__':
    unittest.main()
