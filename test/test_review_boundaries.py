"""Cross-component regressions from independent v0.24.0 review reproductions."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.agents/skills/harness/scripts'))
from harness_cli import distribution as dist, auto_relay as relay
import harness_eval_capture as capture
import harness_eval_store as storage
import harness_maintenance_history as history
from test_cli_distribution import source
import test_harness_ops as ops_fixtures
import harness_ops as ops
from test_official_relay import catalog


class ReviewBoundaryTests(unittest.TestCase):
    def test_install_rechecks_concurrent_committed_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            data, bin_dir = base / 'data', base / 'bin'
            older = source(base / 'older', '0.23.2-beta', 'a' * 40)
            candidate = source(base / 'candidate', '0.24.0-beta', 'b' * 40)
            newer = source(base / 'newer', '0.24.1-beta', 'c' * 40)
            dist.install_tool(older, data, bin_dir, sys.executable)
            lock, injected = dist._lock, []
            @contextlib.contextmanager
            def interleave(root):
                if not injected:
                    injected.append(True)
                    with mock.patch.object(dist, '_lock', lock):
                        dist.install_tool(newer, data, bin_dir, sys.executable)
                with lock(root):
                    yield
            with mock.patch.object(dist, '_lock', interleave), self.assertRaisesRegex(dist.DistributionError, 'changed during setup'):
                dist.install_tool(candidate, data, bin_dir, sys.executable)
            self.assertEqual(dist.installed_status(data)['version'], '0.24.1-beta')

    def test_nested_workspaces_and_purge_keep_separate_histories(self):
        fixture = ops_fixtures.OperationsEvidenceTests()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            mono, state = base / 'monorepo', base / 'state'
            mono.mkdir()
            subprocess.run(['git', 'init', '-q', str(mono)], check=True, capture_output=True)
            projects = [fixture._workspace(mono / name) for name in ('a', 'b')]
            for index, project in enumerate(projects):
                ops.record_hook_event(fixture._hook(project, 'UserPromptSubmit', turn=str(index)), state_root=state)
            reports = [ops.audit(project, state_root=state) for project in projects]
            self.assertNotEqual(reports[0]['repositoryId'], reports[1]['repositoryId'])
            self.assertEqual([report['eventCount'] for report in reports], [1, 1])
            with contextlib.redirect_stdout(io.StringIO()):
                ops.command_purge(SimpleNamespace(root=projects[0], state_home=state))
            self.assertEqual([ops.audit(project, state_root=state)['eventCount'] for project in projects], [0, 1])

    def test_evaluation_purge_preserves_workspace_and_legacy_operations(self):
        fixture = ops_fixtures.OperationsEvidenceTests()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, state = fixture._workspace(base), base / 'state'
            event = ops.record_hook_event(fixture._hook(project, 'UserPromptSubmit'), state_root=state)
            store = storage.EvaluationStore(state_root=state)
            store.purge_repository(event['repositoryId'])
            self.assertEqual(ops.audit(project, state_root=state)['eventCount'], 1)
            legacy = store.register_repository(project)
            legacy_file = store.repository_root(legacy) / 'operations/events/retained.json'
            legacy_file.parent.mkdir(parents=True)
            legacy_file.write_text('{}')
            self.assertFalse(store.purge_repository(legacy)['registryMappingRemoved'])
            self.assertEqual(store.register_repository(project), legacy)
            self.assertEqual(legacy_file.read_text(), '{}')

    def test_reviewed_work_corrections_count_as_new_evidence_not_new_work(self):
        record = {'id': 'a' * 32, 'before': 'b' * 64, 'after': 'c' * 64, 'reasons': ['user-request'], 'evidence': [],
            'files': {'d' * 64: ['e' * 64, 'f' * 64]}, 'status': 'observing', 'observations': {}, 'reviewed': 0}
        for reference in ('1' * 64, '2' * 64):
            history.observe(record, reference, 'unknown', 'verification', '3' * 64)
        record.update(status='reviewed', reviewed=2)
        for reference in ('1' * 64, '2' * 64):
            history.observe(record, reference, 'failed', 'verification', '3' * 64)
            history.validate([record])
        self.assertTrue(history.summary([record])['automaticChangesPaused'])
        self.assertEqual(len(record['observations']), 2)
        self.assertFalse(history.observe(record, '1' * 64, 'failed', 'verification', '3' * 64))

    def test_fork_inherits_both_modes_and_honors_explicit_selection(self):
        for enabled in (False, True):
            policy = relay.Policy(mode='manual' if enabled else 'auto', session_modes={'parent': enabled})
            policy.model_list(catalog())
            for selected, expected in ((None, enabled), ('gpt-5.6-sol', False), (relay.ALIAS, True)):
                params = {'threadId': 'parent'}
                if selected:
                    params['model'] = selected
                response = {'result': {'thread': {'id': 'child'}, 'model': 'gpt-5.6-sol', 'reasoningEffort': 'high'}}
                policy.response(response, 'thread/fork', params)
                self.assertEqual(policy.enabled('child'), expected)
            policy.response({'error': {'message': 'failed'}}, 'thread/fork', {'threadId': 'parent', 'model': relay.ALIAS})
            self.assertEqual(policy.enabled('parent'), enabled)

    def test_evaluation_accepts_future_efforts_and_rejects_unsafe_identifiers(self):
        with mock.patch.object(capture, 'codex_preflight', side_effect=RuntimeError('native preflight reached')):
            for effort in ('none', 'max', 'ultra', 'adaptive'):
                with self.subTest(effort=effort), self.assertRaisesRegex(RuntimeError, 'native preflight reached'):
                    capture.run_codex_jsonl(repository=ROOT, prompt='fixture', sandbox='read-only', timeout_seconds=1, reasoning_effort=effort)
            for effort in ('', 'x' * 257, 'high\n', 'two words', None):
                with self.subTest(effort=effort), self.assertRaises(capture.CaptureError):
                    capture.run_codex_jsonl(repository=ROOT, prompt='fixture', sandbox='read-only', timeout_seconds=1, reasoning_effort=effort)
