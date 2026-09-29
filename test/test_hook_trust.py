"""Native metadata trust is scoped, bounded, idempotent and independent of modes."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from harness_cli import hook_trust, maintenance, presentation

ROOT = Path(__file__).resolve().parents[1]


class HookTrustTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root, self.home = self.base / 'project', self.base / 'codex'
        self.root.mkdir()
        self.home.mkdir()
        self.path = self.home / 'hooks.json'
        self.config = self.home / 'config.toml'
        self.config.write_text('approval_policy = "on-request"\n', encoding='utf-8')
        self.foreign = {'type': 'command', 'command': 'unrelated-tool'}
        self.path.write_text(json.dumps({'hooks': {'Stop': [{'hooks': [self.foreign]}]}}))
        environment = mock.patch.dict(os.environ, {'CODEX_HOME': str(self.home), 'HARNESS_TOOL_HOME': ''})
        environment.start()
        self.addCleanup(environment.stop)
        maintenance.install_hooks(ROOT)
        self.command = maintenance.hook_command(ROOT)
        self.hooks = []
        for index, event in enumerate(maintenance.EVENTS):
            definition = maintenance.hook_definition(event, self.command)
            self.hooks.append({'key': 'owned-' + str(index), 'eventName': event[0].lower() + event[1:], 'handlerType': 'command',
                'command': self.command, 'source': 'user', 'sourcePath': str(self.path), 'isManaged': False,
                'async': False, 'matcher': None, 'pluginId': None, 'statusMessage': None,
                'timeoutSec': definition['timeout'], 'additionalContextLimit': definition.get('additionalContextLimit'),
                'currentHash': 'native-hash-' + str(index), 'trustStatus': 'untrusted', 'enabled': True})
        self.hooks.append({**self.hooks[0], 'key': 'foreign', 'command': 'unrelated-tool', 'enabled': False})
        self.requirements, self.features = None, {}
        self.calls, self.edits, self.closed = [], [], False
        server = mock.Mock()
        server.call.side_effect = self.call
        server.close.side_effect = lambda: setattr(self, 'closed', True)
        patch = mock.patch.object(hook_trust, 'MetadataServer', return_value=server)
        self.factory = patch.start()
        self.addCleanup(patch.stop)
        self.server = server

    def call(self, method, params, timeout):
        self.calls.append(method)
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 20)
        if method == 'configRequirements/read':
            self.assertIsNone(params)
            return {'requirements': self.requirements}
        if method == 'config/read':
            return {'config': {'features': self.features}, 'layers': [
                {'name': {'type': 'user', 'file': str(self.config)}, 'version': 'observed-version'}]}
        if method == 'hooks/list':
            self.assertEqual(params, {'cwds': [str(self.root)]})
            return {'data': [{'cwd': str(self.root), 'hooks': copy.deepcopy(self.hooks), 'errors': []}]}
        if method == 'config/batchWrite':
            self.assertEqual(params['filePath'], str(self.config))
            self.assertEqual(params['expectedVersion'], 'observed-version')
            self.assertTrue(params['reloadUserConfig'])
            self.edits.append(copy.deepcopy(params['edits']))
            edit, = params['edits']
            self.assertEqual((edit['keyPath'], edit['mergeStrategy']), ('hooks.state', 'upsert'))
            for hook in self.hooks:
                if hook['key'] in edit['value']:
                    self.assertEqual(edit['value'][hook['key']], {'trusted_hash': hook['currentHash'], 'enabled': True})
                    hook.update(trustStatus='trusted', enabled=True)
            return {'status': 'ok'}
        self.fail('Unexpected RPC: ' + method)

    def trust(self):
        return hook_trust.trust(['native-codex'], self.root, self.path, self.command, presentation.Progress('test', stream=io.StringIO()))

    def test_only_owned_hashes_are_trusted_and_repeated_setup_has_no_write(self):
        before = self.path.read_bytes(), self.config.read_bytes()
        self.hooks[0]['enabled'] = False
        self.assertEqual(self.trust(), {'status': 'trusted', 'count': 7, 'changed': True})
        self.assertEqual(len(self.edits[0][0]['value']), 7)
        self.assertNotIn('foreign', self.edits[0][0]['value'])
        self.assertEqual(self.hooks[-1]['trustStatus'], 'untrusted')
        self.assertFalse(self.hooks[-1]['enabled'])
        self.assertFalse(self.trust()['changed'])
        self.assertEqual(len(self.edits), 1)
        self.assertEqual(before, (self.path.read_bytes(), self.config.read_bytes()))
        self.assertTrue(self.closed)
        self.assertFalse(any(name.startswith(('thread/', 'turn/')) for name in self.calls))

    def test_manual_registers_without_contacting_codex_or_touching_trust(self):
        result = hook_trust.prepare(ROOT, self.root, mode='manual')
        self.assertEqual(result['status'], 'manual-review-required')
        self.factory.assert_not_called()
        self.assertIn(self.foreign, json.loads(self.path.read_text())['hooks']['Stop'][0]['hooks'])

    def test_admin_and_explicit_native_hook_restrictions_are_never_overridden(self):
        for requirements, features in (({'allowManagedHooksOnly': True}, {}), ({'featureRequirements': {'hooks': False}}, {}),
                                       (None, {'hooks': False}), (None, {'codex_hooks': False})):
            with self.subTest(requirements=requirements, features=features):
                self.requirements, self.features = requirements, features
                with self.assertRaisesRegex(ValueError, 'not overridden'):
                    self.trust()
        self.assertEqual(self.edits, [])

    def test_customized_definitions_and_replaced_ownership_are_not_auto_trusted(self):
        original = self.path.read_bytes()
        receipt = self.home / 'harness-maintenance-hooks.json'
        saved = receipt.read_bytes()
        for change in ('timeout', 'matcher', 'receipt-command', 'duplicate'):
            with self.subTest(change=change):
                value = json.loads(original)
                group = value['hooks']['SessionStart'][0]
                if change == 'timeout':
                    group['hooks'][0]['timeout'] = 100
                elif change == 'matcher':
                    group['matcher'] = '*'
                elif change == 'duplicate':
                    group['hooks'].append(copy.deepcopy(group['hooks'][0]))
                else:
                    receipt.write_text(json.dumps({'owner': 'harness-maintenance-v1', 'command': 'another-command'}))
                self.path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    self.trust()
                self.path.write_bytes(original)
                receipt.write_bytes(saved)
        self.factory.assert_not_called()

    def test_missing_foreign_or_ambiguous_native_metadata_is_rejected(self):
        original = copy.deepcopy(self.hooks)
        for field, value in (('sourcePath', str(self.home / 'other.json')), ('source', 'project'),
                             ('eventName', 'Other'), ('key', 'owned-1'), ('command', 'changed'),
                             ('async', True), ('isManaged', True), ('trustStatus', 'unknown')):
            with self.subTest(field=field):
                self.hooks = copy.deepcopy(original)
                self.hooks[0][field] = value
                with self.assertRaises(ValueError):
                    self.trust()
        self.assertEqual(self.edits, [])

    def test_concurrent_hook_edit_aborts_before_native_write(self):
        def call(method, params, timeout):
            result = self.call(method, params, timeout)
            if method == 'hooks/list':
                self.path.write_bytes(self.path.read_bytes() + b'\n')
            return result
        self.server.call.side_effect = call
        with self.assertRaisesRegex(ValueError, 'changed during setup'):
            self.trust()
        self.assertEqual(self.edits, [])
        self.assertTrue(self.path.read_bytes().endswith(b'\n\n'))

    def test_native_compare_and_swap_failure_preserves_error_without_retry(self):
        def call(method, params, timeout):
            if method == 'config/batchWrite':
                raise ValueError('configuration version changed')
            return self.call(method, params, timeout)
        self.server.call.side_effect = call
        with self.assertRaisesRegex(ValueError, 'version changed'):
            self.trust()
        self.assertEqual(self.server.call.call_count, 4)
        self.assertTrue(self.closed)

    def test_verification_refuses_changed_hash_or_unconfirmed_write(self):
        for failure in ('new-hash', 'disabled', 'overridden'):
            with self.subTest(failure=failure):
                for hook in self.hooks:
                    hook['trustStatus'] = 'untrusted'
                def call(method, params, timeout):
                    result = self.call(method, params, timeout)
                    if method == 'config/batchWrite':
                        if failure == 'new-hash':
                            self.hooks[0]['currentHash'] += '-changed'
                        elif failure == 'disabled':
                            self.hooks[0]['enabled'] = False
                        else:
                            return {'status': 'okOverridden'}
                    return result
                self.server.call.side_effect = call
                with self.assertRaises(ValueError):
                    self.trust()

    def test_unsupported_or_timed_out_codex_returns_manual_guidance_without_model_fallback(self):
        for error in (ValueError('Unsupported RPC'), TimeoutError('timed out')):
            with self.subTest(error=error), mock.patch('harness_cli.project._codex_command', return_value=['native-codex']), \
                    mock.patch.object(hook_trust, 'trust', side_effect=error), mock.patch('sys.stdout', io.StringIO()):
                result = hook_trust.prepare(ROOT, self.root)
                self.assertEqual(result['status'], 'manual-review-required')
                self.assertIn('/hooks', result['guidance'])
                self.assertIn(str(error), result['warning'])

    def test_metadata_client_rejects_execution_or_approval_requests(self):
        client = object.__new__(hook_trust.MetadataServer)
        client.send = mock.Mock()
        with self.assertRaisesRegex(ValueError, 'Unexpected Codex request'):
            client.answer(1, 'item/commandExecution/requestApproval', {})
        self.assertIn('error', client.send.call_args.args[0])
