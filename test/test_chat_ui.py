"""Conversation UI over a real subprocess protocol; deterministic, no model calls."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from harness_cli import chat, project
from test_configuration_progress import FAKE, Terminal

SESSION = '00000000-0000-0000-0000-000000000012'


class ChatTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fake = self.root / 'codex fixture.py'
        script = FAKE.replace('native-thread', SESSION)
        script = script.replace('elif method == "turn/start":', '''elif method == 'thread/list':
        send({'id': value['id'], 'result': {'data': [{'id': "''' + SESSION + '''", 'name': 'Saved work', 'cwd': str(pathlib.Path.cwd())}], 'nextCursor': None}})
    elif method == 'turn/interrupt':
        complete()
        send({'id': value['id'], 'result': {}})
    elif method == "turn/start":''')
        self.fake.write_text(script, encoding='utf-8')
        self.log = self.root / 'wire.jsonl'
        self.command = [sys.executable, '-B', str(self.fake)]
        self.output = io.StringIO()

    def run_chat(self, answers, *, mode='noop', **kwargs):
        with mock.patch.dict(os.environ, {'TEST_SERVER_MODE': mode, 'TEST_SERVER_LOG': str(self.log)}), \
                mock.patch.object(sys, 'stdin', Terminal()), mock.patch('builtins.input', side_effect=answers), \
                contextlib.redirect_stdout(self.output):
            return chat.run(self.command, self.root, 'PRIVATE ACTIVATION', settings='auto', **kwargs)

    def records(self, method):
        return [item['params'] for item in map(json.loads, self.log.read_text().splitlines()) if item['method'] == method]

    def test_multiple_requests_share_one_session_and_one_activation(self):
        self.assertEqual(self.run_chat(['Fix README wording.', 'Review concurrency.', '계속 진행해줘.', '/task Fix README wording.', '/quit']), (0, None))
        turns = self.records('turn/start')
        self.assertEqual(len(turns), 4)
        self.assertEqual(len(self.records('thread/start')), 1)
        self.assertEqual([turn['effort'] for turn in turns], ['medium', 'high', 'high', 'medium'])
        self.assertEqual({turn['threadId'] for turn in turns}, {SESSION})
        self.assertEqual(sum('PRIVATE ACTIVATION' in turn['input'][0]['text'] for turn in turns), 1)
        self.assertEqual(len(self.records('model/list')), 2)  # Catalog pages, not one model per prompt.
        for turn in turns:
            self.assertEqual(set(turn), {'threadId', 'input', 'model', 'effort'})
        self.assertNotIn('PRIVATE ACTIVATION', self.output.getvalue())
        self.assertFalse((self.root / '.harness').exists())

    def test_auto_is_first_and_manual_stays_fixed_until_auto_is_selected(self):
        answers = ['/model', '3', '1', 'Review architecture.', 'Continue.', '/model', '0', '/task Review architecture.', '/quit']
        self.assertEqual(self.run_chat(answers), (0, None))
        turns = self.records('turn/start')
        self.assertEqual([(t['model'], t['effort']) for t in turns[:2]], [('catalog-alternative', 'ultra')] * 2)
        self.assertEqual((turns[2]['model'], turns[2]['effort']), ('native-configured-model', 'high'))
        self.assertIn('0. Auto', self.output.getvalue())

    def test_no_empty_session_or_bootstrap_turn_on_exit(self):
        self.assertEqual(self.run_chat(['/help', '/status', '/quit']), (0, None))
        self.assertFalse(self.records('thread/start'))
        self.assertFalse(self.records('turn/start'))

    def test_resume_reuses_native_history_without_repeated_activation_turn(self):
        self.assertEqual(self.run_chat(['/quit'], resume=True, session_id=SESSION), (0, None))
        self.assertEqual(self.records('thread/resume'), [{'cwd': str(self.root), 'threadId': SESSION, 'excludeTurns': True}])
        self.assertFalse(self.records('thread/start'))
        self.assertFalse(self.records('turn/start'))

    def test_resume_picker_last_and_exact_name_select_existing_thread(self):
        for kwargs, answers in [({'last': True}, ['/quit']), ({'session_id': 'Saved work'}, ['/quit']), ({}, ['1', '/quit'])]:
            self.log.unlink(missing_ok=True)
            self.assertEqual(self.run_chat(answers, resume=True, **kwargs), (0, None))
            self.assertEqual(self.records('thread/resume')[0]['threadId'], SESSION)
            self.assertFalse(self.records('turn/start'))

    def test_native_handoff_keeps_same_session(self):
        self.assertEqual(self.run_chat(['Explain the project.', '/native']), (0, SESSION))
        self.assertEqual(len(self.records('thread/start')), 1)

    def test_unsupported_native_commands_are_not_sent_as_tasks(self):
        self.assertEqual(self.run_chat(['/permissions', '/compact', '/quit']), (0, None))
        self.assertFalse(self.records('turn/start'))
        self.assertIn('/native', self.output.getvalue())

    def test_permissions_are_never_broadened_and_failed_requests_are_not_retried(self):
        self.assertEqual(self.run_chat(['Run the task.'], mode='permissions')[0], 1)
        self.assertEqual(len(self.records('turn/start')), 1)
        self.assertEqual(self.records('answer'), [{'permissions': {}, 'scope': 'turn'}])
        self.assertNotIn('sandboxPolicy', self.records('turn/start')[0])

    def test_command_approval_requires_explicit_yes(self):
        for answer, expected in [('', 'decline'), ('yes', 'accept')]:
            self.log.unlink(missing_ok=True)
            self.assertEqual(self.run_chat(['Read the project.', answer, '/quit'], mode='approve'), (0, None))
            self.assertEqual(self.records('answer'), [{'decision': expected}])
            self.assertIn('cat README.md', self.output.getvalue())

    def test_deadline_sends_native_interrupt_without_resubmitting(self):
        self.assertEqual(self.run_chat(['Do the work.', '/quit'], mode='timeout', timeout=0.5), (0, None))
        self.assertEqual(len(self.records('turn/start')), 1)
        self.assertEqual(len(self.records('turn/interrupt')), 1)

    def test_unknown_server_request_preserves_native_fallback(self):
        self.assertEqual(self.run_chat(['Do the work.'], mode='unknown')[0], 1)
        self.assertEqual(len(self.records('turn/start')), 1)
        self.assertIn('Original Codex UI:', self.output.getvalue())

    def test_paste_is_one_request_and_client_commands_are_not_model_turns(self):
        self.assertEqual(self.run_chat(['/paste', 'Explain this example:', 'line two', '/end', '/done', '/failed', '/quit']), (0, None))
        turns = self.records('turn/start')
        self.assertEqual(len(turns), 1)
        self.assertTrue(turns[0]['input'][0]['text'].endswith('Explain this example:\nline two'))

    def test_streamed_output_is_not_printed_twice_and_control_codes_are_cleaned(self):
        from harness_cli.chat_transport import ChatServer, Console
        with contextlib.redirect_stdout(self.output):
            console = Console()
            server = object.__new__(ChatServer)
            server.progress, server.streamed = console, set()
            server.observe('item/agentMessage/delta', {'itemId': 'x', 'delta': 'answer\x1b[2J'})
            server.observe('item/completed', {'item': {'id': 'x', 'type': 'agentMessage', 'text': 'answer\x1b[2J'}})
        self.assertEqual(self.output.getvalue().count('answer'), 1)
        self.assertNotIn('\x1b', self.output.getvalue())

    def test_project_integration_preserves_native_default_and_canonical_files(self):
        from test_cli_project import ProjectCliTests, snapshot, REPO_ROOT
        fixture = ProjectCliTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.generate()
        before = snapshot(fixture.root)
        with mock.patch('harness_cli.chat.run', return_value=(0, None)) as launch:
            self.assertEqual(fixture.run_cli('new', '--ui', 'harness', 'actual task')[0], 0)
            self.assertEqual(launch.call_args.kwargs['initial_task'], 'actual task')
            self.assertNotIn('actual task', launch.call_args.args[2])
            self.assertEqual(snapshot(fixture.root), before)
            launch.reset_mock()
            self.assertEqual(fixture.run_cli('new', 'native task')[0], 0)
            launch.assert_not_called()
