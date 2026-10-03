"""Regression checks for the isolated probe, not proof of native TUI compatibility."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from integration import auto_relay_probe as probe


def catalog():
    return {'data': [{'id': name, 'model': name, 'displayName': name, 'isDefault': index == 1,
        'defaultReasoningEffort': 'medium', 'supportedReasoningEfforts': [
            {'reasoningEffort': effort} for effort in ('low', 'medium', 'high')]}
        for index, name in enumerate(('gpt-5.6-luna', 'gpt-5.6-sol', 'gpt-6-astra'))]}


def request(thread='main', model=probe.ALIAS, prompt='New task: Fix a typo in README.'):
    return {'threadId': thread, 'model': model, 'effort': 'medium',
            'input': [{'type': 'text', 'text': prompt}], 'approvalPolicy': 'on-request',
            'sandboxPolicy': {'type': 'readOnly'}, 'futureField': {'keep': True}}


class AutoRelayProbeTests(unittest.TestCase):
    def test_settings_gate_recognizes_the_actual_current_values_question(self):
        from harness_cli.management_wizard import settings
        controls = SimpleNamespace(
            cli=mock.AsyncMock(return_value=json.dumps({'features': {
                'maintenance': {'mode': 'suggest'}, 'routing': {'enabled': False}}})),
            choose=mock.AsyncMock(return_value='Back'),
            queued_action=lambda: 'No action queued.')
        self.assertIsNone(asyncio.run(settings(controls, 'thread', 'turn', Path('/fixture/project'))))
        question, options = controls.choose.call_args.args[2:]
        screen = question + '\n' + '\n'.join(label for label, description in options)
        self.assertTrue(probe.settings_picker_ready(screen))
        self.assertFalse(probe.settings_picker_ready('Project preferences\nBack'))
        self.assertFalse(probe.settings_picker_ready(screen.replace('Adaptive Auto:', '')))

    def test_auto_state_is_thread_local_and_survives_routed_model_echo(self):
        policy = probe.Policy()
        original = catalog()
        augmented = policy.model_list(original)
        self.assertEqual(augmented['data'][1:], original['data'])
        first = request()
        before = copy.deepcopy(first)
        routed = policy.turn(first, 10)
        self.assertEqual(first, before)
        self.assertEqual((routed['model'], routed['effort']), ('gpt-5.6-luna', 'low'))
        for key in ('approvalPolicy', 'sandboxPolicy', 'futureField', 'input', 'threadId'):
            self.assertEqual(routed[key], first[key])
        helper = request('helper', None)
        self.assertEqual(policy.turn(helper, 11), helper)
        second = request(model=routed['model'], prompt='New task: Investigate a distributed concurrency race.')
        self.assertEqual(policy.turn(second, 12)['model'], 'gpt-6-astra')
        self.assertTrue(policy.decisions[-1]['auto'])
        self.assertEqual(policy.decisions[-1]['threadId'], 'main')
        self.assertNotIn('helper', policy.contexts)

    def test_explicit_manual_choice_disables_auto_without_changing_other_fields(self):
        policy = probe.Policy()
        policy.model_list(catalog())
        policy.turn(request())
        manual = request(model='gpt-5.6-sol')
        manual['collaborationMode'] = {'mode': 'default', 'settings': {
            'model': 'gpt-5.6-sol', 'reasoning_effort': 'medium', 'developer_instructions': None}}
        policy.settings(manual)
        self.assertEqual(policy.turn(manual), manual)
        self.assertFalse(policy.decisions[-1]['auto'])
        policy.settings({'threadId': 'main', 'effort': 'high'})
        self.assertFalse(policy.auto['main'])
        policy.settings({'threadId': 'main', 'model': probe.ALIAS})
        self.assertTrue(policy.auto['main'])

    def test_virtual_default_write_preserves_permissions_and_batch_metadata(self):
        policy = probe.Policy()
        policy.default_model = 'gpt-5.6-sol'
        params = {'edits': [{'keyPath': 'model', 'value': probe.ALIAS, 'mergeStrategy': 'replace'},
            {'keyPath': 'approval_policy', 'value': 'on-request', 'mergeStrategy': 'replace'}],
            'expectedVersion': 'untouched', 'filePath': '/isolated/config.toml'}
        before = copy.deepcopy(params)
        expected = copy.deepcopy(params)
        expected['edits'][0]['value'] = 'gpt-5.6-sol'
        self.assertEqual(policy.config_write('config/batchWrite', params), expected)
        self.assertEqual(params, before)
        manual = {'keyPath': 'model', 'value': 'gpt-6-astra', 'mergeStrategy': 'replace'}
        self.assertEqual(policy.config_write('config/value/write', manual), manual)
        policy.default_model = None
        with self.assertRaises(ValueError):
            policy.config_write('config/batchWrite', params)

    def test_foreground_correlation_rejects_background_and_old_turn_completion(self):
        prompt = request()['input'][0]['text']
        main = {'threadId': 'main', 'turnId': 'turn-2', 'inputSha256': probe.input_digest(prompt), 'model': 'real'}
        helper = dict(main, threadId='helper', model=None)
        relay = SimpleNamespace(policy=SimpleNamespace(decisions=[main, helper]), events=[
            {'method': 'turn/completed', 'threadId': 'main', 'turnId': 'turn-1'},
            {'method': 'turn/completed', 'threadId': 'helper', 'turnId': 'turn-2'}])
        record = {'threadId': 'main', 'inputSha256': main['inputSha256'], 'model': 'real'}
        provider = SimpleNamespace(records=[record, dict(record, threadId='helper')])
        self.assertIsNone(probe.turn_evidence(relay, provider, 'main', prompt))
        relay.events.append({'method': 'turn/completed', 'threadId': 'main', 'turnId': 'turn-2', 'status': 'completed'})
        self.assertEqual(probe.turn_evidence(relay, provider, 'main', prompt), (dict(main, turnStatus='completed'), record))
        provider.records = [dict(record, threadId='helper')]
        self.assertIsNone(probe.turn_evidence(relay, provider, 'main', prompt))

    def test_footer_excludes_history_and_handles_trailing_empty_terminal_rows(self):
        screen = '• Model changed to codex-auto-harness\n› old task\n• reply\n› Ask Codex to do anything\n\n  gpt-5.6-luna low\n' + '\n' * 15
        self.assertEqual(probe.footer_lines(screen), ['gpt-5.6-luna low'])
        self.assertEqual(probe.footer_lines('• Auto gpt-5.6-luna low'), [])

    def test_startup_only_handles_observed_model_announcement(self):
        terminal = object.__new__(probe.Terminal)
        relay = SimpleNamespace(thread_ids=[])
        terminal.snapshot = mock.Mock()
        terminal.select = mock.Mock()

        def wait(predicate):
            self.assertFalse(predicate('Approve this command?'))
            terminal.select.assert_not_called()
            self.assertFalse(predicate('Meet GPT-6 Sol\n1. Try new model\n2. Use existing model'))
            relay.thread_ids.append('main')
            self.assertTrue(predicate('› Ask Codex to do anything'))

        terminal.wait = wait
        self.assertEqual(terminal.startup(relay), ['Use existing model'])
        terminal.select.assert_called_once_with('Use existing model')


if __name__ == '__main__':
    unittest.main()
