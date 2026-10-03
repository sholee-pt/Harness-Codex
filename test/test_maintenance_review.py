"""Regression checks for retriable, contextual and concurrent maintenance."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from test_harness_tools import harness_apply, minimal_plan
import harness_maintenance as maintenance
from harness_eval_lock import FileLock


class MaintenanceReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))
        self.now = 100000.0
        self.manager = maintenance.Maintenance(self.root, self.base / 'state', clock=lambda: self.now)
        self.manager.configure('auto')

    def hook(self, kind='UserPromptSubmit', session='original', **extra):
        return self.manager.hook({'hook_event_name': kind, 'session_id': session, **extra})

    def signal(self, reason='scope-changed', observation='first', session=None, evidence='pyproject.toml'):
        ref = None
        if session is not None:
            ref = self.manager.store.fingerprint(session.encode())
        return self.manager.signal(reason, evidence, observation, session_ref=ref)

    def plan(self, number=0):
        path = self.base / 'plan.json'
        path.write_text(json.dumps(minimal_plan(self.root, skill_suffix='\nVerify fixture revision ' + str(number) + '.\n')))
        return path

    def production_hook(self):
        event = {'hook_event_name': 'UserPromptSubmit', 'session_id': 'new-worker', 'cwd': str(self.root)}
        output = io.StringIO()
        with mock.patch.object(sys, 'argv', ['maintenance', 'hook']), \
                mock.patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(json.dumps(event).encode()))), \
                mock.patch.object(maintenance, 'Maintenance', return_value=self.manager), contextlib.redirect_stdout(output):
            self.assertEqual(maintenance.main(), 0)
        return json.loads(output.getvalue())

    def test_deferred_and_expired_concerns_retry_with_budget_without_new_evidence(self):
        self.signal()
        lease = self.manager.begin()
        self.manager.finish(lease['id'], 'deferred')
        self.assertEqual(self.manager.status()['pending'], 1)
        self.assertEqual(self.manager.begin()['status'], 'deferred')
        self.now += 3700
        retry = self.manager.begin()
        self.assertEqual(retry['status'], 'claimed')
        self.now = retry['deadline'] + 1
        self.assertEqual(self.manager.begin()['status'], 'deferred')
        self.assertEqual(self.manager.status()['pending'], 1)
        self.now += 86401
        self.assertEqual(self.manager.begin()['status'], 'claimed')

    def test_explicit_review_keeps_disabled_state_absent(self):
        state = self.base / 'disabled-state'
        disabled = maintenance.Maintenance(self.root, state)
        self.assertEqual(disabled.begin(evidence='pyproject.toml')['status'], 'disabled')
        self.assertFalse(state.exists())

    def test_source_edits_accumulate_independent_observations_without_filling_candidates(self):
        for index in range(40):
            with (self.root / 'pyproject.toml').open('a') as stream:
                stream.write('# routine edit ' + str(index) + '\n')
            self.assertTrue(self.signal('workflow-gap', 'turn-' + str(index))['recorded'])
        state = self.manager._read(self.manager._location())
        self.assertEqual(len(state['candidates']), 1)
        self.assertEqual(self.manager.status()['pending'], 1)
        self.assertEqual(self.manager.begin()['status'], 'claimed')
        self.assertNotIn('pyproject.toml', self.manager._location().read_text())

    def test_resolved_source_version_stays_suppressed_but_new_version_reopens(self):
        self.signal()
        self.manager.finish(self.manager.begin()['id'], 'unchanged')
        self.assertFalse(self.signal(observation='another')['recorded'])
        with (self.root / 'pyproject.toml').open('a') as stream:
            stream.write('# relevant update\n')
        self.assertTrue(self.signal(observation='new-version')['recorded'])
        self.assertEqual(self.manager.status()['pending'], 1)

    def test_only_current_evidence_context_can_receive_automatic_review(self):
        self.hook('SessionStart')
        self.signal(session='original')
        self.assertNotIn('Review lease', self.hook(session='other'))
        self.hook('Stop', session='other')
        context = self.hook()
        self.assertIn('Review lease', context)
        self.assertNotIn('pyproject.toml', context)

    def test_unbound_and_compacted_context_require_explicit_evidence_reselection(self):
        self.signal()
        self.assertEqual(self.manager.status()['contextRequired'], 1)
        self.assertNotIn('Review lease', self.hook())
        self.hook('Stop')
        self.signal(session='original')
        self.hook('SessionStart', source='compact')
        self.assertEqual(self.manager.status()['contextRequired'], 1)
        self.assertNotIn('Review lease', self.hook())
        self.hook('Stop')
        self.assertEqual(self.manager.begin(evidence='pyproject.toml')['status'], 'claimed')

    def test_manual_review_selects_only_the_current_explicit_source(self):
        for name in ('first.txt', 'second.txt'):
            (self.root / name).write_text('Selected evidence ' + name)
            self.signal(evidence=name)
        first = self.manager.begin(evidence='first.txt')
        self.assertEqual(len(first['candidates']), 1)
        self.manager.finish(first['id'], 'deferred')
        self.now += 3700
        second = self.manager.begin(evidence='second.txt')
        self.assertEqual(len(second['candidates']), 1)
        self.assertNotEqual(first['candidates'], second['candidates'])
        self.manager.finish(second['id'], 'unchanged')
        self.assertEqual(self.manager.status()['pending'], 1)

    def test_changed_signal_during_review_is_not_accidentally_resolved(self):
        self.signal()
        lease = self.manager.begin()
        (self.root / 'pyproject.toml').write_text('[project]\nname = "updated"\n')
        self.signal(observation='later')
        self.manager.finish(lease['id'], 'unchanged')
        self.assertEqual(self.manager.status()['pending'], 1)

    def test_compaction_defers_an_issued_lease_without_resolving_the_concern(self):
        self.hook('SessionStart')
        self.signal(session='original')
        self.assertIn('Review lease', self.hook())
        self.hook('SessionStart', source='compact')
        self.assertFalse(self.manager.status()['reviewInProgress'])
        self.assertEqual(self.manager.status()['pending'], 1)
        self.assertEqual(self.manager.status()['contextRequired'], 1)

    def test_operations_annotation_can_bind_only_explicit_current_session_context(self):
        import harness_ops
        self.hook('SessionStart')
        ref = self.manager.store.fingerprint(b'original')
        for index in range(2):
            event = harness_ops.record_hook_event({'hook_event_name': 'UserPromptSubmit', 'session_id': 'original',
                'turn_id': str(index), 'cwd': str(self.root), 'prompt': 'Do not persist this'}, state_root=self.base / 'state')
            result = harness_ops.annotate(root=self.root, state_root=self.base / 'state', work_item_ref=event['workItemRef'],
                relation='new-task', category='unknown', execution_class='direct', agent_selection='not-applicable',
                outcome='failed', verification='failed', evidence_source='verification',
                maintenance_reason='workflow-gap', maintenance_evidence='pyproject.toml', maintenance_session_ref=ref)
            self.assertTrue(result['maintenance']['signal']['recorded'])
        self.assertIn('Review lease', self.hook())

    def test_off_closes_known_parent_and_child_without_tracking_new_sessions(self):
        self.hook()
        self.hook('SubagentStart', agent_id='child')
        self.manager.configure('off')
        self.hook('UserPromptSubmit', session='untracked')
        self.hook('SubagentStop', agent_id='child')
        self.hook('Stop')
        self.hook('SessionEnd')
        self.assertEqual(self.manager.status()['blockingSessions'], [])
        self.assertEqual(self.manager._read(self.manager._location())['sessions'], {})
        self.manager.configure('auto')
        self.signal()
        self.assertEqual(self.manager.begin()['status'], 'claimed')

    def test_hook_lock_timeout_pauses_auto_until_explicit_session_recovery(self):
        held, release = threading.Event(), threading.Event()
        def holder():
            with FileLock(self.manager._location().with_suffix('.lock')):
                held.set()
                release.wait(5)
        worker = threading.Thread(target=holder)
        worker.start()
        self.assertTrue(held.wait(2))
        try:
            response = self.production_hook()
            self.assertIn('timeout', response['systemMessage'])
            self.assertNotIn('decision', response)
        finally:
            release.set()
            worker.join(2)
        self.assertTrue(self.manager.status()['trackingIncomplete'])
        self.signal()
        self.assertEqual(self.manager.begin()['status'], 'deferred')
        self.manager.recover_session('all')
        self.assertFalse(self.manager.status()['trackingIncomplete'])
        self.assertEqual(self.manager.begin()['status'], 'claimed')

    def test_overlapping_prompt_blocks_only_during_actual_apply_and_is_never_replayed(self):
        self.signal()
        lease = self.manager.begin()
        plan = self.plan()
        started, release = threading.Event(), threading.Event()
        apply = harness_apply.apply_application
        failures = []
        def delayed(application):
            started.set()
            self.assertTrue(release.wait(5))
            return apply(application)
        def finish():
            try:
                self.manager.finish(lease['id'], 'apply', plan=plan)
            except BaseException as exc:
                failures.append(exc)
        with mock.patch.object(harness_apply, 'apply_application', side_effect=delayed):
            worker = threading.Thread(target=finish)
            worker.start()
            self.assertTrue(started.wait(2))
            try:
                response = self.production_hook()
                self.assertEqual(response['decision'], 'block')
                self.assertIn('Retry this request', response['reason'])
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertFalse(self.manager.status()['trackingIncomplete'])
        self.assertEqual(self.manager.status()['metrics']['applied'], 1)
        self.assertNotIn(self.manager.store.fingerprint(b'new-worker'), self.manager._read(self.manager._location())['sessions'])

    def test_new_worker_during_planning_is_recorded_and_prevents_apply(self):
        self.signal()
        lease = self.manager.begin()
        original = self.manager._limited_application
        before = (self.root / '.agents/skills/project-harness/SKILL.md').read_bytes()
        def build(plan):
            self.hook(session='concurrent')
            return original(plan)
        with mock.patch.object(self.manager, '_limited_application', side_effect=build):
            with self.assertRaisesRegex(ValueError, 'Another task'):
                self.manager.finish(lease['id'], 'apply', plan=self.plan())
        self.assertEqual((self.root / '.agents/skills/project-harness/SKILL.md').read_bytes(), before)
        self.assertFalse(self.manager.status()['trackingIncomplete'])

    def test_interrupted_prejournal_apply_marker_pauses_before_spending_review_budget(self):
        self.signal()
        marker = self.manager._location().with_name('apply-active')
        marker.touch()
        self.assertFalse((self.root / '.harness/transaction.json').exists())
        status = self.manager.status()
        self.assertTrue(status['applicationMarkerPresent'])
        self.assertTrue(status['automaticChangesPaused'])
        self.assertEqual(self.manager.begin(evidence='pyproject.toml')['status'], 'deferred')
        self.assertEqual(self.manager.status()['metrics']['reviews'], 0)
        self.assertEqual(self.manager.recover_session('all')['status'], 'session-recovered')
        self.assertFalse(marker.exists())
        self.assertFalse(self.manager.status()['automaticChangesPaused'])
        lease = self.manager.begin(evidence='pyproject.toml')
        self.assertEqual(lease['status'], 'claimed')
        self.assertEqual(self.manager.finish(lease['id'], 'apply', plan=self.plan())['status'], 'apply')

    def test_successful_revisions_retire_prior_observation_and_continue_past_history_limit(self):
        for index in range(18):
            self.now += 86401
            (self.root / 'evidence.txt').write_text('Selected concern ' + str(index))
            self.signal('user-request', str(index), evidence='evidence.txt')
            lease = self.manager.begin()
            self.assertEqual(lease['status'], 'claimed')
            self.assertEqual(self.manager.finish(lease['id'], 'apply', plan=self.plan(index))['status'], 'apply')
        status = self.manager.status()
        self.assertEqual(status['metrics']['applied'], 18)
        self.assertEqual(len(status['changes']), 16)
        self.assertEqual(sum(item['status'] == 'observing' for item in status['changes']), 1)
        self.assertFalse(status['automaticChangesPaused'])

    def test_legacy_unbound_candidates_migrate_without_rewriting_on_status(self):
        self.signal()
        path = self.manager._location()
        state = json.loads(path.read_text())
        state['schema'] = 4
        item = next(iter(state['candidates'].values()))
        item.pop('session')
        legacy = self.manager.store.fingerprint(('scope-changed\0pyproject.toml\0' + item['evidence']).encode())
        state['candidates'] = {legacy: item}
        path.write_text(json.dumps(state))
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.assertEqual(self.manager.status()['contextRequired'], 1)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertNotIn('Review lease', self.hook())
        self.hook('Stop')
        self.assertEqual(self.manager.begin(evidence='pyproject.toml')['status'], 'claimed')

    def test_full_legacy_history_merges_selected_source_versions_without_raw_paths(self):
        path = self.manager._location()
        for action in ('signal', 'begin'):
            with self.subTest(action=action):
                state = maintenance.default_state()
                state['schema'] = 4
                state['mode'] = 'auto'
                for index in range(32):
                    evidence = self.manager.store.fingerprint(('old-version-' + str(index)).encode())
                    key = self.manager.store.fingerprint(('workflow-gap\0pyproject.toml\0' + evidence).encode())
                    state['candidates'][key] = {'reason': 'workflow-gap', 'evidence': evidence, 'status': 'pending',
                        'observations': [self.manager.store.fingerprint(('turn-' + str(index)).encode())]}
                path.write_text(json.dumps(state))
                if action == 'signal':
                    self.assertTrue(self.signal('workflow-gap', 'current')['recorded'])
                else:
                    self.assertEqual(self.manager.begin(evidence='pyproject.toml')['status'], 'claimed')
                current = self.manager._read(path)
                self.assertEqual(len(current['candidates']), 1)
                self.assertEqual(self.manager.status()['pending'], 1)
                self.assertNotIn('pyproject.toml', path.read_text())


if __name__ == '__main__':
    unittest.main()
