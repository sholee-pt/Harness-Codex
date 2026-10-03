"""Check the manual picker/native launch boundary without a model or global writes."""
import contextlib
import io
from pathlib import Path
import subprocess
import tomllib
import unittest
from unittest import mock

from harness_cli import native_session, project, session_settings


class NativeSessionSettingsTests(unittest.TestCase):
    def arguments(self, permission, *, root=Path('/selected/project'), confirm=True):
        server = mock.Mock()
        server.call.side_effect = lambda method, params, **kwargs: {
            'config/read': {'config': {'model': 'catalog-model', 'model_reasoning_effort': 'medium',
                                      'sandbox_mode': 'workspace-write', 'approval_policy': 'never',
                                      'approvals_reviewer': 'auto_review',
                                      'sandbox_workspace_write': {'writable_roots': ['/unrelated'],
                                                                  'network_access': True,
                                                                  'exclude_slash_tmp': True,
                                                                  'exclude_tmpdir_env_var': True}}},
            'model/list': {'data': [{'model': 'catalog-model', 'defaultReasoningEffort': 'medium',
                                    'supportedReasoningEfforts': [{'reasoningEffort': 'medium'}]}]},
        }[method]
        with mock.patch.object(native_session, 'Server', return_value=server), \
                mock.patch.object(session_settings, 'choose', side_effect=[0, 0, permission, 0]), \
                mock.patch('harness_cli.presentation.confirm', return_value=confirm), \
                contextlib.redirect_stderr(io.StringIO()):
            arguments = native_session.settings_arguments(['codex'], root, 'manual')
        server.initialize.assert_called_once_with()
        server.close.assert_called_once_with()
        self.assertEqual([call.args[0] for call in server.call.call_args_list], ['config/read', 'model/list'])
        return arguments

    def config_overrides(self, arguments):
        return tomllib.loads('\n'.join(arguments[index + 1] for index, value in enumerate(arguments) if value == '-c'))

    def test_workspace_selection_replaces_inherited_network_roots_and_temp_permissions(self):
        root = Path('/selected/project with "quotes" and \\ Unicode 한글')
        arguments = self.arguments(2, root=root)
        self.assertEqual(arguments[:4], ['--sandbox', 'workspace-write', '--ask-for-approval', 'on-request'])
        self.assertEqual(self.config_overrides(arguments), {
            'approvals_reviewer': 'user',
            'sandbox_workspace_write': {'writable_roots': [str(root)], 'network_access': False,
                                        'exclude_slash_tmp': False, 'exclude_tmpdir_env_var': False},
        })

    def test_read_only_and_confirmed_full_access_use_the_selected_native_sandbox(self):
        for permission, sandbox, approval in ((1, 'read-only', 'on-request'), (3, 'danger-full-access', 'never')):
            with self.subTest(permission=permission):
                arguments = self.arguments(permission)
                self.assertEqual(arguments[:4], ['--sandbox', sandbox, '--ask-for-approval', approval])
                self.assertEqual(self.config_overrides(arguments), {'approvals_reviewer': 'user'})

    def test_keep_current_or_declined_full_access_adds_no_permission_override(self):
        self.assertEqual(self.arguments(0), [])
        self.assertEqual(self.arguments(3, confirm=False), [])

    def test_native_mode_does_not_discover_or_override_settings(self):
        with mock.patch.object(native_session, 'Server') as server:
            self.assertEqual(native_session.settings_arguments(['codex'], Path('/project'), 'native'), [])
        server.assert_not_called()

    def test_picker_distinguishes_codex_defaults_from_harness_auto_routing(self):
        with mock.patch.object(session_settings, 'choose', return_value=0) as choose:
            self.assertEqual(session_settings.mode_choice(mock.Mock(), 'ask'), 'auto')
        self.assertIn('Codex defaults', choose.call_args.args[2][0])
        self.assertIn('Harness Auto routing is selected separately in /model.', choose.call_args.kwargs['summary'])

    def test_failed_native_launch_is_returned_without_retry_or_broader_permissions(self):
        root = Path('/selected/project')
        arguments = self.arguments(2, root=root)
        with mock.patch.object(native_session, 'settings_arguments', return_value=arguments), \
                mock.patch.object(project.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(project._launch(['codex'], root, '', settings='manual', environment={}), 1)
        run.assert_called_once_with(['codex', '--cd', str(root), *arguments], cwd=root, check=False, env={})


if __name__ == '__main__':
    unittest.main()
