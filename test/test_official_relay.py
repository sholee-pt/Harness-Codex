"""Published updates and inference-only protocol adaptation without paid requests."""
import copy
import asyncio
import io
import json
import os
import hashlib
from pathlib import Path
import subprocess
import shutil
import sys
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from harness_cli import auto_relay as relay, codex_entry as entry, official_codex as official, release_updates as updates
from harness_cli import codex_integration as integration, distribution as dist, integration_path, native_package
from test_cli_distribution import source


def catalog():
    return {'data': [{'id': model, 'model': model, 'displayName': model, 'hidden': False,
        'defaultReasoningEffort': 'medium', 'isDefault': model == 'gpt-5.6-sol',
        'supportedReasoningEfforts': [{'reasoningEffort': effort, 'description': effort} for effort in ['low', 'medium', 'high']]}
        for model in ['gpt-5.6-luna', 'gpt-5.6-sol', 'gpt-6-astra']], 'nextCursor': None}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.saved = []
        self.policy = relay.Policy(profiles={'fast': ['gpt-5.6-luna'], 'deep': ['gpt-6-astra']}, remember=lambda *args: self.saved.append(args))
        self.policy.model_list(catalog())
        self.policy.response({'result': {'config': {'model': 'gpt-5.6-sol', 'model_reasoning_effort': 'high'}}}, 'config/read', {})

    def test_catalog_keeps_real_models_and_hides_display_aliases(self):
        original = catalog()
        result = self.policy.model_list(original)
        self.assertEqual(original, catalog())
        self.assertEqual(result['data'][0]['displayName'], 'Auto')
        self.assertEqual([x for x in result['data'][1:] if not x['hidden']], original['data'])
        with self.assertRaisesRegex(ValueError, 'complete'):
            self.policy.model_list({**original, 'nextCursor': 'more'})

    def test_routing_changes_only_inference_fields_and_keeps_auto_footer(self):
        params = {'threadId': 't1', 'model': relay.ALIAS, 'effort': 'medium',
            'input': [{'type': 'text', 'text': 'New task: Fix a typo in README.'}],
            'sandboxPolicy': {'type': 'readOnly'}, 'approvalPolicy': 'on-request', 'unknownFuture': {'keep': True},
            'collaborationMode': {'mode': 'default', 'settings': {'model': relay.ALIAS, 'reasoning_effort': 'medium', 'developer_instructions': 'owned'}}}
        before = copy.deepcopy(params)
        result = self.policy.request('turn/start', params)
        self.assertEqual(params, before)
        self.assertEqual((result['model'], result['effort']), ('gpt-5.6-luna', 'low'))
        for key in ['input', 'sandboxPolicy', 'approvalPolicy', 'unknownFuture']:
            self.assertEqual(result[key], before[key])
        event = {'method': 'thread/settings/updated', 'params': {'threadId': 't1', 'threadSettings': {'model': result['model'], 'effort': 'low'}}}
        displayed = self.policy.response(event, None, {})['params']['threadSettings']
        self.assertIn('gpt-5.6-luna', displayed['model'])
        self.assertEqual(displayed['effort'], 'low')
        params['input'][0]['text'] = 'New task: Investigate a distributed concurrency race and design a cross-service architecture migration.'
        routed = self.policy.request('turn/start', params)
        self.assertEqual((routed['model'], routed['effort']), ('gpt-6-astra', 'high'))

    def test_successful_manual_selection_survives_resume_and_does_not_affect_other_threads(self):
        params = {'threadId': 't1', 'model': relay.ALIAS}
        self.policy.response({'error': {'message': 'rejected'}}, 'thread/settings/update', params)
        self.assertFalse(self.policy.enabled('t1'))
        self.policy.response({'result': {}}, 'thread/settings/update', params)
        self.assertTrue(self.policy.enabled('t1'))
        self.policy.settings({'threadId': 't2', 'model': 'gpt-5.6-sol'})
        self.assertFalse(self.policy.enabled('t2'))
        resumed = relay.Policy(session_modes=dict(self.saved))
        resumed.model_list(catalog())
        resumed.response({'result': {'thread': {'id': 't1'}, 'model': 'gpt-5.6-sol'}}, 'thread/resume', {'model': 'gpt-5.6-sol'})
        self.assertTrue(resumed.enabled('t1'))

    def test_config_alias_is_never_persisted_and_other_edits_pass_unchanged(self):
        params = {'edits': [{'keyPath': 'model', 'value': relay.ALIAS},
            {'keyPath': 'model_reasoning_effort', 'value': 'medium'}, {'keyPath': 'sandbox_mode', 'value': 'read-only'}]}
        before = copy.deepcopy(params)
        result = self.policy.request('config/batchWrite', params)
        self.assertEqual(params, before)
        self.assertEqual(result['edits'], [{'keyPath': 'sandbox_mode', 'value': 'read-only'}])

    def test_large_or_image_only_input_is_preserved_without_virtual_model_leak(self):
        for content in ([{'type': 'image', 'url': 'fixture'}], [{'type': 'text', 'text': 'x' * 40000}]):
            params = {'threadId': 't1', 'model': relay.ALIAS, 'input': content}
            result = self.policy.request('turn/start', params)
            self.assertEqual(result['input'], content)
            self.assertFalse(result['model'].startswith(relay.ALIAS))

    def test_unknown_methods_and_server_approval_packets_are_preserved(self):
        params = {'cwd': '/project', 'approvalPolicy': 'never', 'unknown': {'model': 'leave this field'}}
        self.assertEqual(self.policy.request('future/method', params), params)
        packet = {'id': 1, 'method': 'item/commandExecution/requestApproval', 'params': params}
        self.assertEqual(self.policy.response(copy.deepcopy(packet), None, {}), packet)
        self.assertEqual(relay.server_arguments(['-c', 'approval_policy="on-request"', '--disable', 'test', 'resume', '--last']),
                         ['-c', 'approval_policy="on-request"', '--disable', 'test'])

    def test_catalog_replacement_revalidates_auto_and_manual_without_replaying(self):
        self.policy.seed('t1', {'model': 'gpt-5.6-sol', 'reasoningEffort': 'high'})
        self.policy.auto['t1'] = True
        future = {'data': [{'model': 'new-model', 'isDefault': True, 'defaultReasoningEffort': 'adaptive',
            'supportedReasoningEfforts': [{'reasoningEffort': 'adaptive'}]}], 'nextCursor': None}
        self.policy.model_list(future)
        params = {'threadId': 't1', 'input': [{'type': 'text', 'text': 'Continue.'}], 'model': 'gpt-5.6-sol', 'effort': 'high'}
        result = self.policy.request('turn/start', params)
        self.assertEqual((result['model'], result['effort']), ('new-model', 'adaptive'))
        self.assertTrue(self.policy.notices)
        self.assertEqual(result['input'], params['input'])
        self.policy.auto['t1'] = False
        with self.assertRaisesRegex(relay.SelectionRequired, '/model'):
            self.policy.request('turn/start', params)
        self.policy.model_list({'data': [], 'nextCursor': None})
        with self.assertRaises(relay.SelectionRequired):
            self.policy.request('turn/start', {**params, 'model': relay.ALIAS})

    def test_resume_model_and_effort_changes_preserve_all_other_settings(self):
        self.policy.auto['t1'] = True
        self.policy.seed('t1', {'model': 'removed', 'reasoningEffort': 'retired-effort'})
        params = {'threadId': 't1', 'config': {'approval_policy': 'on-request'}, 'cwd': '/project'}
        result = self.policy.request('thread/resume', params)
        self.assertEqual(result['model'], 'gpt-5.6-sol')
        self.assertEqual(result['config'], {'approval_policy': 'on-request', 'model_reasoning_effort': 'medium'})
        self.assertEqual(result['cwd'], params['cwd'])
        self.policy.seed('t1', {'model': 'gpt-5.6-sol', 'reasoningEffort': 'removed-effort'})
        self.assertEqual(self.policy.request('thread/resume', params)['config']['model_reasoning_effort'], 'medium')
        self.policy.auto['t1'] = False
        self.policy.seed('t1', {'model': 'gpt-5.6-sol', 'reasoningEffort': 'removed-effort'})
        with self.assertRaises(relay.SelectionRequired):
            self.policy.request('thread/resume', params)

    def test_availability_error_requests_refresh_but_does_not_retry(self):
        message = {'id': 1, 'error': {'code': -1, 'message': 'Model is no longer available'}}
        self.assertEqual(self.policy.response(copy.deepcopy(message), 'turn/start', {'threadId': 't1'}), message)
        self.assertTrue(self.policy.refresh_needed)
        self.policy.model_list(catalog())
        self.assertFalse(self.policy.refresh_needed)
        self.policy.response({'error': {'message': 'approval rejected'}}, 'turn/start', {})
        self.assertFalse(self.policy.refresh_needed)

    def test_manual_reselection_uses_new_models_reasoning_and_keeps_native_permissions(self):
        self.policy.seed('t1', {'model': 'removed', 'reasoningEffort': 'retired'})
        params = {'threadId': 't1', 'model': 'gpt-5.6-luna', 'config': {'approval_policy': 'on-request'}}
        result = self.policy.request('thread/resume', params)
        self.assertEqual(result['config'], {'approval_policy': 'on-request', 'model_reasoning_effort': 'medium'})
        params = {'threadId': 't1', 'model': 'gpt-5.6-luna', 'effort': 'low'}
        self.policy.response({'result': {}}, 'thread/settings/update', params)
        self.assertEqual(self.policy.contexts['t1'].effort, 'low')
        self.assertEqual(self.policy.request('turn/start', {'threadId': 't1', 'input': []}), {'threadId': 't1', 'input': []})

    def test_empty_native_configuration_uses_catalog_for_validation_without_overrides(self):
        policy = relay.Policy()
        policy.model_list(catalog())
        self.assertEqual(policy.request('thread/start', {'cwd': '/project'}), {'cwd': '/project'})

    def test_explicit_task_boundary_releases_adaptive_switching_penalty(self):
        observer = mock.Mock()
        observer.decision.side_effect = lambda thread, text, decision, *args, **kwargs: decision
        policy = relay.Policy(mode='auto', observer=observer)
        policy.model_list(catalog())
        policy.response({'result': {'thread': {'id': 't1'}, 'model': 'gpt-5.6-sol', 'reasoningEffort': 'medium'}}, 'thread/start', {})
        for text, active in [('Implement a function.', True), ('New task: implement a function.', False),
                             ('Continue.', True), ('다음 작업: 함수를 구현해줘.', False)]:
            with self.subTest(text=text):
                policy.request('turn/start', {'threadId': 't1', 'input': [{'type': 'text', 'text': text}]})
                self.assertEqual(observer.decision.call_args.args[4].active_task, active)
                self.assertTrue(policy.contexts['t1'].active_task)


