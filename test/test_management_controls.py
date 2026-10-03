"""Local control protocol, native task boundaries and owned-directory cleanup."""
import asyncio
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harness_cli import dashboard, management, management_relay, presentation, project_cleanup
from test_harness_tools import harness_apply, minimal_plan
from harness_cli import lifecycle


class LocalControls(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.sent = []
        async def send(message):
            self.sent.append(message)
        self.call = mock.AsyncMock(return_value={'thread': {'cwd': str(self.root)}})
        self.relay = SimpleNamespace(env=dict(os.environ), binary='codex', after_exit=None)
        self.controls = management_relay.Controls(self.relay, send, self.call)

    async def asyncTearDown(self):
        await self.controls.close()

    def request(self, text):
        return {'id': 10, 'method': 'turn/start', 'params': {'threadId': 'thread', 'input': [{'type': 'text', 'text': text}]}}

    async def test_status_finishes_locally_without_forwarding_task_or_model_request(self):
        self.controls.cli = mock.AsyncMock(return_value='Harness for Codex\nby sholee-pt')
        self.assertTrue(await self.controls.intercept(self.request('/harness/status')))
        await asyncio.gather(*list(self.controls.tasks.values()))
        self.assertEqual([entry.args[0] for entry in self.call.call_args_list], ['thread/read'])
        self.assertEqual(self.sent[0]['id'], 10)
        self.assertEqual(self.sent[-1]['method'], 'turn/completed')
        self.assertEqual(self.sent[-1]['params']['turn']['status'], 'completed')
        self.assertIn('local command', self.sent[2]['params']['item']['text'] + self.sent[3]['params']['delta'])

    async def test_ordinary_input_is_untouched_and_busy_controls_are_refused(self):
        value = self.request('Read README')
        before = json.dumps(value)
        self.assertFalse(await self.controls.intercept(value))
        self.assertEqual(json.dumps(value), before)
        self.controls.busy.add('thread')
        with self.assertRaisesRegex(ValueError, 'finish'):
            await self.controls.intercept(self.request('/harness/remove'))
        self.call.assert_not_called()

    async def test_native_choice_only_accepts_a_listed_answer(self):
        task = asyncio.create_task(self.controls.choose('thread', 'turn', 'Select', [('Back', 'Return')]))
        await asyncio.sleep(0)
        request = self.sent[-1]
        self.assertEqual(request['method'], 'item/tool/requestUserInput')
        self.assertTrue(await self.controls.intercept({'id': request['id'], 'result': {'answers': {'choice': {'answers': ['Back']}}}}))
        self.assertEqual(await task, 'Back')
        self.assertFalse(self.controls.answers)

    async def test_interrupt_cancels_menu_and_completes_turn(self):
        self.assertTrue(await self.controls.intercept(self.request('/harness/settings')))
        await asyncio.sleep(0)
        turn = next(iter(self.controls.tasks))
        self.assertTrue(await self.controls.intercept({'id': 11, 'method': 'turn/interrupt', 'params': {'threadId': 'thread', 'turnId': turn}}))
        await asyncio.gather(*list(self.controls.tasks.values()))
        self.assertEqual(self.sent[-1]['params']['turn']['status'], 'interrupted')
        self.assertFalse(self.controls.answers)

    async def test_configuration_uses_original_model_and_permissions(self):
        value = self.request('/harness/init --goal "Small test project"')
        value['params'].update(model='catalog-model', effort='medium', approvalPolicy='on-request', sandboxPolicy={'type': 'readOnly'})
        self.controls.cli = mock.AsyncMock(return_value='ready')
        with mock.patch('harness_cli.project.load_installer'), mock.patch('harness_cli.project._assert_no_transaction'):
            self.assertFalse(await self.controls.intercept(value))
        self.assertEqual(value['params']['model'], 'catalog-model')
        self.assertEqual(value['params']['sandboxPolicy'], {'type': 'readOnly'})
        self.assertEqual(value['params']['approvalPolicy'], 'on-request')
        self.assertIn('Small test project', value['params']['input'][0]['text'])
        self.assertEqual(self.controls.cli.call_args.args[1], ['init', '--install-only'])

    async def test_configuration_completion_stays_on_original_turn(self):
        self.controls.configuring['thread'] = (self.root, 'config', None)
        (self.root / '.harness').mkdir()
        (self.root / '.harness/manifest.json').write_text('{}')
        self.controls.busy.add('thread')
        self.controls.cli = mock.AsyncMock(return_value='configured')
        await self.controls.observe({'method': 'turn/completed', 'params': {'threadId': 'thread', 'turn': {'id': 'real-turn', 'status': 'completed'}}})
        await asyncio.gather(*list(self.controls.completions.values()))
        self.assertTrue(all(item['params']['turnId'] == 'real-turn' for item in self.sent))
        self.assertFalse(self.controls.busy)
        self.assertEqual(self.controls.cli.call_args.args[1], ['_complete-config', '--codex-binary', 'codex'])

    async def test_clarification_waits_for_generation_without_repeated_validation(self):
        self.controls.configuring['thread'] = (self.root, 'init', None)
        self.controls.cli = mock.AsyncMock(return_value='configured')
        completed = {'method': 'turn/completed', 'params': {'threadId': 'thread', 'turn': {'id': 'answer-turn', 'status': 'completed'}}}
        await self.controls.observe(completed)
        await self.controls.observe(completed)
        self.controls.cli.assert_not_called()
        self.assertIn('thread', self.controls.configuring)
        (self.root / '.harness').mkdir()
        (self.root / '.harness/manifest.json').write_text('{}')
        await self.controls.observe(completed)
        await self.controls.observe(completed)
        await asyncio.gather(*list(self.controls.completions.values()))
        self.controls.cli.assert_awaited_once()
        self.assertNotIn('thread', self.controls.configuring)

    async def test_slow_completion_does_not_block_native_events_and_is_cancelled_on_close(self):
        (self.root / '.harness').mkdir()
        (self.root / '.harness/manifest.json').write_text('{}')
        self.controls.configuring['thread'] = (self.root, 'init', None)
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def pending(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        self.controls.cli = pending
        completed = {'method': 'turn/completed', 'params': {'threadId': 'thread', 'turn': {'id': 'real-turn', 'status': 'completed'}}}
        await asyncio.wait_for(self.controls.observe(completed), .5)
        await asyncio.wait_for(started.wait(), .5)
        self.assertFalse(await self.controls.intercept(self.request('Continue ordinary project work')))
        await self.controls.observe({'method': 'turn/started', 'params': {'threadId': 'other'}})
        self.assertIn('other', self.controls.busy)
        await self.controls.close()
        self.assertTrue(cancelled.is_set())
        self.assertFalse(self.controls.completions)
        self.assertFalse(self.controls.completion_turns)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux process-group cancellation')
    async def test_management_timeout_and_cancellation_reap_npm_process_group(self):
        node = self.root / 'runtime/node/bin/node'
        node.parent.mkdir(parents=True)
        pid_file = self.root / 'npm-pids.json'
        node.write_text('#!' + sys.executable + '\nimport json, os, subprocess, sys, time\n'
                        'from pathlib import Path\n'
                        'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])\n'
                        'Path(' + repr(str(pid_file)) + ').write_text(json.dumps([os.getpid(), child.pid]))\n'
                        'time.sleep(30)\n')
        node.chmod(0o700)
        (self.root / 'harness.py').write_text('import sys\nfrom pathlib import Path\n'
            'sys.path.insert(0, ' + repr(str(REPO)) + ')\nfrom harness_cli.graft_setup import _install\n'
            '_install(Path(' + repr(str(node)) + '), Path(' + repr(str(self.root / 'runtime/package')) + '), '
            '"0.18.0", Path(' + repr(str(self.root / 'npm.log')) + '))\n')
        self.controls.source = self.root
        def running(pid):
            try:
                return Path('/proc/' + str(pid) + '/stat').read_text().split(') ', 1)[1].split()[0] != 'Z'
            except FileNotFoundError:
                return False
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted):
                task = asyncio.create_task(self.controls.cli(self.root, ['graft', 'enable'], timeout=2))
                pids = []
                try:
                    for _ in range(100):
                        if pid_file.exists():
                            pids = json.loads(pid_file.read_text())
                            break
                        await asyncio.sleep(.02)
                    self.assertTrue(pids, 'The npm fixture did not start')
                    if interrupted:
                        task.cancel()
                    with self.assertRaises(asyncio.CancelledError if interrupted else TimeoutError):
                        await task
                    self.assertFalse(any(running(pid) for pid in pids))
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    for pid in pids:
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    pid_file.unlink(missing_ok=True)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux sandbox probe cancellation')
    async def test_management_cancellation_reaps_separate_sandbox_probe(self):
        heartbeat = self.root / 'probe-heartbeat'
        child = ('from pathlib import Path; import time\n'
                 'path = Path(' + repr(str(heartbeat)) + ')\n'
                 'for i in range(100):\n path.write_text(str(i)); time.sleep(.02)\n')
        (self.root / 'harness.py').write_text('import sys\nfrom pathlib import Path\n'
            'sys.path.insert(0, ' + repr(str(REPO)) + ')\nfrom harness_cli.workspace_context import _run\n'
            '_run([sys.executable, "-c", ' + repr(child) + '], Path(' + repr(str(self.root)) + '))\n')
        self.controls.source = self.root
        task = asyncio.create_task(self.controls.cli(self.root, ['_complete-init'], timeout=5))
        try:
            for _ in range(100):
                if heartbeat.exists():
                    break
                await asyncio.sleep(.02)
            self.assertTrue(heartbeat.exists())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            before = heartbeat.read_bytes()
            await asyncio.sleep(.15)
            self.assertEqual(before, heartbeat.read_bytes())
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_switch_only_queues_target_and_keeps_current_history(self):
        other = self.root / 'second project'
        other.mkdir()
        self.controls.choose = mock.AsyncMock(return_value='New conversation')
        result = await self.controls.switch('thread', 'turn', self.root, [str(other)])
        self.assertEqual(self.relay.after_exit, {'action': 'switch', 'root': str(other), 'resume': False})
        self.assertIn('/quit', result)
        self.call.assert_not_called()
        self.assertEqual(list(other.iterdir()), [])

    async def test_switch_missing_mount_never_guesses_another_location(self):
        with self.assertRaises(ValueError):
            await self.controls.switch('thread', 'turn', self.root, [str(self.root / 'absent-mount')])
        self.assertIsNone(self.relay.after_exit)

    async def test_queued_switch_relaunches_without_source_permissions_or_input(self):
        from harness_cli import auto_relay
        target = self.root / 'target'
        target.mkdir()
        policy = SimpleNamespace(refresh_needed=False, observer=SimpleNamespace(cwd=self.root))
        launches = []
        first = SimpleNamespace(error=None, after_exit={'action': 'switch', 'root': str(target), 'resume': True}, connect=None)
        second = SimpleNamespace(error=None, after_exit=None, connect=None)
        for relay in (first, second):
            relay.client = lambda port, args: (['codex', *args], {})
        server = mock.MagicMock()
        server.sockets = [SimpleNamespace(getsockname=lambda: ('127.0.0.1', 1))]
        context = mock.MagicMock()
        context.__aenter__ = mock.AsyncMock(return_value=server)
        context.__aexit__ = mock.AsyncMock(return_value=False)
        async def spawn(*args, **kwargs):
            launches.append(args)
            return SimpleNamespace(wait=mock.AsyncMock(return_value=0), returncode=0)
        with mock.patch.object(auto_relay, 'dependency', return_value=lambda *a, **kw: context), mock.patch.object(auto_relay, 'Relay', side_effect=[first, second]), mock.patch('asyncio.create_subprocess_exec', side_effect=spawn):
            result = await auto_relay.run('codex', ['--dangerously-bypass-approvals-and-sandbox', 'source prompt'], {}, policy)
        self.assertEqual(result, 0)
        self.assertEqual(launches[1], ('codex', '-c', 'check_for_update_on_startup=false', '--cd', str(target), 'resume'))
        self.assertEqual(policy.observer.cwd, target)
        self.assertTrue(policy.refresh_needed)

    async def test_queued_missing_project_prepares_then_launches_only_its_approved_brief(self):
        from harness_cli import auto_relay
        target = self.root / 'new project'
        policy = SimpleNamespace(refresh_needed=False, observer=None)
        launches = []
        first = SimpleNamespace(error=None, after_exit={'action': 'configure', 'root': str(target), 'command': 'init', 'arguments': ['--goal', 'Approved goal']}, connect=None)
        second = SimpleNamespace(error=None, after_exit=None, connect=None)
        for relay in (first, second):
            relay.client = lambda port, args: (['codex', *args], {})
        server = mock.MagicMock()
        server.sockets = [SimpleNamespace(getsockname=lambda: ('127.0.0.1', 1))]
        context = mock.MagicMock()
        context.__aenter__ = mock.AsyncMock(return_value=server)
        context.__aexit__ = mock.AsyncMock(return_value=False)
        async def spawn(*args, **kwargs):
            launches.append(args)
            if '--install-only' in args:
                target.mkdir()
            return SimpleNamespace(wait=mock.AsyncMock(return_value=0), returncode=0)
        with mock.patch.object(auto_relay, 'dependency', return_value=lambda *a, **kw: context), mock.patch.object(auto_relay, 'Relay', side_effect=[first, second]), mock.patch('asyncio.create_subprocess_exec', side_effect=spawn):
            self.assertEqual(await auto_relay.run('codex', ['--dangerously-bypass-approvals-and-sandbox', 'source prompt'], {}, policy), 0)
        self.assertIn('--install-only', launches[1])
        self.assertEqual(launches[1][-2:], ('--project', str(target)))
        self.assertEqual(launches[2][1:6], ('-c', 'check_for_update_on_startup=false', '--cd', str(target), '--'))
        command, arguments = management_relay.parse({'input': [{'type': 'text', 'text': launches[2][-1]}]})
        self.assertEqual((command, arguments), ('init', ['--project', str(target), '--goal', 'Approved goal']))

    async def test_no_foreign_root_or_credentials_in_local_command(self):
        self.controls.cli = mock.AsyncMock()
        with self.assertRaises(ValueError):
            await self.controls.execute('thread', 'turn', self.root, 'status', ['--project=/another'])
        message = await self.controls.execute('thread', 'turn', self.root, 'jev', ['login'])
        self.assertIn('Never paste API keys', message)
        self.controls.cli.assert_not_called()

    async def test_unconfirmed_removal_does_not_apply(self):
        self.controls.cli = mock.AsyncMock(return_value=json.dumps({'actions': [{'action': 'remove-file', 'path': '.harness/manifest.json'}], 'planDigest': 'preview'}))
        self.controls.choose = mock.AsyncMock(return_value='Back')
        result = await self.controls.execute('thread', 'turn', self.root, 'remove', [])
        self.assertIn('cancelled', result)
        self.assertEqual(self.controls.cli.call_count, 1)
        self.assertIn('--dry-run', self.controls.cli.call_args.args[1])

    async def test_init_menu_keeps_permissions_and_submits_only_after_confirmation(self):
        self.controls.choose = mock.AsyncMock(side_effect=['Init', 'Current project', 'Describe the project', 'Confirm'])
        self.controls.enter = mock.AsyncMock(return_value='A small analysis project')
        self.controls.cli = mock.AsyncMock(return_value='ready')
        self.controls.submit = mock.AsyncMock()
        value = self.request('/harness/')
        value['params'].update(model='selected-model', effort='high', approvalPolicy='on-request', sandboxPolicy={'type': 'readOnly'})
        self.assertTrue(await self.controls.intercept(value))
        await asyncio.gather(*list(self.controls.tasks.values()))
        request = self.controls.submit.call_args.args[0]
        self.assertEqual(request['model'], 'selected-model')
        self.assertEqual(request['effort'], 'high')
        self.assertEqual(request['sandboxPolicy'], {'type': 'readOnly'})
        self.assertEqual(request['approvalPolicy'], 'on-request')
        self.assertIn('A small analysis project', request['input'][0]['text'])
        self.assertEqual(self.sent[-1]['method'], 'turn/completed')
        self.controls.cli.assert_awaited_once()

    async def test_wizard_back_preserves_files_and_starts_no_model(self):
        self.controls.choose = mock.AsyncMock(side_effect=['Current project', 'Describe the project', 'Back', 'Back', 'Back'])
        self.controls.enter = mock.AsyncMock(return_value='Unused description')
        self.controls.cli = mock.AsyncMock()
        result = await self.controls.execute('thread', 'turn', self.root, 'init', [])
        self.assertIn('without configuring', result)
        self.controls.cli.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    async def test_new_project_queues_only_after_brief_confirmation(self):
        target = self.root / 'new project'
        self.controls.choose = mock.AsyncMock(side_effect=['Another directory', 'Describe the project', 'Confirm'])
        self.controls.enter = mock.AsyncMock(side_effect=[str(target), 'New project purpose'])
        self.controls.cli = mock.AsyncMock()
        result = await self.controls.execute('thread', 'turn', self.root, 'init', [])
        self.assertIn('/quit', result)
        self.assertEqual(self.relay.after_exit, {'action': 'configure', 'root': str(target), 'command': 'init', 'arguments': ['--goal', 'New project purpose']})
        self.assertFalse(target.exists())
        self.controls.cli.assert_not_called()

    async def test_existing_project_wizard_reviews_without_reset(self):
        (self.root / '.harness').mkdir()
        (self.root / '.harness/manifest.json').write_text('{}')
        self.controls.choose = mock.AsyncMock(side_effect=['Current project', 'Review and update', 'Use existing project evidence', 'Confirm'])
        result = await self.controls.execute('thread', 'turn', self.root, 'init', [])
        self.assertEqual(result['configuration'], (self.root, 'config', []))
        self.assertEqual((self.root / '.harness/manifest.json').read_text(), '{}')

    async def test_markdown_brief_is_relative_to_target_and_contents_not_in_command(self):
        target = self.root / 'target'
        target.mkdir()
        brief = target / 'project brief.md'
        brief.write_text('Private project description', encoding='utf-8')
        self.controls.choose = mock.AsyncMock(side_effect=['Another directory', 'Markdown file', 'Confirm'])
        self.controls.enter = mock.AsyncMock(side_effect=[str(target), 'project brief.md'])
        await self.controls.execute('thread', 'turn', self.root, 'init', [])
        self.assertEqual(self.relay.after_exit['arguments'], ['--goal-file', str(brief)])
        self.assertNotIn('Private project description', json.dumps(self.relay.after_exit))

    async def test_explicit_configuration_target_cannot_change_native_directory(self):
        other = self.root / 'other'
        other.mkdir()
        self.controls.cli = mock.AsyncMock()
        with self.assertRaisesRegex(ValueError, 'own conversation'):
            await self.controls.intercept(self.request('/harness/init --project ' + json.dumps(str(other)) + ' --goal "test"'))
        self.controls.cli.assert_not_called()

    async def test_explicit_target_does_not_select_parent_harness(self):
        (self.root / '.harness').mkdir()
        (self.root / '.harness/manifest.json').write_text('{}')
        nested = self.root / 'nested'
        nested.mkdir()
        self.call.return_value = {'thread': {'cwd': str(nested)}}
        self.controls.cli = mock.AsyncMock(return_value='ready')
        message = self.request('/harness/init --project ' + json.dumps(str(nested)) + ' --goal "nested project"')
        self.assertFalse(await self.controls.intercept(message))
        self.assertEqual(message['params']['cwd'], str(nested))
        self.assertEqual(self.controls.cli.call_args.args[0], nested)

    async def test_private_login_is_queued_without_chat_secret_or_cli_execution(self):
        self.controls.choose = mock.AsyncMock(side_effect=['Jev', 'Login'])
        self.controls.cli = mock.AsyncMock()
        result = await self.controls.execute('thread', 'turn', self.root, 'help', [])
        self.assertEqual(self.relay.after_exit['action'], 'jev')
        self.assertEqual(self.relay.after_exit['operation'], 'login')
        self.assertIn('Never paste credentials', result)
        self.controls.cli.assert_not_called()

    async def test_free_input_uses_native_text_field_and_rejects_control_characters(self):
        task = asyncio.create_task(self.controls.enter('thread', 'turn', 'Path'))
        await asyncio.sleep(0)
        request = self.sent[-1]
        self.assertIsNone(request['params']['questions'][0]['options'])
        await self.controls.intercept({'id': request['id'], 'result': {'answers': {'choice': {'answers': ['bad\0path']}}}})
        with self.assertRaises(ValueError):
            await task

    async def test_native_free_text_prefix_is_not_part_of_the_selected_path(self):
        task = asyncio.create_task(self.controls.enter('thread', 'turn', 'Path'))
        await asyncio.sleep(0)
        request = self.sent[-1]
        await self.controls.intercept({'id': request['id'], 'result': {'answers': {'choice': {'answers': ['user_note: /projects/project one']}}}})
        self.assertEqual(await task, '/projects/project one')


class ManagementFilesystemTests(unittest.TestCase):
    def setUp(self):
        token = presentation.JSON_MODE.set(False)
        self.addCleanup(presentation.JSON_MODE.reset, token)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        settings = tempfile.TemporaryDirectory()
        self.addCleanup(settings.cleanup)
        environment = mock.patch.dict(os.environ, {'HARNESS_STATE_HOME': str(Path(settings.name) / 'state'), 'CODEX_HOME': str(Path(settings.name) / 'codex-home')})
        environment.start()
        self.addCleanup(environment.stop)

    def test_real_removal_cleanup_preserves_foreign_content(self):
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))
        notes = self.root / '.agents/skills/project-harness/notes.txt'
        notes.write_text('User notes')
        report = lifecycle.remove_project(self.root, source_root=REPO, dry_run=False)
        result = project_cleanup.after_removal(self.root, report, requested=True)
        self.assertEqual(notes.read_text(), 'User notes')
        self.assertIn('.agents', result['retained'])
        self.assertFalse((self.root / '.harness').exists())

    def test_global_codex_home_is_never_a_cleanup_candidate(self):
        target = self.root / '.codex'
        target.mkdir()
        report = {'actions': [{'path': '.codex/agents/agent.toml'}]}
        with mock.patch.dict(os.environ, {'CODEX_HOME': str(target)}):
            self.assertEqual(project_cleanup.candidates(self.root, report), [])
        with mock.patch.dict(os.environ, {'CODEX_HOME': '.codex'}):
            self.assertEqual(project_cleanup.candidates(self.root, report), [])
        self.assertTrue(target.is_dir())

    def test_confirmed_removal_rejects_changes_since_its_preview(self):
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))
        preview = lifecycle.remove_project(self.root, source_root=REPO)
        pointer = self.root / 'AGENTS.md'
        pointer.write_bytes(pointer.read_bytes() + b'\nNew user instruction\n')
        with self.assertRaisesRegex(lifecycle.LifecycleError, 'changed after the preview'):
            lifecycle.remove_project(self.root, source_root=REPO, dry_run=False, expected_plan=preview['planDigest'])
        self.assertTrue((self.root / '.harness/manifest.json').is_file())
        self.assertIn(b'New user instruction', pointer.read_bytes())

    def test_cleanup_requires_confirmation_and_rejects_escape(self):
        target = self.root / '.harness'
        target.mkdir()
        report = {'state': 'removed', 'actions': [{'path': '.harness/manifest.json'}]}
        result = project_cleanup.after_removal(self.root, report, json_mode=True)
        self.assertTrue(result['confirmationRequired'])
        self.assertTrue(target.exists())
        with self.assertRaises(ValueError):
            project_cleanup.remove_empty(self.root, [{'path': '../other', 'device': 1, 'inode': 1}])

    def test_cleanup_rechecks_directory_identity(self):
        target = self.root / '.harness'
        target.mkdir()
        selected = project_cleanup.candidates(self.root, {'actions': [{'path': '.harness/manifest.json'}]})
        selected[0]['inode'] += 1
        self.assertEqual(project_cleanup.remove_empty(self.root, selected)['retained'], ['.harness'])

    def test_status_box_keeps_header_and_author_and_never_prints_raw_key(self):
        stream = io.StringIO()
        with mock.patch('sys.stdout', stream):
            dashboard.display({'state': 'unconfigured', 'features': {'jev': {'mode': 'shadow', 'keyAvailable': True, 'key': 'private-key'}}}, self.root, 'test-version')
        text = stream.getvalue()
        self.assertIn('Harness for Codex (test-version)', text)
        self.assertIn('by sholee-pt', text)
        self.assertNotIn('private-key', text)
        self.assertIn('not-measured', text)

    def test_settings_json_is_one_document_after_preference_change(self):
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))
        args = SimpleNamespace(command='settings', project=self.root, maintenance='suggest', adaptive=None,
                               prepare_hooks=False, json=True)
        token = presentation.JSON_MODE.set(True)
        try:
            stream = io.StringIO()
            with mock.patch('sys.stdout', stream):
                self.assertEqual(management.run(args, REPO), 0)
            value = json.loads(stream.getvalue())
            self.assertEqual(value['features']['maintenance']['mode'], 'suggest')
        finally:
            presentation.JSON_MODE.reset(token)

    def test_parser_only_reserves_qualified_single_line_commands(self):
        self.assertIsNone(management_relay.parse({'input': [{'type': 'text', 'text': 'Explain /harness/status'}]}))
        self.assertEqual(management_relay.parse({'input': [{'type': 'text', 'text': '/harness/switch "/with spaces"'}]}), ('switch', ['/with spaces']))
        for text in ('/harness/status\nremove', '/harness/unknown', '/harness/status "'):
            with self.assertRaises(ValueError):
                management_relay.parse({'input': [{'type': 'text', 'text': text}]})
