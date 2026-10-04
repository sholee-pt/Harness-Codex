"""Task reuse boundary checks using actual verification commands, without models."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.agents/skills/harness/scripts'))
import harness_checkpoint as checkpoint
from build.commit_status import outcome


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'project'
        self.root.mkdir()
        self.store = self.root.parent / 'state'
        self.attempts = {}
        self.real_cleanup = checkpoint._terminate_process_tree
        if os.name == 'nt':
            # These state-transition fixtures do not spawn children. Inject their
            # cleanup evidence without claiming native Windows tree containment.
            def fixture_cleanup(process):
                self.real_cleanup(process)
                return process.poll() is not None
            cleanup = mock.patch.object(checkpoint, '_terminate_process_tree', side_effect=fixture_cleanup)
            cleanup.start()
            self.addCleanup(cleanup.stop)
        self.plan = {'schemaVersion': 1, 'tasks': [self.task('alpha'), self.task('beta'), self.task('qa', ['alpha', 'beta'])]}
        for name in ('alpha', 'beta', 'qa'):
            (self.root / (name + '.in')).write_text(name)
        self.call('init', keep_days=7)

    def task(self, name, dependencies=None):
        return {'id': name, 'dependsOn': dependencies or [], 'inputs': [name + '.in'],
                'outputs': [name + '.out'], 'context': {},
                'checks': [[sys.executable, '-c', "from pathlib import Path; assert Path('" + name + ".out').read_text() == 'ok'"]]}

    def call(self, action, run='first', **kwargs):
        key = (run, kwargs.get('task'))
        if action in {'record', 'quiesce'}:
            kwargs.setdefault('attempt', self.attempts.get(key))
        result = checkpoint.operate(self.root, self.store, self.plan, action, run, **kwargs)
        if action == 'start':
            self.attempts[key] = result['attemptId']
        return result

    def finish(self, name):
        self.call('start', task=name)
        (self.root / (name + '.out')).write_text('ok')
        self.assertEqual(self.call('record', task=name)['status'], 'completed')
        self.call('quiesce', task=name, observed='idle')

    def test_partial_resume_reuses_independent_work_and_preserves_history(self):
        for name in ('alpha', 'beta', 'qa'):
            self.finish(name)
        old = checkpoint.read_json(self.store / 'checkpoint.json')['runs'][checkpoint.digest('first')]
        before = (self.root / 'alpha.out').stat().st_mtime_ns
        (self.root / 'beta.in').write_text('new input')
        result = self.call('resume', run='second', previous='first', keep_days=3)
        self.assertEqual(result['reused'], ['alpha'])
        self.assertEqual(set(result['pending']), {'beta', 'qa'})
        self.assertEqual(checkpoint.read_json(self.store / 'checkpoint.json')['runs'][checkpoint.digest('first')], old)
        self.assertEqual((self.root / 'alpha.out').stat().st_mtime_ns, before)

    def test_stale_attempt_reports_cannot_release_current_writer(self):
        first = self.call('start', task='alpha')['attemptId']
        self.call('quiesce', task='alpha', observed='stopped', attempt=first)
        second = self.call('start', task='alpha')['attemptId']
        self.assertNotEqual(first, second)
        before = (self.store / 'checkpoint.json').read_bytes()
        for action in ('record', 'quiesce'):
            for token in (None, first):
                with self.subTest(action=action, token=token):
                    with self.assertRaisesRegex(ValueError, 'current --attempt'):
                        self.call(action, task='alpha', observed='stopped', attempt=token)
                    self.assertEqual(before, (self.store / 'checkpoint.json').read_bytes())
        with self.assertRaisesRegex(ValueError, 'single-writer'):
            self.call('start', task='beta')
        self.call('quiesce', task='alpha', observed='stopped', attempt=second)
        self.assertEqual(self.call('start', task='beta')['status'], 'running')

    def test_changed_result_is_not_reusable_and_blocks_consumer(self):
        self.finish('alpha')
        self.finish('beta')
        (self.root / 'alpha.out').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'dependency'):
            self.call('start', task='qa')
        self.assertNotIn('alpha', self.call('status')['reusable'])

    def test_result_does_not_release_writer_and_stop_request_is_not_stop(self):
        self.call('start', task='alpha')
        (self.root / 'alpha.out').write_text('ok')
        self.call('record', task='alpha')
        for observed in (None, 'stop-requested'):
            if observed:
                self.call('quiesce', task='alpha', observed=observed)
            with self.assertRaisesRegex(ValueError, 'single-writer'):
                self.call('start', task='beta')
            with self.assertRaisesRegex(ValueError, 'idle/stopped'):
                self.call('resume', run='second', previous='first', keep_days=1)
        self.call('quiesce', task='alpha', observed='stopped')
        self.assertEqual(self.call('start', task='beta')['status'], 'running')

    def test_failed_real_check_cannot_complete_and_retry_is_bounded(self):
        for attempt in range(3):
            self.call('start', task='alpha')
            (self.root / 'alpha.out').write_text('wrong')
            self.assertEqual(self.call('record', task='alpha')['status'], 'blocked')
            self.call('quiesce', task='alpha', observed='idle')
        with self.assertRaisesRegex(ValueError, 'retry budget'):
            self.call('start', task='alpha')
        self.assertFalse(self.call('status')['complete'])

    def test_read_only_consumer_waits_for_completed_producer_to_be_idle(self):
        reader = self.task('reader', ['alpha'])
        reader['outputs'] = []
        self.plan['tasks'].append(reader)
        (self.root / 'reader.in').write_text('input')
        self.call('init', run='readers', keep_days=1)
        self.call('start', run='readers', task='alpha')
        (self.root / 'alpha.out').write_text('ok')
        self.call('record', run='readers', task='alpha')
        with self.assertRaisesRegex(ValueError, 'dependency'):
            self.call('start', run='readers', task='reader')
        self.call('quiesce', run='readers', task='alpha', observed='idle')
        self.assertEqual(self.call('start', run='readers', task='reader')['status'], 'running')

    def test_no_retention_without_consent_and_no_project_local_store(self):
        missing = self.root.parent / 'unused'
        with self.assertRaisesRegex(ValueError, 'Opt in'):
            checkpoint.operate(self.root, missing, self.plan, 'init', 'new')
        self.assertFalse(missing.exists())
        with self.assertRaisesRegex(ValueError, 'outside'):
            checkpoint.operate(self.root, self.root / '.harness/checkpoints', self.plan, 'init', 'new', keep_days=1)
        self.assertFalse((self.root / '.harness').exists())

    def test_state_has_no_raw_paths_commands_task_names_or_context(self):
        text = (self.store / 'checkpoint.json').read_text()
        for value in ('alpha', 'beta', str(self.root), sys.executable, 'Path(', '.in', '.out'):
            self.assertNotIn(value, text)

    def test_changed_contract_and_context_invalidate_only_dependents(self):
        for name in ('alpha', 'beta', 'qa'):
            self.finish(name)
        self.plan['tasks'][1]['context'] = {'evaluator': 'a' * 64}
        result = self.call('resume', run='second', previous='first', keep_days=1)
        self.assertEqual(result['reused'], ['alpha'])
        self.assertIn('contract-changed', result['pending']['beta'])

    def test_modified_store_rejected_without_overwrite(self):
        path = self.store / 'checkpoint.json'
        content = path.read_text().replace('pending', 'completed')
        path.write_text(content)
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.call('status')
        self.assertEqual(path.read_text(), content)

    def test_expiry_does_not_erase_active_ownership(self):
        self.call('start', task='alpha')
        with mock.patch.object(checkpoint.time, 'time', return_value=10**12):
            with self.assertRaisesRegex(ValueError, 'expired'):
                self.call('status')
            with self.assertRaisesRegex(ValueError, 'active'):
                self.call('remove')
            checkpoint.operate(self.root, self.store, None, 'quiesce', 'first', task='alpha', observed='closed', attempt=self.attempts[('first', 'alpha')])
            checkpoint.operate(self.root, self.store, None, 'remove', 'first')

    def test_read_only_status_preserves_bytes_and_mtime(self):
        path = self.store / 'checkpoint.json'
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.call('status')
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_verification_cannot_repair_an_output_and_claim_it_was_correct(self):
        self.plan['tasks'][0]['checks'] = [[sys.executable, '-c', "from pathlib import Path; Path('alpha.out').write_text('ok')"]]
        self.call('init', run='changed', keep_days=1)
        self.call('start', run='changed', task='alpha')
        (self.root / 'alpha.out').write_text('wrong')
        self.assertEqual(self.call('record', run='changed', task='alpha')['verification'], 'failed')

    def test_verification_timeout_keeps_ownership_until_observed_idle(self):
        self.plan['tasks'][0]['checks'] = [[sys.executable, '-c', 'import time; time.sleep(10)']]
        self.call('init', run='slow', keep_days=1)
        self.call('start', run='slow', task='alpha')
        (self.root / 'alpha.out').write_text('ok')
        self.assertEqual(self.call('record', run='slow', task='alpha', timeout=1)['status'], 'blocked')
        with self.assertRaisesRegex(ValueError, 'single-writer'):
            self.call('start', task='beta')

    def test_successful_verifier_needs_confirmed_process_cleanup(self):
        self.call('start', task='alpha')
        (self.root / 'alpha.out').write_text('ok')
        with mock.patch.object(checkpoint, '_terminate_process_tree', return_value=False) as cleanup:
            result = self.call('record', task='alpha')
        cleanup.assert_called_once()
        self.assertEqual(cleanup.call_args.args[0].returncode, 0)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['verification'], 'failed')
        self.assertFalse(self.call('status')['complete'])
        self.call('quiesce', task='alpha', observed='idle')
        self.assertNotIn('alpha', self.call('status')['reusable'])

    @unittest.skipUnless(os.name == 'nt', 'native Windows cleanup assurance')
    def test_windows_real_cleanup_keeps_successful_verification_unverified(self):
        self.call('start', task='alpha')
        (self.root / 'alpha.out').write_text('ok')
        with mock.patch.object(checkpoint, '_terminate_process_tree', side_effect=self.real_cleanup) as cleanup:
            result = self.call('record', task='alpha')
        cleanup.assert_called_once()
        self.assertEqual(cleanup.call_args.args[0].returncode, 0)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['verification'], 'failed')
        self.call('quiesce', task='alpha', observed='idle')
        self.assertNotIn('alpha', self.call('status')['reusable'])

    @unittest.skipIf(os.name == 'nt', 'Linux process-group containment; Windows release is paused')
    def test_successful_verifier_cannot_leave_a_child_writing_later(self):
        child = "import time; from pathlib import Path; time.sleep(.6); Path('escaped').write_text('late')"
        parent = "import subprocess, sys; subprocess.Popen([sys.executable, '-c', " + repr(child) + "])"
        self.plan['tasks'][0]['checks'] = [[sys.executable, '-c', parent]]
        self.call('init', run='background', keep_days=1)
        self.call('start', run='background', task='alpha')
        (self.root / 'alpha.out').write_text('ok')
        self.call('record', run='background', task='alpha')
        time.sleep(.8)
        self.assertFalse((self.root / 'escaped').exists())

    def test_added_task_keeps_independent_verified_work(self):
        self.finish('alpha')
        self.plan['tasks'].append(self.task('new-task'))
        (self.root / 'new-task.in').write_text('new input')
        self.assertEqual(self.call('resume', run='second', previous='first', keep_days=1)['reused'], ['alpha'])

    def test_partial_plan_cannot_claim_whole_run_completion(self):
        self.finish('alpha')
        self.plan['tasks'] = self.plan['tasks'][:1]
        report = self.call('status')
        self.assertFalse(report['complete'])
        self.assertFalse(report['planMatchesRun'])
        self.assertEqual(report['omittedTasks'], 2)
        self.assertEqual(report['reusable'], ['alpha'])
        self.call('resume', run='replacement', previous='first', keep_days=1)
        self.assertTrue(self.call('status', run='replacement')['complete'])

    @unittest.skipIf(os.name == 'nt', 'Linux process-group containment; Windows release is paused')
    def test_timed_out_verifier_cannot_leave_a_child_writing_later(self):
        child = "import time; from pathlib import Path; time.sleep(2); Path('escaped').write_text('late')"
        parent = "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', " + repr(child) + "]); time.sleep(15)"
        self.plan['tasks'][0]['checks'] = [[sys.executable, '-c', parent]]
        self.call('init', run='descendant', keep_days=1)
        self.call('start', run='descendant', task='alpha')
        (self.root / 'alpha.out').write_text('ok')
        self.assertEqual(self.call('record', run='descendant', task='alpha', timeout=1)['status'], 'blocked')
        time.sleep(1.4)
        self.assertFalse((self.root / 'escaped').exists())
        self.assertFalse(self.call('status', run='descendant')['complete'])

    def test_invalid_dependency_graph_paths_and_budget(self):
        cases = []
        for value in ('../escape', '/absolute', 'a\\b', 'C:/escape', '.'):
            plan = copy.deepcopy(self.plan)
            plan['tasks'][0]['inputs'] = [value]
            cases.append(plan)
        cyclic = copy.deepcopy(self.plan)
        cyclic['tasks'][0]['dependsOn'] = ['qa']
        cases.append(cyclic)
        for plan in cases:
            with self.assertRaises(ValueError):
                checkpoint.compile_plan(self.root, plan)
        with mock.patch.object(checkpoint, 'MAX_BYTES', 1), self.assertRaisesRegex(ValueError, 'budget'):
            checkpoint.compile_plan(self.root, self.plan)


class WorkflowStatusTests(unittest.TestCase):
    def test_no_false_green_when_native_release_fails_or_is_skipped(self):
        verify = {'verify': {'result': 'success'}}
        self.assertEqual(outcome(verify, False), 'success')
        self.assertEqual(outcome(verify, True), 'error')
        self.assertEqual(outcome({**verify, 'native-release': {'result': 'failure'}}, True), 'failure')
        self.assertEqual(outcome({**verify, 'native-release': {'result': 'success'}, 'release': {'result': 'success'}}, True), 'success')


if __name__ == '__main__':
    unittest.main()