class UpdateTests(unittest.TestCase):
    def test_official_package_switches_only_after_verification_and_preserves_older_packages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / 'data'
            dist.install_tool(source(root / 'source', '0.23.0-beta'), data, root / 'bin', sys.executable)
            fixture = root / 'fixture'
            (fixture / 'bin').mkdir(parents=True)
            executable = fixture / 'bin/codex'
            executable.write_bytes(b'official fixture unchanged\n')
            executable.chmod(0o755)
            archive = root / 'codex.tar.gz'
            with tarfile.open(archive, 'w:gz') as bundle:
                bundle.add(executable, arcname='bin/codex')
            value = {'name': 'codex-package-x86_64-unknown-linux-musl.tar.gz', 'url': 'https://api.github.com/repos/openai/codex/releases/assets/1',
                     'digest': 'sha256:' + hashlib.sha256(archive.read_bytes()).hexdigest(), 'size': archive.stat().st_size}
            selected = {'updateAvailable': True, 'release': {'tag_name': 'rust-v0.158.0', 'assets': [value]}}
            with mock.patch.object(official, 'target', return_value='x86_64-unknown-linux-musl'), \
                 mock.patch.object(updates, 'request', side_effect=lambda *args, **kw: io.BytesIO(archive.read_bytes())), \
                 mock.patch.object(entry, 'compatible') as compatible, \
                 mock.patch.object(official.subprocess, 'run', return_value=SimpleNamespace(stdout='codex-cli 0.158.0\n')):
                with mock.patch.object(entry, 'compatible', side_effect=ValueError('unsupported Auto protocol')):
                    with self.assertRaisesRegex(ValueError, 'unsupported Auto'):
                        official.install(data, selected=selected)
                self.assertFalse((data / official.POINTER).exists())
                self.assertFalse((data / 'official-codex').exists())
                binary = official.install(data, selected=selected)
                before = (data / official.POINTER).read_bytes()
                before_mtime = (data / official.POINTER).stat().st_mtime_ns
                self.assertEqual(compatible.call_count, 1)
                self.assertIn('.pending-', str(compatible.call_args.args[0]))
                self.assertEqual(binary.read_bytes(), executable.read_bytes())
                for error in (ValueError('unsupported Auto protocol'), TimeoutError('probe timed out')):
                    with self.subTest(error=type(error).__name__), mock.patch.object(entry, 'compatible', side_effect=error), \
                         mock.patch.object(official.subprocess, 'run', return_value=SimpleNamespace(stdout='codex-cli 0.159.0\n')):
                        with self.assertRaises(type(error)):
                            official.install(data, selected={'updateAvailable': True, 'release': {'tag_name': 'rust-v0.159.0', 'assets': [value]}})
                    self.assertEqual((data / official.POINTER).read_bytes(), before)
                    self.assertEqual((data / official.POINTER).stat().st_mtime_ns, before_mtime)
                    self.assertFalse((data / 'official-codex/0.159.0').exists())
                    self.assertFalse(list((data / 'official-codex').rglob('.pending-*')))
                official.install(data, selected=selected)
                compatible.assert_called_with(binary, ())
                with mock.patch.object(updates, 'request', side_effect=lambda *args, **kw: io.BytesIO(b'bad asset')):
                    with self.assertRaisesRegex(ValueError, 'mismatch'):
                        official.install(data, selected={'updateAvailable': True, 'release': {'tag_name': 'rust-v0.159.0', 'assets': [value]}})
                self.assertEqual((data / official.POINTER).read_bytes(), before)
                self.assertEqual(official.binary(data), binary)
                self.assertIn(binary, official.removal_files(data))
                binary.write_bytes(b'user edit')
                with self.assertRaisesRegex(ValueError, 'Modified'):
                    official.removal_files(data)

    def test_real_release_activation_preserves_previous_files_and_rejects_bad_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = source(root / 'old', '0.22.3-beta', commit='a' * 40)
            new = source(root / 'new', '0.23.0-beta', commit='b' * 40)
            data = root / 'data'
            before = dist.install_tool(old, data, root / 'bin', sys.executable)
            archive = root / 'release.tar.gz'
            with tarfile.open(archive, 'w:gz') as bundle:
                for path in new.rglob('*'):
                    if path.is_file():
                        bundle.add(path, arcname='harness-codex-0.23.0-beta/' + path.relative_to(new).as_posix())
            value = {'name': 'harness-codex-0.23.0-beta-linux.tar.gz', 'url': 'https://api.github.com/repos/sholee-pt/Harness-Codex/releases/assets/1',
                     'digest': 'sha256:' + hashlib.sha256(archive.read_bytes()).hexdigest(), 'size': archive.stat().st_size}
            selected = {'updateAvailable': True, 'availableVersion': '0.23.0-beta',
                        'release': {'tag_name': 'v0.23.0-beta', 'assets': [value]}}
            with mock.patch.object(updates, 'request', side_effect=lambda *args, **kw: io.BytesIO(b'corrupt')):
                with self.assertRaisesRegex(ValueError, 'mismatch'):
                    updates.update(data, selected=selected)
            self.assertEqual(dist.installed_status(data), before)
            old_bytes = {p.relative_to(Path(before['sourceRoot'])): p.read_bytes() for p in Path(before['sourceRoot']).rglob('*') if p.is_file()}
            with mock.patch.object(updates, 'request', side_effect=lambda *args, **kw: io.BytesIO(archive.read_bytes())):
                result = updates.update(data, selected=selected)
            self.assertTrue(result['updated'])
            self.assertEqual(result['installation']['version'], '0.23.0-beta')
            self.assertEqual(result['installation']['commit'], 'b' * 40)
            self.assertEqual({p.relative_to(Path(before['sourceRoot'])): p.read_bytes() for p in Path(before['sourceRoot']).rglob('*') if p.is_file()}, old_bytes)

    def test_published_beta_selection_ignores_drafts_and_nonversion_tags(self):
        releases = [{'tag_name': 'v0.22.3-beta'}, {'tag_name': 'v0.23.0-beta'},
                    {'tag_name': 'v9.0.0', 'draft': True}, {'tag_name': 'preview-latest'}]
        with mock.patch.object(updates, 'metadata', return_value=releases):
            self.assertEqual(updates.latest_harness()['tag_name'], 'v0.23.0-beta')
        with mock.patch.object(updates, 'metadata', return_value=releases), mock.patch.object(dist, 'installed_status', return_value={'version': '0.23.0-beta'}):
            self.assertFalse(updates.check(Path('unused'))['updateAvailable'])

    def test_asset_digest_and_repository_are_required(self):
        value = {'name': 'package', 'url': 'https://api.github.com/repos/openai/codex/releases/assets/123', 'digest': 'sha256:' + 'a' * 64}
        self.assertEqual(updates.asset({'assets': [value]}, 'package', 'openai/codex'), value)
        for bad in ({**value, 'digest': None}, {**value, 'url': 'https://example.org/package'}):
            with self.assertRaises(ValueError):
                updates.asset({'assets': [bad]}, 'package', 'openai/codex')

    def test_every_launch_checks_both_releases_but_skipping_never_installs(self):
        with mock.patch.object(dist, 'installed_status', return_value={'auto_update': 'compatible'}), \
             mock.patch.object(official, 'check', return_value={'updateAvailable': True, 'currentVersion': '1.0.0', 'availableVersion': '1.1.0'}) as codex, \
             mock.patch.object(updates, 'check', return_value={'updateAvailable': True, 'currentVersion': '0.22.3-beta', 'availableVersion': '0.23.0-beta'}) as harness, \
             mock.patch.object(entry, 'choose', return_value=0), mock.patch.object(official, 'install') as install_codex, \
             mock.patch.object(updates, 'update') as install_harness, mock.patch.dict(os.environ, {}, clear=True):
            entry.update_choices(Path('unused'))
            entry.update_choices(Path('unused'))
            self.assertEqual((codex.call_count, harness.call_count), (2, 2))
            install_codex.assert_not_called()
            install_harness.assert_not_called()

    def test_noninteractive_help_remote_and_automation_remain_offline(self):
        with mock.patch.object(sys.stdin, 'isatty', return_value=True), mock.patch.object(sys.stdout, 'isatty', return_value=True):
            for args in (['--help'], ['--version'], ['exec', 'task'], ['app-server'], ['--remote', 'ws://fixture'], ['login'],
                         ['resume', '--help'], ['fork', '-h'], ['resume', '--remote=ws://fixture'],
                         ['resume', 'thread-id', '--remote', 'ws://fixture'], ['agents'], ['archive', '--all'],
                         ['--local-provider', 'ollama', 'queue'], ['--cd=project', 'unarchive', 'thread-id']):
                self.assertFalse(entry.interactive(args), args)
            for args in ([], ['resume', 'thread-id'], ['-C', 'a path', 'resume', '--last'], ['--model', 'model', 'a prompt'],
                         ['-marchive', 'resume', '--last'], ['--', '--help'], ['resume', '--', '--remote'],
                         ['--model', '--help'], ['resume', 'queue'], ['a prompt', 'exec']):
                self.assertTrue(entry.interactive(args), args)

    def test_native_arguments_do_not_promote_option_values_or_escaped_prompts(self):
        self.assertEqual(relay.server_arguments(['-C', '--profile', '-cmodel="fixture"', '--enable=test', 'resume', '--', '--disable', 'keep']),
                         ['-c', 'model="fixture"', '--enable', 'test'])
        self.assertEqual(relay.working_directory(['-c', '--cd=/unrelated', '--', '--cd', '/ignored']), Path.cwd())
        self.assertEqual(relay.working_directory(['resume', '--cd=project']), (Path.cwd() / 'project').absolute())
        for args in (['--profile', 'work'], ['resume', '--profile=work'], ['-pwork']):
            self.assertTrue(relay.profile_requested(args))
            with self.assertRaisesRegex(ValueError, 'preserve profile'):
                relay.server_arguments(args)
        for args in (['--', '--profile', 'work'], ['-m', '--profile']):
            self.assertFalse(relay.profile_requested(args))

    def test_passthrough_and_profile_launch_keep_original_native_arguments(self):
        from harness_cli import main
        for args in (['resume', '--help'], ['fork', '--remote=ws://fixture'], ['archive', '--all'],
                     ['resume', 'thread-id', '--profile', 'work'], ['-pwork'], ['--profile=work']):
            with self.subTest(args=args), mock.patch.object(sys.stdin, 'isatty', return_value=True), \
                 mock.patch.object(sys.stdout, 'isatty', return_value=True), mock.patch.object(sys, 'stderr', io.StringIO()), \
                 mock.patch.object(main, 'default_data_root', return_value=Path('unused')), \
                 mock.patch.object(integration, 'read', return_value={'schema': 2}), \
                 mock.patch.object(official, 'binary', return_value=Path('official-codex')), \
                 mock.patch.object(entry, 'update_choices', return_value=False) as updates_check, \
                 mock.patch.object(entry, 'compatible') as compatible, mock.patch.object(relay, 'run') as run, \
                 mock.patch.object(entry.os, 'execve', side_effect=RuntimeError('native executed')) as execute:
                with self.assertRaisesRegex(RuntimeError, 'native executed'):
                    entry.main(args)
                self.assertEqual(execute.call_args.args[1], ['official-codex', *args])
                compatible.assert_not_called()
                run.assert_not_called()
                if not relay.profile_requested(args):
                    updates_check.assert_not_called()

    def test_candidate_probe_closes_backend_after_incompatible_catalog(self):
        from harness_cli.configuration import Server
        with mock.patch.object(relay, 'dependency'), mock.patch.object(entry.subprocess, 'run',
                return_value=SimpleNamespace(stdout='--remote --remote-auth-token-env')), \
             mock.patch('harness_cli.configuration.Server', autospec=Server) as server:
            server.return_value.call.return_value = {'data': [], 'nextCursor': None}
            with self.assertRaisesRegex(ValueError, 'visible Codex models'):
                entry.compatible(Path('candidate-codex'), ())
            server.return_value.close.assert_called_once()

    def test_auto_resume_preferences_contain_only_bounded_boolean_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry.remember(root, 'thread-id', True)
            before = (root / 'relay-sessions.json').stat().st_mtime_ns
            entry.remember(root, 'thread-id', True)
            self.assertEqual((root / 'relay-sessions.json').stat().st_mtime_ns, before)
            self.assertEqual(entry.sessions(root), {'thread-id': True})
            entry.remember(root, '../unowned', False)
            self.assertEqual(entry.sessions(root), {'thread-id': True})


