"""Cross-boundary regressions from the whole-repository review."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from test_harness_tools import minimal_plan, harness_apply
import harness_eval_store as store_module
import harness_eval_types as types
import harness_ops
import harness_maintenance
from harness_cli import configuration, main, presentation, terminal_menu

ROOT = Path(__file__).resolve().parents[1]


class ReviewBoundaries(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.project = self.base / 'project'
        self.project.mkdir()
        self.enterContext(mock.patch.dict(os.environ, {'HARNESS_LOCK_HOME': str(self.base / 'locks')}))

    @contextmanager
    def linked(self, path, target):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.rmdir()
        if os.name == 'nt':
            quote = lambda p: "'" + str(p).replace("'", "''") + "'"
            subprocess.run(['powershell', '-NoProfile', '-Command',
                f'New-Item -ItemType Junction -Path {quote(path)} -Target {quote(target)} | Out-Null'], check=True, capture_output=True)
        else:
            path.symlink_to(target, target_is_directory=True)
        try:
            yield
        finally:
            if os.name == 'nt':
                path.rmdir()
            else:
                path.unlink()

    def test_collection_aliases_are_rejected_before_any_purge_or_export(self):
        harness_apply.apply_application(harness_apply.build_application(self.project, minimal_plan(self.project)))
        store = store_module.EvaluationStore(self.base / 'state')
        repository = store.register_workspace(self.project)
        root = store.repository_root(repository)
        earlier = root / 'runs/completed/retained.json'
        earlier.write_text('{}')
        for location in ('runs/completed/nested', 'annotations', 'operations/events'):
            for outside in (True, False):
                with self.subTest(location=location, outside=outside):
                    target = (self.base if outside else store.root) / ('outside' if outside else 'alias-target')
                    target.mkdir(exist_ok=True)
                    sentinel = target / 'unrelated.json'
                    sentinel.write_text('{"retain": true}')
                    before = sentinel.read_bytes(), sentinel.stat().st_mtime_ns
                    with self.linked(root / location, target):
                        if location.startswith('operations'):
                            with self.assertRaises(store_module.StoreError):
                                harness_ops.command_purge(SimpleNamespace(root=str(self.project), state_home=str(store.root)))
                        else:
                            for action in (store.purge_repository, store.export_repository, store.repair_repository):
                                with self.assertRaises(store_module.StoreError):
                                    action(repository)
                        self.assertEqual((sentinel.read_bytes(), sentinel.stat().st_mtime_ns), before)
                        self.assertEqual(earlier.read_text(), '{}')

    def test_export_rejects_a_sealed_unsupported_schema_and_raw_field(self):
        store = store_module.EvaluationStore(self.base / 'state')
        repository = store.register_workspace(self.project)
        path = store.repository_root(repository) / 'runs/completed/invalid.json'
        path.write_text(json.dumps(types.seal_record({'schemaVersion': 999, 'rawPrompt': 'PRIVATE', 'integrity': {}})))
        result = store.export_repository(repository)
        self.assertEqual((result['includedCount'], result['excludedCount']), (0, 1))
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_recover_one_stale_session_preserves_other_workers_and_observations(self):
        harness_apply.apply_application(harness_apply.build_application(self.project, minimal_plan(self.project)))
        manager = harness_maintenance.Maintenance(self.project, self.base / 'state', clock=lambda: 100000)
        manager.configure('auto')
        for session in ('stopped', 'running'):
            manager.hook({'hook_event_name': 'UserPromptSubmit', 'session_id': session})
        manager.signal('scope-changed', 'pyproject.toml', 'later-task')
        self.assertEqual(manager.begin()['status'], 'deferred')
        before = manager.status()
        manager.recover_session(manager.store.fingerprint(b'stopped'))
        self.assertEqual(manager.begin()['status'], 'deferred')
        self.assertEqual(len(manager.status()['blockingSessions']), 1)
        self.assertEqual(manager.status()['pending'], before['pending'])
        manager.hook({'hook_event_name': 'SessionEnd', 'session_id': 'running'})
        lease = manager.begin('stopped')['id']
        self.assertEqual(manager.recover_session(manager.store.fingerprint(b'stopped'))['status'], 'session-recovered')
        self.assertFalse(manager.status()['reviewInProgress'])
        self.assertEqual(manager.status()['pending'], 1)
        with self.assertRaisesRegex(ValueError, 'no longer current'):
            manager.finish(lease, 'unchanged')

    def test_child_preview_is_scoped_and_child_completion_does_not_finish_parent(self):
        server = object.__new__(configuration.Server)
        server.thread_id, server.items, server.messages = 'parent', {}, queue.Queue()
        server.progress, server.completed = presentation.Progress('', stream=io.StringIO()), []
        server.send = mock.Mock()
        def event(method, params, request=None):
            server.messages.put({'method': method, 'params': params, **({'id': request} if request else {})})
            server.event(time.monotonic() + 10)
        change = {'id': 'same-id', 'type': 'fileChange', 'changes': [{'path': 'child.txt', 'kind': {'type': 'update'}, 'diff': '-old\n+new'}]}
        event('item/started', {'threadId': 'child', 'item': change})
        with mock.patch.object(server.progress, 'ask', return_value=''):
            event('item/fileChange/requestApproval', {'threadId': 'child', 'itemId': 'same-id'}, 1)
        self.assertEqual(server.send.call_args.args[0]['result']['decision'], 'accept')
        with self.assertRaisesRegex(ValueError, 'preview'):
            event('item/fileChange/requestApproval', {'threadId': 'parent', 'itemId': 'same-id'}, 2)
        event('item/completed', {'threadId': 'child', 'item': change})
        event('turn/completed', {'threadId': 'child', 'turn': {'status': 'completed'}})
        self.assertEqual(server.items, {})
        self.assertEqual(server.completed, [])

    @unittest.skipUnless(os.name == 'nt', 'Windows staging path expansion')
    def test_long_project_path_can_apply_and_reapply_without_pending_transaction(self):
        root = self.project / ('a' * 75) / ('b' * 35)
        root.mkdir(parents=True)
        plan = minimal_plan(root)
        self.assertGreater(len(str(root)), 150)
        harness_apply.apply_application(harness_apply.build_application(root, plan))
        before = {p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
        result = harness_apply.apply_application(harness_apply.build_application(root, plan))
        self.assertEqual(result['writes'], 0)
        self.assertEqual(before, {p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()})
        self.assertFalse((root / '.harness/transaction.json').exists())

    def test_short_terminal_and_resize_keep_selection_within_viewport(self):
        class TTY(io.StringIO):
            def isatty(self): return True
            def fileno(self): return 0
        output = TTY()
        progress = presentation.Progress('', stream=output)
        size = [10]
        keys = iter(['down'] * 11 + ['\r'])
        @contextmanager
        def keyboard():
            def read():
                size[0] = 6
                return next(keys)
            yield read
        with mock.patch.dict(os.environ, {'TERM': 'xterm'}), mock.patch.object(sys, 'stdin', TTY()), mock.patch.object(terminal_menu, 'keyboard', keyboard), \
                mock.patch.object(terminal_menu.shutil, 'get_terminal_size', side_effect=lambda *a, **kw: os.terminal_size((50, size[0]))):
            choice = terminal_menu.choose(progress, 'Model', [f'model-{i}' for i in range(12)], summary=['Selected: previous'], back=True)
        self.assertEqual(choice, 11)
        self.assertLessEqual(max(map(int, re.findall(r'\x1b\[(\d+)A', output.getvalue()))), 5)
        self.assertIn('model-11', output.getvalue())

    def test_confirmation_normalization_closed_input_and_invalid_retry(self):
        for answer, expected in [('', True), (' Y ', True), ('YES', True), (' n ', False), ('No', False)]:
            with self.subTest(answer=answer), mock.patch.object(sys.stdin, 'isatty', return_value=True), mock.patch('builtins.input', return_value=answer):
                self.assertEqual(presentation.confirm('Proceed?'), expected)
        with mock.patch.object(sys.stdin, 'isatty', return_value=True), mock.patch('builtins.input', side_effect=EOFError):
            self.assertFalse(presentation.confirm('Proceed?'))
        with mock.patch.object(sys.stdin, 'isatty', return_value=False), mock.patch('builtins.input') as read:
            with self.assertRaises(ValueError):
                presentation.confirm('Proceed?')
            read.assert_not_called()
        with mock.patch.object(sys.stdin, 'isatty', return_value=True), mock.patch('builtins.input', side_effect=['invalid', 'n']) as read:
            self.assertFalse(presentation.confirm('Proceed?'))
            self.assertEqual(read.call_count, 2)

    def test_update_messages_and_integration_follow_real_update_outcome(self):
        from harness_cli import codex_integration, release_updates
        for branch in (None, 'v0.28.0-beta'):
            for status in ('up-to-date', 'updated', 'update-available', 'failure'):
                with self.subTest(branch=branch, status=status):
                    result = {'status': status, 'updated': status == 'updated', 'updateAvailable': status in {'updated', 'update-available'},
                              'currentVersion': '0.28.0-beta', 'availableVersion': '0.28.1-beta' if status in {'updated', 'update-available'} else '0.28.0-beta'}
                    action = 'check' if status == 'update-available' else 'update'
                    target = (main.distribution, 'check_update' if action == 'check' else 'update_tool') if branch else (release_updates, action)
                    output, error = io.StringIO(), io.StringIO()
                    with mock.patch.object(main, '_environment'), mock.patch.object(main.distribution, 'installed_status', return_value={'branch': branch, 'release_root': str(ROOT)}), \
                            mock.patch.object(*target, return_value=result, side_effect=ValueError('network unavailable') if status == 'failure' else None), \
                            mock.patch.object(codex_integration, 'read', return_value={}), mock.patch.object(codex_integration, 'install', return_value={'state': 'configured'}) as install, \
                            redirect_stdout(output), redirect_stderr(error):
                        code = main.main(['--no-update-check', 'update', *(['--check'] if action == 'check' else [])], source_root=ROOT)
                    self.assertEqual(code, int(status == 'failure'))
                    self.assertEqual(install.call_count, int(status == 'updated'))
                    self.assertNotIn('Update available: False', output.getvalue())
                    if status == 'up-to-date':
                        self.assertIn('already up to date', output.getvalue())
                        self.assertNotIn('Tool update complete', output.getvalue())
                    elif status == 'failure':
                        self.assertNotIn('complete', output.getvalue())
                        self.assertIn('network unavailable', error.getvalue())
                    else:
                        self.assertIn('Current version:', output.getvalue())
                        self.assertIn('Latest version:', output.getvalue())
