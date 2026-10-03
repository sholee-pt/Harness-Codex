"""Native management navigation, unchanged defaults and after-exit reservations."""
import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from harness_cli import management_relay, management_wizard
import test_management_controls as fixtures


class ManagementNavigation(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.LocalControls.setUp
    asyncTearDown = fixtures.LocalControls.asyncTearDown
    request = fixtures.LocalControls.request

    def preferences(self):
        return json.dumps({'features': {'maintenance': {'mode': 'suggest'}, 'routing': {'enabled': True},
                                       'hooks': {'state': 'registered', 'recordedTrustMatches': 2}}})

    async def test_group_back_returns_to_parent_and_keeps_qualified_commands(self):
        self.controls.choose = mock.AsyncMock(side_effect=['Settings', 'Jev', 'Back', 'Back', 'Diagnostics', 'Status'])
        self.controls.cli = mock.AsyncMock(return_value='Project status')
        result = await self.controls.execute('thread', 'turn', self.root, 'help', [])
        self.assertIn('Project status', result)
        prompts = self.controls.choose.call_args_list
        self.assertEqual([label for label, _ in prompts[0].args[3]], ['Project', 'Settings', 'Diagnostics', 'Tools', 'Help', 'Back'])
        self.assertTrue(prompts[1].args[2].endswith('\nSettings'))
        self.assertTrue(prompts[3].args[2].endswith('\nSettings'))
        for name in management_relay.COMMANDS:
            self.assertEqual(management_relay.parse(self.request('/harness/' + name)['params']), (name, []))
        self.controls.cli.assert_awaited_once_with(self.root, ['status'], timeout=60)

    async def test_settings_keep_current_is_default_and_makes_no_write(self):
        self.controls.cli = mock.AsyncMock(return_value=self.preferences())
        self.controls.choose = mock.AsyncMock(return_value='Keep current')
        result = await self.controls.execute('thread', 'turn', self.root, 'settings', [])
        self.assertIn('Maintenance: suggest', result)
        self.assertIn('Adaptive Auto: on', result)
        self.assertIn(str(self.root), result)
        self.assertEqual(self.controls.choose.call_args.args[3][0][0], 'Keep current')
        self.controls.cli.assert_awaited_once_with(self.root, ['settings', '--json'])

    async def test_settings_back_edits_the_value_before_explicit_apply(self):
        self.controls.cli = mock.AsyncMock(side_effect=[self.preferences(), 'Changed'])
        self.controls.choose = mock.AsyncMock(side_effect=['Maintenance', 'auto', 'Back', 'off', 'Apply change'])
        result = await self.controls.execute('thread', 'turn', self.root, 'settings', [])
        self.assertIn('suggest → off', result)
        self.assertIn('suggest → auto', self.controls.choose.call_args_list[2].args[2])
        self.controls.cli.assert_has_awaits([mock.call(self.root, ['settings', '--json']), mock.call(self.root, ['settings', '--maintenance', 'off'])])
        self.assertEqual(self.controls.cli.await_count, 2)

    async def test_settings_nested_back_returns_to_preferences(self):
        self.controls.cli = mock.AsyncMock(return_value=self.preferences())
        self.controls.choose = mock.AsyncMock(side_effect=['Adaptive Auto', 'Back', 'Keep current'])
        result = await self.controls.execute('thread', 'turn', self.root, 'settings', [])
        self.assertIn('Current preferences retained', result)
        self.assertEqual(self.controls.cli.await_count, 1)

    async def test_queue_conflict_defaults_to_keep_and_requires_explicit_replacement(self):
        original = {'action': 'configure', 'root': str(self.root), 'command': 'init', 'arguments': ['--goal', 'Original purpose']}
        self.relay.after_exit = original
        self.controls.choose = mock.AsyncMock(side_effect=['Keep queued action', 'Replace queued action'])
        self.assertFalse(await self.controls.queue('thread', 'turn', {'action': 'update'}))
        self.assertIs(self.relay.after_exit, original)
        self.assertEqual(self.controls.choose.call_args.args[3][0][0], 'Keep queued action')
        self.assertIn(str(self.root), self.controls.choose.call_args.args[2])
        self.assertTrue(await self.controls.queue('thread', 'turn', {'action': 'update'}))
        self.assertEqual(self.relay.after_exit, {'action': 'update'})

    async def test_qualified_cancel_never_cancels_another_kind_of_action(self):
        self.controls.cli = mock.AsyncMock()
        for action in ({'action': 'jev', 'operation': 'logout', 'root': str(self.root)}, {'action': 'configure', 'root': str(self.root)}, {'action': 'uninstall'}):
            self.relay.after_exit = action
            for command in ('switch', 'update'):
                result = await self.controls.execute('thread', 'turn', self.root, command, ['--cancel'])
                self.assertIs(self.relay.after_exit, action)
                self.assertIn('No ' + command + ' action was cancelled', result)
        for command in ('switch', 'update'):
            self.relay.after_exit = {'action': command}
            await self.controls.execute('thread', 'turn', self.root, command, ['--cancel'])
            self.assertIsNone(self.relay.after_exit)
        self.controls.cli.assert_not_called()

    async def test_later_preserves_and_displays_an_existing_update(self):
        self.relay.after_exit = {'action': 'update'}
        self.controls.cli = mock.AsyncMock(return_value=json.dumps({'updateAvailable': True}))
        self.controls.choose = mock.AsyncMock(return_value='Later')
        with mock.patch.object(management_relay.ui, 'update_report'):
            result = await self.controls.execute('thread', 'turn', self.root, 'update', [])
        self.assertEqual(self.relay.after_exit, {'action': 'update'})
        self.assertIn('No new update', result)
        self.assertIn('After exit: Update Harness', result)

    async def test_status_displays_the_current_queue_without_executing_it(self):
        self.relay.after_exit = {'action': 'jev', 'operation': 'login', 'root': str(self.root)}
        self.controls.cli = mock.AsyncMock(return_value='Project status')
        result = await self.controls.execute('thread', 'turn', self.root, 'status', [])
        self.assertIn('Private Jev login', result)
        self.assertIn(str(self.root), result)
        self.assertEqual(self.relay.after_exit['operation'], 'login')

    async def test_tools_queue_review_cancels_the_displayed_kind_only(self):
        for action in ('configure', 'jev', 'uninstall', 'switch', 'update'):
            self.relay.after_exit = {'action': action, 'root': str(self.root)}
            self.controls.choose = mock.AsyncMock(side_effect=['Queued action', 'Cancel queued action'])
            result = await management_wizard.tools(self.controls, 'thread', 'turn', self.root, 'tool')
            self.assertIsNone(self.relay.after_exit)
            self.assertIn('Queued ' + action + ' action cancelled', result)

    async def test_private_login_preserves_existing_action_when_replacement_is_declined(self):
        self.relay.after_exit = {'action': 'update'}
        self.controls.choose = mock.AsyncMock(side_effect=['Login', 'Keep queued action'])
        self.controls.cli = mock.AsyncMock()
        result = await management_wizard.tools(self.controls, 'thread', 'turn', self.root, 'jev')
        self.assertEqual(self.relay.after_exit, {'action': 'update'})
        self.assertIn('retained', result)
        self.controls.cli.assert_not_called()

    async def test_confirm_back_retains_the_project_description(self):
        self.controls.choose = mock.AsyncMock(side_effect=['Current project', 'Describe the project', 'Back', 'Keep entered value', 'Confirm'])
        self.controls.enter = mock.AsyncMock(return_value='Reusable description')
        result = await self.controls.execute('thread', 'turn', self.root, 'init', [])
        self.assertEqual(result['configuration'], (self.root, 'init', ['--goal', 'Reusable description']))
        self.controls.enter.assert_awaited_once()
        self.assertIn('Reusable description', self.controls.choose.call_args_list[3].args[2])

    async def test_back_through_project_steps_retains_path_and_brief(self):
        target = self.root / 'new target'
        self.controls.choose = mock.AsyncMock(side_effect=['Another directory', 'Describe the project', 'Back', 'Back', 'Back',
                                                          'Keep entered value', 'Keep entered brief', 'Confirm'])
        self.controls.enter = mock.AsyncMock(side_effect=[str(target), 'Saved target purpose'])
        result = await self.controls.execute('thread', 'turn', self.root, 'init', [])
        self.assertIn('queued', result)
        self.assertEqual(self.relay.after_exit['root'], str(target))
        self.assertEqual(self.relay.after_exit['arguments'], ['--goal', 'Saved target purpose'])
        self.assertEqual(self.controls.enter.await_count, 2)
        self.assertFalse(target.exists())

    async def test_external_source_name_back_revisits_the_retained_path(self):
        self.controls.choose = mock.AsyncMock(side_effect=['Add external source', 'Keep entered value'])
        self.controls.enter = mock.AsyncMock(side_effect=['../library', ':back', 'library'])
        self.controls.cli = mock.AsyncMock(return_value='Attached')
        result = await management_wizard.tools(self.controls, 'thread', 'turn', self.root, 'graft')
        self.assertEqual(result, 'Attached')
        self.assertIn('../library', self.controls.choose.call_args.args[2])
        self.controls.cli.assert_awaited_once_with(self.root, ['graft', 'add', str(self.root / '../library'), '--name', 'library'], timeout=180)

    async def test_switch_confirmation_back_preserves_the_entered_path(self):
        target = self.root / 'other'
        target.mkdir()
        self.call.return_value = {'data': []}
        self.controls.choose = mock.AsyncMock(side_effect=['Another directory', 'Back', 'Keep entered value', 'New conversation'])
        self.controls.enter = mock.AsyncMock(return_value=str(target))
        await self.controls.switch('thread', 'turn', self.root, [])
        self.controls.enter.assert_awaited_once()
        self.assertEqual(self.relay.after_exit, {'action': 'switch', 'root': str(target), 'resume': False})

    async def test_management_errors_are_failed_turns_and_do_not_clear_the_queue(self):
        self.relay.after_exit = {'action': 'update'}
        for error in (ValueError('Local validation failed'), RuntimeError('Local operation failed')):
            self.controls.execute = mock.AsyncMock(side_effect=error)
            await self.controls.handle(10, 'thread', 'turn', self.root, 'status', [])
            completed = self.sent[-1]['params']['turn']
            self.assertEqual(completed['status'], 'failed')
            self.assertEqual(completed['error']['message'], str(error))
            self.assertEqual(self.relay.after_exit, {'action': 'update'})

    async def test_missing_submission_fails_before_configuration_changes(self):
        self.controls.execute = mock.AsyncMock(return_value={'configuration': (self.root, 'init', [])})
        self.controls.configuration = mock.AsyncMock()
        await self.controls.handle(10, 'thread', 'turn', self.root, 'init', [], self.request('/harness/init')['params'])
        self.assertEqual(self.sent[-1]['params']['turn']['status'], 'failed')
        self.controls.configuration.assert_not_called()

    async def test_repeated_interrupt_during_process_creation_reaps_the_child(self):
        (self.root / 'harness.py').write_text('import time\ntime.sleep(60)\n')
        self.controls.source = self.root
        started, release = asyncio.Event(), asyncio.Event()
        create_process, processes = asyncio.create_subprocess_exec, []
        async def delayed(*args, **kwargs):
            process = await create_process(*args, **kwargs)
            processes.append(process)
            started.set()
            await release.wait()
            return process
        with mock.patch.object(asyncio, 'create_subprocess_exec', side_effect=delayed):
            task = asyncio.create_task(self.controls.cli(self.root, ['status']))
            try:
                await asyncio.wait_for(started.wait(), 3)
                for _ in range(3):
                    task.cancel()
                    await asyncio.sleep(0)
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
                self.assertIsNotNone(processes[0].returncode)
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)
                for process in processes:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()

    @unittest.skipUnless(os.name == 'posix', 'POSIX management process groups')
    async def test_repeated_interrupt_during_cleanup_preserves_cancellation(self):
        reading, stopping, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        process = SimpleNamespace(pid=999999, returncode=None)
        async def read(size):
            reading.set()
            await release.wait()
            return b''
        async def wait():
            process.returncode = 0
            return 0
        process.stdout = SimpleNamespace(read=read)
        process.wait = mock.AsyncMock(side_effect=wait)
        with mock.patch.object(asyncio, 'create_subprocess_exec', return_value=process), \
             mock.patch.object(management_relay.os, 'killpg', side_effect=lambda *args: stopping.set()):
            task = asyncio.create_task(self.controls.cli(self.root, ['status']))
            await asyncio.wait_for(reading.wait(), 1)
            task.cancel()
            await asyncio.wait_for(stopping.wait(), 1)
            for _ in range(3):
                task.cancel()
                await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
        self.assertEqual(process.returncode, 0)
        self.assertTrue(process.wait.await_count)

    async def test_process_creation_failure_keeps_its_original_cause(self):
        error = FileNotFoundError('Missing management interpreter')
        with mock.patch.object(asyncio, 'create_subprocess_exec', side_effect=error):
            with self.assertRaises(FileNotFoundError) as caught:
                await self.controls.cli(self.root, ['status'])
        self.assertIs(caught.exception, error)


if __name__ == '__main__':
    unittest.main()