class IntegrationMigrationTests(unittest.TestCase):
    def test_linux_entry_registration_rollback_idempotence_and_removal_ownership(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, home = root / 'data', root / 'home'
            home.mkdir()
            (home / '.bashrc').write_bytes(b'# user\n')
            src = source(root / 'source', '0.23.0-beta', commit=None)
            state = dist.install_tool(src, data, root / 'bin', sys.executable)
            with mock.patch.object(integration_path, 'os', SimpleNamespace(name='posix')), \
                 mock.patch.object(integration_path, 'block', side_effect=lambda path, home=None: (integration_path.START + '\n# ' + str(path) + '\n' + integration_path.END + '\n').encode()), \
                 mock.patch.object(relay, 'dependency'), mock.patch.object(official, 'read', return_value={'version': '1.2.3'}), \
                 mock.patch.object(official, 'binary', return_value=root / 'official-codex'):
                with mock.patch.object(integration_path, 'apply', side_effect=ValueError('concurrent')):
                    with self.assertRaisesRegex(ValueError, 'concurrent'):
                        integration._official_install(data, state, None, 'auto', None, home)
                self.assertIsNone(integration.read(data))
                first = integration._official_install(data, state, None, 'auto', None, home)
                saved = integration.read(data)
                paths = [data / name for name in saved['files']] + [data / integration.RECEIPT, home / '.bashrc']
                before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
                integration._official_install(data, state, saved, 'auto', None, home)
                self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}, before)
                self.assertTrue(set(paths[:-1]) <= integration.removal_files(data).keys())
                self.assertEqual(saved['schema'], 2)
                self.assertIn('_codex "$@"', (data / 'codex-bin/codex').read_text())


class RelayProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_menu_submission_error_never_claims_no_task_was_sent_or_replays(self):
        script = """import json, sys
for line in sys.stdin:
    message = json.loads(line)
    method = message.get('method')
    if method == 'turn/start':
        print(json.dumps({'id': message['id'], 'error': {'code': -1, 'message': 'Model is no longer available'}}), flush=True)
    else:
        result = CATALOG if method == 'model/list' else {'thread': {'cwd': CWD}}
        print(json.dumps({'id': message['id'], 'result': result}), flush=True)
""".replace('CATALOG', repr(catalog())).replace('CWD', repr(os.getcwd()))
        adapter = relay.Relay(sys.executable, dict(os.environ), args=['-c', script], policy=relay.Policy())
        class Socket:
            request = SimpleNamespace(path='/', headers={'Authorization': 'Bearer ' + adapter.token})
            def __init__(self):
                self.queue, self.messages = asyncio.Queue(), []
                self.queue.put_nowait({'id': 1, 'method': 'turn/start', 'params': {'threadId': 't1',
                    'input': [{'type': 'text', 'text': '/harness/'}]}})
            def __aiter__(self):
                return self
            async def __anext__(self):
                value = await self.queue.get()
                if value is None:
                    raise StopAsyncIteration
                return json.dumps(value)
            async def send(self, raw):
                message = json.loads(raw)
                self.messages.append(message)
                if message.get('method') == 'warning' and 'submission was not confirmed' in message['params']['message']:
                    self.queue.put_nowait(None)
            async def close(self, **kwargs):
                pass
        socket = Socket()
        with mock.patch('harness_cli.management_relay.Controls.execute', new=mock.AsyncMock(return_value={'review': True})), \
                mock.patch.object(adapter.policy, 'request', wraps=adapter.policy.request) as requests:
            await asyncio.wait_for(adapter.connect(socket), 10)
        self.assertEqual(sum(call.args[0] == 'turn/start' for call in requests.call_args_list), 1)
        self.assertIsNone(adapter.error)
        self.assertTrue(adapter.policy.refresh_needed)
        warnings = [item['params']['message'] for item in socket.messages if item.get('method') == 'warning']
        self.assertEqual(sum('submission was not confirmed' in warning for warning in warnings), 1)
        self.assertIn('no automatic replay', '\n'.join(warnings))
        self.assertNotIn('no task was submitted', '\n'.join(warnings))

    async def test_authenticated_picker_reconnect_waits_for_backend_teardown(self):
        adapter = relay.Relay('codex', {}, policy=relay.Policy(session_modes={'thread': True}))
        closing, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def session(socket):
            calls.append(socket)
            if len(calls) == 1:
                adapter.policy.pending_modes['thread'] = False
                closing.set()
                await release.wait()
            else:
                self.assertEqual(adapter.policy.pending_modes, {})
        headers = {'Authorization': 'Bearer ' + adapter.token}
        first, second = [SimpleNamespace(request=SimpleNamespace(path='/', headers=headers), close=mock.AsyncMock()) for _ in range(2)]
        with mock.patch.object(adapter, 'session', side_effect=session):
            previous = asyncio.create_task(adapter.connect(first))
            await closing.wait()
            following = asyncio.create_task(adapter.connect(second))
            await asyncio.sleep(.01)
            self.assertEqual(calls, [first])
            release.set()
            await asyncio.gather(previous, following)
        self.assertEqual(calls, [first, second])
        self.assertFalse(adapter.connected)
        self.assertTrue(adapter.policy.enabled('thread'))
        first.close.assert_not_called()
        second.close.assert_not_called()

    async def test_failed_backend_start_does_not_latch_connection(self):
        adapter = relay.Relay('codex', {})
        socket = SimpleNamespace(request=SimpleNamespace(path='/', headers={'Authorization': 'Bearer ' + adapter.token}), close=mock.AsyncMock())
        with mock.patch.object(relay.asyncio, 'create_subprocess_exec', side_effect=OSError('missing')):
            await adapter.connect(socket)
        self.assertFalse(adapter.connected)
        self.assertFalse(adapter.connection_lock.locked())
        self.assertIn('backend could not start', adapter.error)
        socket.close.assert_awaited_once_with(code=1011, reason='Codex backend unavailable')

    async def test_backend_exit_during_cleanup_is_not_a_start_failure(self):
        for escalation in (False, True):
            with self.subTest(escalation=escalation):
                adapter = relay.Relay('codex', {})
                process = SimpleNamespace(pid=1234, returncode=None,
                    stdout=SimpleNamespace(readline=mock.AsyncMock(return_value=b'')),
                    wait=mock.AsyncMock(side_effect=[asyncio.TimeoutError(), 0] if escalation else [0]))
                signal_process = mock.Mock(side_effect=[None, ProcessLookupError()] if escalation else ProcessLookupError())

                class Socket:
                    request = SimpleNamespace(path='/', headers={'Authorization': 'Bearer ' + adapter.token})
                    close = mock.AsyncMock()
                    def __aiter__(self):
                        return self
                    async def __anext__(self):
                        raise StopAsyncIteration

                socket = Socket()
                with mock.patch.object(relay.asyncio, 'create_subprocess_exec', return_value=process), \
                     mock.patch.object(relay, 'os', SimpleNamespace(name='posix', killpg=signal_process)):
                    await adapter.connect(socket)
                self.assertIsNone(adapter.error)
                self.assertFalse(adapter.connection_lock.locked())
                socket.close.assert_awaited_once_with()
                self.assertEqual(process.wait.await_count, 2 if escalation else 1)
                expected = [mock.call(process.pid, relay.signal.SIGTERM)]
                if escalation:
                    expected.append(mock.call(process.pid, relay.signal.SIGKILL))
                self.assertEqual(signal_process.call_args_list, expected)

    async def test_real_websocket_reconnect_keeps_authentication_and_new_request_ids(self):
        try:
            from websockets.asyncio.client import connect
            serve = relay.dependency()
        except (ImportError, ValueError):
            self.skipTest('optional WebSocket transport unavailable')
        script = "import sys,json\nfor line in sys.stdin:\n m=json.loads(line); print(json.dumps({'id':m['id'],'result':{'method':m['method']}}),flush=True)"
        adapter = relay.Relay(sys.executable, dict(os.environ), args=['-c', script])
        async with serve(adapter.connect, '127.0.0.1', 0, compression=None) as server:
            uri = 'ws://127.0.0.1:' + str(server.sockets[0].getsockname()[1])
            for _ in range(2):
                async with connect(uri, additional_headers={'Authorization': 'Bearer ' + adapter.token}, proxy=None) as socket:
                    await socket.send(json.dumps({'id': 'initialize', 'method': 'initialize', 'params': {}}))
                    message = json.loads(await asyncio.wait_for(socket.recv(), 10))
                    self.assertEqual(message, {'id': 'initialize', 'result': {'method': 'initialize'}})
        self.assertIsNone(adapter.error)
        self.assertFalse(adapter.connected)

    async def test_authenticated_endpoint_has_no_path_secret_or_backend_environment_change(self):
        env = {'PATH': 'project-bin', 'CONDA_PREFIX': 'project-env'}
        adapter = relay.Relay('codex', env)
        command, child_env = adapter.client(12345, ['resume', 'thread-id'])
        self.assertEqual(command[:4], ['codex', '--remote', 'ws://127.0.0.1:12345', '--remote-auth-token-env'])
        self.assertEqual(command[4:], [adapter.auth_env, 'resume', 'thread-id'])
        self.assertNotIn(adapter.token, ' '.join(command))
        self.assertEqual(child_env, {**env, adapter.auth_env: adapter.token})
        self.assertNotIn(adapter.auth_env, adapter.env)
        self.assertEqual(env, {'PATH': 'project-bin', 'CONDA_PREFIX': 'project-env'})
        self.assertNotEqual(adapter.token, relay.Relay('codex', env).token)

    async def test_unauthenticated_or_browser_connections_never_start_backend(self):
        adapter = relay.Relay('codex', {})
        for path, headers in [('/', {}), ('/', {'Authorization': 'Bearer wrong'}),
                ('/', {'Authorization': 'Bearer \N{GRINNING FACE}'}),
                ('/' + adapter.token, {'Authorization': 'Bearer ' + adapter.token}),
                ('/', {'Authorization': 'Bearer ' + adapter.token, 'Origin': ''})]:
            with self.subTest(path=path, header_names=list(headers)), \
                 mock.patch.object(relay.asyncio, 'create_subprocess_exec') as start:
                socket = SimpleNamespace(request=SimpleNamespace(path=path, headers=headers), close=mock.AsyncMock())
                await adapter.connect(socket)
                socket.close.assert_awaited_once_with(code=1008, reason='Local Codex client required')
                start.assert_not_called()
                self.assertFalse(adapter.connected)

    async def test_real_stdio_process_keeps_approval_ids_and_inference_separate(self):
        script = """import json, sys
catalog = CATALOG
for line in sys.stdin:
    message = json.loads(line)
    method = message.get('method')
    if method == 'model/list':
        result = catalog
    elif method == 'turn/start':
        print(json.dumps({'id': message['id'], 'method': 'item/commandExecution/requestApproval', 'params': {'threadId': 't1'}}), flush=True)
        answer = json.loads(sys.stdin.readline())
        result = {'turn': {'id': 'turn1'}, 'received': message['params'], 'approval': answer}
    else:
        result = {}
    print(json.dumps({'id': message['id'], 'result': result}), flush=True)
""".replace('CATALOG', repr(catalog()))
        policy = relay.Policy()
        adapter = relay.Relay(sys.executable, dict(os.environ), args=['-c', script], policy=policy)

        class Socket:
            request = SimpleNamespace(path='/', headers={'Authorization': 'Bearer ' + adapter.token})
            def __init__(self):
                self.queue = asyncio.Queue()
                self.messages = []
                self.queue.put_nowait({'id': 1, 'method': 'model/list', 'params': {}})
            def __aiter__(self):
                return self
            async def __anext__(self):
                value = await self.queue.get()
                if value is None:
                    raise StopAsyncIteration
                return json.dumps(value)
            async def send(self, raw):
                message = json.loads(raw)
                self.messages.append(message)
                if message.get('method'):
                    self.queue.put_nowait({'id': 2, 'result': {'decision': 'decline'}})
                elif message['id'] == 1:
                    self.queue.put_nowait({'id': 2, 'method': 'turn/start', 'params': {'threadId': 't1',
                        'model': relay.ALIAS, 'approvalPolicy': 'on-request',
                        'input': [{'type': 'text', 'text': 'New task: Fix a typo in README.'}]}})
                else:
                    self.queue.put_nowait(None)
            async def close(self, **kwargs):
                pass

        socket = Socket()
        await asyncio.wait_for(adapter.connect(socket), 10)
        self.assertIsNone(adapter.error)
        self.assertEqual(socket.messages[1]['method'], 'item/commandExecution/requestApproval')
        result = socket.messages[-1]['result']
        self.assertEqual(result['received']['model'], 'gpt-5.6-sol')
        self.assertEqual(result['received']['approvalPolicy'], 'on-request')
        self.assertEqual(result['approval'], {'id': 2, 'result': {'decision': 'decline'}})

    async def test_paginated_refresh_resume_and_removed_model_never_replay_inference(self):
        script = """import json, sys
calls, turns = [], 0
for line in sys.stdin:
    message = json.loads(line)
    method, params = message['method'], message['params']
    calls.append({'method': method, 'params': params})
    if method == 'model/list':
        model, effort = ('future-model', 'adaptive') if turns else ('old-model', 'medium')
        entry = {'model': model, 'id': model, 'isDefault': True, 'defaultReasoningEffort': effort,
                 'supportedReasoningEfforts': [{'reasoningEffort': effort}]}
        result = {'data': [entry] if params.get('cursor') else [], 'nextCursor': None if params.get('cursor') else 'page2'}
    elif method == 'thread/read':
        result = {'thread': {'id': 't1', 'model': 'old-model', 'reasoningEffort': 'medium'}}
    elif method == 'thread/resume':
        result = {'thread': {'id': 't1'}, 'model': 'old-model', 'reasoningEffort': 'medium'}
    elif method == 'turn/start':
        turns += 1
        if turns == 1:
            print(json.dumps({'id': message['id'], 'error': {'code': -1, 'message': 'Model is no longer available'}}), flush=True)
            continue
        result = {'turn': {'id': str(turns)}, 'received': params, 'calls': calls}
    print(json.dumps({'id': message['id'], 'result': result}), flush=True)
"""
        policy = relay.Policy(session_modes={'t1': True})
        adapter = relay.Relay(sys.executable, dict(os.environ), args=['-c', script], policy=policy)
        task = {'threadId': 't1', 'model': 'old-model', 'effort': 'medium', 'approvalPolicy': 'on-request',
                'input': [{'type': 'text', 'text': 'Continue.'}]}

        class Socket:
            request = SimpleNamespace(path='/', headers={'Authorization': 'Bearer ' + adapter.token})
            def __init__(self):
                self.queue, self.messages = asyncio.Queue(), []
                self.queue.put_nowait({'id': 1, 'method': 'thread/resume', 'params': {'threadId': 't1'}})
            def __aiter__(self):
                return self
            async def __anext__(self):
                value = await self.queue.get()
                if value is None:
                    raise StopAsyncIteration
                return json.dumps(value)
            async def send(self, raw):
                message = json.loads(raw)
                self.messages.append(message)
                if 'id' not in message:
                    return
                if message['id'] == 4:
                    self.queue.put_nowait(None)
                else:
                    self.queue.put_nowait({'id': message['id'] + 1, 'method': 'turn/start', 'params': task})
            async def close(self, **kwargs):
                pass

        socket = Socket()
        await asyncio.wait_for(adapter.connect(socket), 10)
        self.assertIsNone(adapter.error)
        responses = {item['id']: item for item in socket.messages if 'id' in item}
        self.assertIn('error', responses[2])
        self.assertEqual(responses[3]['result']['received']['model'], 'future-model')
        self.assertEqual(responses[3]['result']['received']['effort'], 'adaptive')
        calls = responses[4]['result']['calls']
        self.assertEqual([item['params']['includeTurns'] for item in calls if item['method'] == 'thread/read'], [False])
        self.assertEqual(sum(item['method'] == 'model/list' for item in calls), 4)
        submitted = [item['params'] for item in calls if item['method'] == 'turn/start']
        self.assertEqual(len(submitted), 3)
        for item in submitted:
            self.assertEqual(item['input'], task['input'])
            self.assertEqual(item['approvalPolicy'], 'on-request')
        self.assertTrue(any('No failed task was replayed' in item.get('params', {}).get('message', '') for item in socket.messages))


if __name__ == '__main__':
    unittest.main()
