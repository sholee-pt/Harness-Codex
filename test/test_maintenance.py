"""Behavioral checks for no-op cost, bounded updates and ownership protection."""
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.agents/skills/harness/scripts'))
import harness_apply
import harness_eval_lock
import harness_maintenance as maintenance
from test_harness_tools import minimal_plan
from harness_cli import versions
from harness_cli.maintenance import install_hooks


class MaintenanceTests(unittest.TestCase):
    def test_manual_begin_expires_lease_without_hooks_and_status_is_read_only(self):
        self.manager.configure('auto')
        self.signal()
        first = self.manager.begin()
        self.assertEqual(first['status'], 'claimed')
        self.now += 86401
        self.signal('user-request', 'next-day')
        path = self.manager._location()
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.assertTrue(self.manager.status()['reviewExpired'])
        self.assertFalse(self.manager.status()['reviewInProgress'])
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        second = self.manager.begin()
        self.assertEqual(second['status'], 'claimed')
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(self.manager.status()['metrics']['unmeasuredReviews'], 1)
        self.assertEqual(self.manager.begin()['status'], 'deferred')
        self.assertEqual(self.manager.status()['metrics']['unmeasuredReviews'], 1)

    def test_expired_review_does_not_release_active_native_workers(self):
        self.manager.configure('auto')
        self.signal()
        self.manager.begin()
        self.hook(session='other-worker')
        self.now += 86401
        self.signal('user-request', 'next-day')
        self.assertEqual(self.manager.begin()['status'], 'deferred')
        self.assertIsNone(self.lease())
        self.hook('Stop', session='other-worker')
        self.assertEqual(self.manager.begin()['status'], 'claimed')

    def test_hook_install_and_remove_preserve_concurrent_user_edits(self):
        from harness_cli import distribution, hook_state, maintenance as cli_maintenance
        home = self.base / 'codex home'
        home.mkdir()
        path = home / 'hooks.json'
        receipt = home / 'harness-maintenance-hooks.json'
        path.write_text('{"hooks": {}, "custom": "before"}')
        writer = distribution._write_json
        def concurrent_write(target, value, **kwargs):
            if target == path:
                current = json.loads(path.read_text())
                current['custom'] = 'concurrent-user-value'
                path.write_text(json.dumps(current))
            writer(target, value, **kwargs)
        with mock.patch.object(distribution, '_write_json', side_effect=concurrent_write):
            with self.assertRaisesRegex(distribution.DistributionError, 'concurrent edits preserved'):
                install_hooks(ROOT, codex_home=home, tool_home=self.base)
        self.assertEqual(json.loads(path.read_text())['custom'], 'concurrent-user-value')
        self.assertFalse(receipt.exists())
        install_hooks(ROOT, codex_home=home, tool_home=self.base)
        receipt_before = receipt.read_bytes()
        value = json.loads(path.read_text()); value['custom'] = 'before-removal'
        path.write_text(json.dumps(value))
        replace = hook_state.replace_file
        def concurrent_remove(target, before, after):
            if target == path:
                current = json.loads(path.read_text())
                current['custom'] = 'concurrent-user-value'
                path.write_text(json.dumps(current))
            return replace(target, before, after)
        with mock.patch.object(hook_state, 'replace_file', side_effect=concurrent_remove), \
                mock.patch.object(distribution, 'installed_status', return_value={'python': sys.executable}):
            with self.assertRaisesRegex(ValueError, 'user edits preserved'):
                cli_maintenance.remove_hooks(self.base, codex_home=home, dry_run=False)
        self.assertEqual(receipt.read_bytes(), receipt_before)
        self.assertEqual(json.loads(path.read_text())['custom'], 'concurrent-user-value')
        with mock.patch.object(distribution, 'installed_status', return_value={'python': sys.executable}):
            self.assertGreater(cli_maintenance.remove_hooks(self.base, codex_home=home, dry_run=False)['handlers'], 0)
        self.assertFalse(receipt.exists())

    def test_failed_hook_update_restores_existing_receipt_and_allows_retry(self):
        from harness_cli import distribution
        home = self.base / 'codex home'
        install_hooks(ROOT, codex_home=home, tool_home=self.base / 'old-tool')
        before = {p.name: p.read_bytes() for p in home.iterdir()}
        writer = distribution._write_json
        for error in (OSError, KeyboardInterrupt):
            for target in ('hooks.json', 'harness-maintenance-hooks.json'):
                def fail(path, value, **kwargs):
                    if path.name == target:
                        raise error('simulated-hook-write-failure')
                    return writer(path, value, **kwargs)
                with self.subTest(error=error.__name__, target=target), mock.patch.object(distribution, '_write_json', side_effect=fail):
                    with self.assertRaisesRegex(error, 'simulated-hook-write-failure'):
                        install_hooks(ROOT, codex_home=home, tool_home=self.base / 'new-tool')
                self.assertEqual(before, {p.name: p.read_bytes() for p in home.iterdir()})
        self.assertTrue(install_hooks(ROOT, codex_home=home, tool_home=self.base / 'new-tool')['changed'])

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

    def test_unknown_terminal_events_do_not_consume_session_capacity(self):
        self.manager.configure('suggest')
        for index in range(maintenance.MAX_SESSIONS):
            self.hook('SessionStart', 'known-' + str(index))
        before = self.manager._read(self.manager._location())['sessions']
        for kind in ('Stop', 'Interrupt', 'SubagentStop', 'SessionEnd'):
            self.assertEqual(self.hook(kind, 'unknown-' + kind), '')
        self.assertEqual(self.manager._read(self.manager._location())['sessions'], before)
        self.assertIn('session limit', self.hook('UserPromptSubmit', 'another'))

    def test_tracking_overflow_stays_paused_until_confirmed_global_recovery(self):
        for overflow in ('sessions', 'children'):
            self.manager.clear()
            self.manager.configure('auto')
            self.signal(observation='overflow-' + overflow)
            if overflow == 'sessions':
                for index in range(maintenance.MAX_SESSIONS):
                    self.hook('SessionStart', str(index))
                self.hook('SessionStart', 'untracked')
                for index in range(maintenance.MAX_SESSIONS):
                    self.hook('SessionEnd', str(index))
            else:
                for index in range(65):
                    self.hook('SubagentStart', agent_id=str(index))
                for index in range(64):
                    self.hook('SubagentStop', agent_id=str(index))
            self.assertTrue(self.manager.status()['trackingIncomplete'])
            self.assertTrue(self.manager.status()['automaticChangesPaused'])
            self.assertEqual(self.manager.begin()['status'], 'deferred')
            before = self.snapshot()
            self.manager.recover_session('all')
            self.assertEqual(self.snapshot(), before)
            self.assertFalse(self.manager.status()['trackingIncomplete'])
            self.assertEqual(self.manager.status()['pending'], 1)
            self.assertIn('id', self.manager.begin())

    def test_previous_tracking_state_is_readable_without_rewriting_on_status(self):
        self.manager.configure('suggest')
        path = self.manager._location()
        previous = json.loads(path.read_bytes())
        previous['schema'] = 3
        previous.pop('trackingIncomplete')
        path.write_text(json.dumps(previous))
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.assertFalse(self.manager.status()['trackingIncomplete'])
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.hook('SessionStart')
        self.assertEqual(json.loads(path.read_bytes())['schema'], 4)

    def test_hook_output_is_event_appropriate_and_diagnostics_do_not_echo_input(self):
        import contextlib
        import io
        from types import SimpleNamespace
        for kind in ('SessionStart', 'UserPromptSubmit', 'SubagentStart', 'Stop', 'SubagentStop', 'Interrupt', 'SessionEnd'):
            event = {'hook_event_name': kind, 'cwd': str(self.root), 'session_id': 'fixture'}
            with mock.patch.object(sys, 'argv', ['maintenance', 'hook']), \
                    mock.patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(json.dumps(event).encode()))), \
                    mock.patch.object(maintenance.Maintenance, 'hook', return_value='capacity notice'), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(maintenance.main(), 0)
            result = json.loads(output.getvalue())
            self.assertEqual('hookSpecificOutput' in result, kind in {'SessionStart', 'UserPromptSubmit'})
        with mock.patch.object(sys, 'argv', ['maintenance', 'hook']), \
                mock.patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(b'{"secret":"private"}'))), \
                mock.patch.object(maintenance, 'find_root', side_effect=OSError('secret private path')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(maintenance.main(), 0)
        message = json.loads(output.getvalue())['systemMessage']
        self.assertIn('filesystem', message)
        self.assertNotIn('secret', message)
        self.assertNotIn('private', message)

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

    def applied_change(self):
        self.manager.configure('auto')
        self.signal()
        self.hook()
        result = self.manager.finish(self.lease()['id'], 'apply', plan=self.updated_plan())
        self.hook('Stop')
        return result

    def test_effect_observations_are_deduplicated_stratified_and_pause_only_related_changes(self):
        result = self.applied_change()
        identity, revision = result['changeId'], result['revision']
        def observe(reference, **kwargs):
            context = dict(model='private-model', effort='adaptive', category='testing', runtime='cli-future')
            context.update(kwargs)
            return self.manager.observe(identity, reference, 'failed', 'verification', revision, **context)
        self.assertEqual(observe('one')['status'], 'observing')
        self.assertFalse(observe('one')['recorded'])
        self.assertEqual(observe('different', model='other-model')['status'], 'observing')
        self.assertEqual(observe('unknown', runtime=None)['status'], 'observing')
        self.assertEqual(observe('two')['status'], 'review-required')
        self.assertTrue(self.manager.status()['automaticChangesPaused'])
        self.assertEqual(self.manager.begin()['status'], 'deferred')
        self.assertEqual(self.manager.resolve(identity, 'keep')['status'], 'reviewed')
        self.assertFalse(self.manager.status()['automaticChangesPaused'])
        self.assertEqual(observe('three')['status'], 'reviewed')
        self.assertFalse(observe('two')['recorded'])
        self.assertEqual(observe('four')['status'], 'review-required')
        stored = self.manager._location().read_text()
        self.assertNotIn('private-model', stored)
        self.assertNotIn('SKILL.md', stored)
        self.assertEqual(self.manager.status()['changes'][0]['effect'], 'not-established')
        self.assertFalse(self.manager.observe(identity, 'stale', 'failed', 'verification', '0' * 64)['recorded'])

    def test_guarded_rollback_restores_only_recorded_content_and_preserves_user_edits(self):
        result = self.applied_change()
        previous = self.base / 'previous-plan.json'
        previous.write_text(json.dumps(self.plan), encoding='utf-8')
        skill = self.root / '.agents/skills/project-harness/SKILL.md'
        before = skill.read_bytes()
        with self.assertRaises(ValueError):
            self.manager.resolve(result['changeId'], 'rollback', plan=self.updated_plan('\nUnrelated correction.\n'))
        self.assertEqual(skill.read_bytes(), before)
        skill.write_bytes(before + b'\nuser edit\n')
        with self.assertRaisesRegex(ValueError, 'Modified'):
            self.manager.resolve(result['changeId'], 'rollback', plan=previous)
        self.assertTrue(skill.read_bytes().endswith(b'user edit\n'))
        skill.write_bytes(before)
        self.assertEqual(self.manager.resolve(result['changeId'], 'rollback', plan=previous)['status'], 'rolled-back')
        self.assertEqual(skill.read_text(encoding='utf-8'), self.plan['artifacts'][0]['content'])

    def test_previous_state_migrates_in_memory_and_interrupted_apply_blocks_new_changes(self):
        self.manager.configure('suggest')
        path = self.manager._location()
        old = json.loads(path.read_text())
        old.pop('changes')
        for name in ('policy', 'recentReviews', 'retired', 'trackingIncomplete'):
            old.pop(name)
        old['schema'] = 1
        path.write_text(json.dumps(old))
        before = path.read_bytes()
        self.assertEqual(self.manager.status()['mode'], 'suggest')
        self.assertEqual(path.read_bytes(), before)
        self.manager.configure('auto')
        self.signal()
        self.hook()
        identity = self.lease()['id']
        with mock.patch.object(harness_apply, 'apply_application', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                self.manager.finish(identity, 'apply', plan=self.updated_plan())
        self.assertTrue(self.manager.status()['automaticChangesPaused'])
        self.hook('Stop')
        self.now += 181
        self.assertEqual(self.manager.resolve(identity, 'keep')['writes'], 0)

    def test_completed_rollback_recovers_its_intent_and_external_config_can_close_old_review(self):
        result = self.applied_change()
        previous = self.base / 'previous-plan.json'
        previous.write_text(json.dumps(self.plan), encoding='utf-8')
        apply = harness_apply.apply_application
        def interrupted(application):
            apply(application)
            raise OSError('Interrupted after the project transaction completed')
        with mock.patch.object(harness_apply, 'apply_application', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.manager.resolve(result['changeId'], 'rollback', plan=previous)
        self.assertTrue(self.manager.status()['automaticChangesPaused'])
        self.assertEqual(self.manager.resolve(result['changeId'], 'rollback')['writes'], 0)
        self.assertFalse(self.manager.status()['automaticChangesPaused'])
        self.now += 3700
        (self.root / 'review.txt').write_text('An explicitly reviewed workflow gap')
        self.manager.signal('user-request', 'review.txt', 'next-review')
        self.hook()
        result = self.manager.finish(self.lease()['id'], 'apply', plan=self.updated_plan())
        self.hook('Stop')
        newer = minimal_plan(self.root, skill_suffix='\nExplicit user-requested configuration.\n')
        apply(harness_apply.build_application(self.root, newer))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'revision changed'):
            self.manager.resolve(result['changeId'], 'rollback', plan=previous)
        self.assertEqual(self.manager.resolve(result['changeId'], 'keep')['status'], 'superseded')
        self.assertEqual(self.snapshot(), before)

    def test_oversized_history_write_preserves_previous_state(self):
        self.manager.configure('suggest')
        path = self.manager._location()
        before = path.read_bytes()
        with mock.patch.object(maintenance, 'MAX_STATE', len(before) + 10):
            with self.assertRaisesRegex(ValueError, 'size limit'):
                self.signal()
        self.assertEqual(path.read_bytes(), before)

    def test_operations_annotation_links_only_explicit_harness_concerns(self):
        import harness_ops
        self.manager.configure('auto')
        def annotate(turn, linked):
            event = harness_ops.record_hook_event({'hook_event_name': 'UserPromptSubmit', 'session_id': 'ops-session',
                'turn_id': turn, 'cwd': str(self.root), 'prompt': 'fixture task'}, state_root=self.state)
            return harness_ops.annotate(root=self.root, state_root=self.state, work_item_ref=event['workItemRef'],
                relation='new-task', category='unknown', execution_class='direct', agent_selection='not-applicable',
                outcome='failed', verification='failed', evidence_source='verification',
                **({'maintenance_reason': 'verification-gap', 'maintenance_evidence': 'pyproject.toml'} if linked else {}))
        annotate('code-bug', False)
        self.assertEqual(self.manager.status()['pending'], 0)
        annotate('gap-one', True)
        self.assertEqual(self.manager.status()['pending'], 0)
        self.assertIn('signal', annotate('gap-two', True)['maintenance'])
        self.assertEqual(self.manager.status()['pending'], 1)

    def test_apply_rejects_user_edits_without_overwrite(self):
        self.manager.configure('auto')
        self.signal(); self.hook()
        path = self.root / '.agents/skills/project-harness/SKILL.md'
        path.write_text(path.read_text() + '\nUser content\n')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.manager.finish(self.lease()['id'], 'apply', plan=self.updated_plan())
        self.assertEqual(before, self.snapshot())

    def test_automatic_content_update_cannot_change_file_mode(self):
        self.manager.configure('auto')
        self.signal(); self.hook()
        path = self.updated_plan()
        plan = json.loads(path.read_text())
        plan['artifacts'][0]['mode'] = '0777'
        path.write_text(json.dumps(plan))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'file permissions'):
            self.manager.finish(self.lease()['id'], 'apply', plan=path)
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
        self.assertIn('record the bounded evidence signal', self.hook('SessionStart'))
        self.hook(session='other')
        self.signal()
        self.assertEqual(self.hook(), '')
        self.assertIsNone(self.lease())
        self.hook('Stop', session='other')
        self.hook('SubagentStart', agent_id='child')
        self.assertEqual(self.hook(), '')
        self.hook('SubagentStop', agent_id='child')
        self.assertIn('review', self.hook())

    def test_signal_policy_is_announced_once_without_prompt_inspection_or_review(self):
        self.manager.configure('auto')
        before = self.snapshot()
        with mock.patch.object(self.manager, 'manifest', side_effect=AssertionError('No project scan')):
            self.assertIn('Project maintenance is auto', self.hook('SessionStart'))
            self.assertEqual(self.hook('SessionStart', source='resume'), '')
            for _ in range(10):
                self.assertEqual(self.hook(), '')
                self.hook('Stop')
            self.assertIn('Project maintenance is auto', self.hook('SessionStart', source='compact'))
        self.assertIsNone(self.lease())
        self.assertEqual(self.manager.status()['metrics']['reviews'], 0)
        self.assertEqual(self.snapshot(), before)
        self.manager.configure('suggest')
        self.assertIn('Project maintenance is suggest', self.hook())
        self.assertEqual(self.hook(), '')

    def test_legacy_session_gets_policy_once_when_sessionstart_was_missed(self):
        self.manager.configure('suggest')
        with self.manager.transaction() as state:
            key = self.manager.store.fingerprint(b'session-a')
            state['sessions'][key] = {'active': False, 'children': [], 'seenRevision': None}
        self.assertIn('Project maintenance is suggest', self.hook())
        self.assertEqual(self.hook(), '')

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

    def test_apply_rechecks_revision_and_deadline_after_lock_wait(self):
        for change in ('revision', 'deadline'):
            with self.subTest(change=change):
                self.manager.configure('auto')
                with (self.root / 'pyproject.toml').open('a') as stream:
                    stream.write('# ' + change + '\n')
                self.signal(observation=change)
                lease = self.manager.begin()
                candidate = self.updated_plan()
                self.now = lease['deadline'] - 1
                preserved = {}
                @contextmanager
                def wait_for_lock(root):
                    if change == 'revision':
                        newer = minimal_plan(self.root, skill_suffix='\nConcurrent explicit configuration.\n')
                        harness_apply.apply_application(harness_apply.build_application(self.root, newer))
                    else:
                        self.now += 2
                    preserved.update(self.snapshot())
                    with harness_eval_lock.project_lock(root):
                        yield
                with mock.patch.object(maintenance, 'project_lock', side_effect=wait_for_lock):
                    with self.assertRaisesRegex(ValueError, 'changed during review|deadline'):
                        self.manager.finish(lease['id'], 'apply', plan=candidate)
                self.assertEqual(preserved, self.snapshot())
                self.assertEqual(self.lease()['id'], lease['id'])
                self.assertEqual(self.manager.status()['metrics']['applied'], 0)
                self.now += 86401

    def test_apply_holds_project_lock_through_planning_and_write(self):
        self.manager.configure('auto')
        self.signal()
        lease = self.manager.begin()['id']
        original_build = self.manager._limited_application
        original_apply = harness_apply.apply_application
        attempted, held = threading.Event(), []
        acquire = harness_eval_lock.FileLock.acquire
        def inspect_lock():
            def competing_acquire(lock):
                lock.timeout = 0.1
                lock.poll_interval = 0.01
                attempted.set()
                return acquire(lock)
            def compete():
                try:
                    with harness_eval_lock.project_lock(self.root):
                        held.append(False)
                except harness_eval_lock.LockError:
                    held.append(True)
            with mock.patch.object(harness_eval_lock.FileLock, 'acquire', competing_acquire):
                worker = threading.Thread(target=compete, daemon=True)
                worker.start()
                self.assertTrue(attempted.wait(5))
                worker.join(5)
                self.assertFalse(worker.is_alive())
            attempted.clear()
        def build(plan):
            inspect_lock()
            return original_build(plan)
        def apply(application):
            inspect_lock()
            return original_apply(application)
        with mock.patch.object(self.manager, '_limited_application', side_effect=build), \
                mock.patch.object(harness_apply, 'apply_application', side_effect=apply):
            result = self.manager.finish(lease, 'apply', plan=self.updated_plan())
        self.assertEqual(result['status'], 'apply')
        self.assertEqual(held, [True, True])

    def test_apply_refuses_deadline_expired_while_building_without_writes(self):
        self.manager.configure('auto')
        self.signal()
        lease = self.manager.begin()
        build = self.manager._limited_application
        before = self.snapshot()
        def expire(plan):
            application = build(plan)
            self.now = lease['deadline'] + 1
            return application
        with mock.patch.object(self.manager, '_limited_application', side_effect=expire):
            with self.assertRaisesRegex(ValueError, 'deadline passed before apply'):
                self.manager.finish(lease['id'], 'apply', plan=self.updated_plan())
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.lease()['id'], lease['id'])

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
