"""Exercise the progress client over real subprocess JSON-RPC, without model calls."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time
import unittest
from unittest import mock

from harness_cli import configuration, presentation, project, setup

ROOT = Path(__file__).resolve().parents[1]
FAKE = r'''
import json, os, pathlib, sys, time
mode = os.environ["TEST_SERVER_MODE"]
log = pathlib.Path(os.environ["TEST_SERVER_LOG"])
def send(value):
    print(json.dumps(value), flush=True)
def note(method, params):
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"method": method, "params": params}) + "\n")
def complete():
    if mode == "generate":
        sys.path.insert(0, str(pathlib.Path(os.environ["TEST_SOURCE"]) / "test"))
        from test_harness_tools import harness_apply, minimal_plan
        root = pathlib.Path.cwd()
        harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))
    final = {"status": "needs-input" if mode == "needs-input" else "complete", "message": "Which dataset should be used?" if mode == "needs-input" else "Configuration result from Codex."}
    text = json.dumps(final) if mode != "unstructured" else "Which dataset should be used?"
    send({"method": "item/completed", "params": {"threadId": "native-thread", "item": {"id": "final", "type": "agentMessage", "text": text}}})
    send({"method": "turn/completed", "params": {"threadId": "native-thread", "turn": {"id": "turn-1", "status": "interrupted" if mode == "interrupted" else "completed"}}})
for line in sys.stdin:
    value = json.loads(line)
    method, params = value.get("method"), value.get("params", {})
    note(method or "answer", params if method else value.get("result", value.get("error")))
    if method == "initialize":
        send({"id": value["id"], "result": {"userAgent": "test"}})
    elif method in {"thread/start", "thread/resume"}:
        send({"id": value["id"], "result": {"thread": {"id": "native-thread"}, "model": "native-configured-model", "reasoningEffort": "medium", "sandbox": {"type": "readOnly"}, "approvalPolicy": "on-request"}})
    elif method == 'config/read':
        send({'id': value['id'], 'result': {'config': {'model': 'native-configured-model', 'model_reasoning_effort': 'medium', 'sandbox_mode': 'read-only', 'approval_policy': 'on-request'}}})
    elif method == 'thread/archive':
        send({'id': value['id'], 'result': {}})
    elif method == 'thread/read':
        saved = {'cwd': os.environ.get('TEST_THREAD_CWD', str(pathlib.Path.cwd())),
                 'model': 'removed-model' if mode == 'removed-model' else 'native-configured-model',
                 'reasoningEffort': 'removed-effort' if mode == 'removed-effort' else 'medium'}
        send({'id': value['id'], 'result': {'thread': saved}})
    elif method == "model/list":
        native = {"model": "native-configured-model", "isDefault": True, "defaultReasoningEffort": "medium", "supportedReasoningEfforts": [{"reasoningEffort": "medium"}, {"reasoningEffort": "high"}]}
        alternate = {"model": "catalog-alternative", "defaultReasoningEffort": "low", "supportedReasoningEfforts": [{"reasoningEffort": "low"}, {"reasoningEffort": "ultra"}]}
        data, cursor = ([native], "second") if not params.get("cursor") else ([alternate], None)
        if mode == "bad-catalog":
            data = None
        if mode == "repeated-cursor":
            cursor = "second"
        send({"id": value["id"], "result": {"data": data, "nextCursor": cursor}})
    elif method == "turn/start":
        if mode == "managed-rejection":
            send({"id": value["id"], "error": {"code": -32600, "message": "Managed policy does not allow these permissions"}})
            continue
        if mode == "malformed":
            print("not protocol json", flush=True)
            continue
        send({"method": "turn/started", "params": {"threadId": "native-thread", "turn": {"id": "turn-1"}}})
        if mode == "early":
            complete()
        send({"id": value["id"], "result": {"turn": {"id": "turn-1"}}})
        if mode == "early":
            continue
        if mode == "eof":
            sys.exit(0)
        if mode == "timeout":
            continue
        if mode == "foreign":
            send({"method": "turn/completed", "params": {"threadId": "other-thread", "turn": {"id": "other", "status": "failed", "error": {"message": "foreign failure"}}}})
        if mode in {"approve", "approval-access", "approval-declined", "approval-failed", "missing-command"}:
            request = {"threadId": "native-thread", "turnId": "turn-1", "itemId": "command"}
            if mode != "missing-command":
                request.update({"command": "cat README.md", "cwd": str(pathlib.Path.cwd()), "availableDecisions": ["accept", {"acceptWithExecpolicyAmendment": {"execpolicy_amendment": ["cat", "README.md"]}}, "cancel"]})
            if mode == "approval-access":
                request.update({"environmentId": "remote-test", "reason": "Access the selected source", "commandActions": [{"command": "cat README.md", "type": "read"}], "networkApprovalContext": {"host": "example.invalid", "protocol": "https"}, "additionalPermissions": {"fileSystem": {"read": ["/external/review-source"]}}})
            send({"id": "approval", "method": "item/commandExecution/requestApproval", "params": request})
        elif mode in {"file", "missing-file"}:
            if mode == "file":
                send({"method": "item/started", "params": {"threadId": "native-thread", "item": {"id": "edit", "type": "fileChange", "changes": [{"path": "AGENTS.md", "kind": {"type": "add"}, "diff": "+ use project harness"}]}}})
            send({"id": "approval", "method": "item/fileChange/requestApproval", "params": {"threadId": "native-thread", "turnId": "turn-1", "itemId": "edit"}})
        elif mode == "question":
            send({"id": "question", "method": "item/tool/requestUserInput", "params": {"questions": [{"id": "purpose", "question": "What is the project purpose?", "options": [{"label": "Research", "description": "Investigate data"}, {"label": "Service", "description": "Serve users"}]}]}})
        elif mode == "permissions":
            send({"id": "grant", "method": "item/permissions/requestApproval", "params": {"permissions": {"network": {"enabled": True}}}})
        elif mode == "unknown":
            send({"id": "new-api", "method": "future/requestApproval", "params": {}})
        else:
            complete()
    elif method is None:
        if mode in {"approval-declined", "approval-failed"}:
            send({"method": "serverRequest/resolved", "params": {"threadId": "native-thread", "requestId": "approval"}})
            output = "rejected by configuration" if mode == "approval-declined" else "bwrap: Operation not permitted"
            send({"method": "item/completed", "params": {"threadId": "native-thread", "item": {"id": "command", "type": "commandExecution", "status": "declined" if mode == "approval-declined" else "failed", "exitCode": None, "aggregatedOutput": output}}})
        complete()
'''
class Terminal(io.StringIO):
    def isatty(self):
        return True

class ConfigurationProgressTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'project with spaces'
        self.root.mkdir()
        self.fake = self.base / 'codex fixture.py'
        self.fake.write_text(FAKE, encoding='utf-8')
        self.log = self.base / 'protocol.jsonl'
        self.command = [sys.executable, '-B', str(self.fake)]
        self.addCleanup(mock.patch.stopall)
        mock.patch('harness_cli.hook_trust.prepare', return_value={'status': 'trusted', 'count': 7, 'changed': False}).start()
        mock.patch.dict(os.environ, {'TEST_SERVER_MODE': 'noop', 'TEST_SERVER_LOG': str(self.log),
                                   'TEST_SOURCE': str(ROOT)}).start()
        self.output, self.error = Terminal(), io.StringIO()

    def invoke(self, mode='noop', answers=(), **kwargs):
        with mock.patch.dict(os.environ, {'TEST_SERVER_MODE': mode}), contextlib.redirect_stdout(self.output), \
                contextlib.redirect_stderr(self.error), mock.patch.object(sys, 'stdin', Terminal()), \
                mock.patch('builtins.input', side_effect=list(answers)):
            self.result = configuration.run(self.command, self.root, 'PRIVATE BOOTSTRAP TEXT', **kwargs)
            return self.result.code

    def records(self):
        return [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines()]

    def test_native_protocol_preserves_settings_and_hides_transport_and_prompt(self):
        self.assertEqual(self.invoke(), 0)
        records = self.records()
        start = next(r['params'] for r in records if r['method'] == 'thread/start')
        self.assertEqual(start, {'cwd': str(self.root)})
        turn = next(r['params'] for r in records if r['method'] == 'turn/start')
        self.assertEqual(set(turn), {'threadId', 'input', 'outputSchema'})
        output = self.output.getvalue() + self.error.getvalue()
        self.assertNotIn('PRIVATE BOOTSTRAP TEXT', output)
        self.assertNotIn('"method"', output)
        self.assertIn('native-configured-model', output)
        self.assertNotIn('Configuration result from Codex.', output)
        self.assertNotIn('--resume', output)
        self.assertEqual(self.result.message, 'Configuration result from Codex.')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_resume_uses_native_session_without_project_registry(self):
        self.assertEqual(self.invoke(resume_id='earlier-native-session'), 0)
        records = self.records()
        self.assertEqual(next(r['params'] for r in records if r['method'] == 'thread/resume'),
                         {'cwd': str(self.root), 'threadId': 'earlier-native-session'})
        self.assertFalse(any(r['method'] == 'thread/start' for r in records))
        self.assertEqual(list(self.root.iterdir()), [])

    @unittest.skipIf(os.name == 'nt', 'POSIX command parsing; PowerShell quoting is tested separately')
    def test_resume_guidance_keeps_project_and_session_literal_from_another_directory(self):
        from harness_cli.main import build_parser
        self.root = self.base / "project with spaces ' $HOME `name`"
        self.root.mkdir()
        self.assertNotEqual(Path.cwd(), self.root)
        for mode in ('needs-input', 'interrupted'):
            with self.subTest(mode=mode):
                self.output.seek(0)
                self.output.truncate()
                self.error.seek(0)
                self.error.truncate()
                self.assertEqual(self.invoke(mode), 1 if mode == 'needs-input' else 130)
                if mode == 'needs-input':
                    with contextlib.redirect_stdout(self.output):
                        self.result.show_resume(self.root)
                    text = self.output.getvalue()
                else:
                    text = self.error.getvalue()
                line = next(line for line in text.splitlines() if line.startswith('To continue'))
                arguments = shlex.split(line.split(': ', 1)[1])
                self.assertEqual(arguments, ['harness-codex', 'config', '--project', str(self.root), '--resume', 'native-thread'])
                parsed = build_parser(ROOT).parse_args(arguments[1:])
                self.assertEqual(parsed.project, self.root)
                self.assertEqual(parsed.resume, 'native-thread')
        session = "session ' $HOME `literal`"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            configuration.Result(1, session).show_resume(self.root)
        self.assertEqual(shlex.split(output.getvalue().split(': ', 1)[1])[-1], session)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            configuration.Result(1, 'session\x1b[31m').show_resume(self.root)
        self.assertNotIn('\x1b', output.getvalue())

    def test_early_completion_and_foreign_thread_events(self):
        for mode in ('early', 'foreign'):
            with self.subTest(mode=mode):
                self.assertEqual(self.invoke(mode), 0)
        self.assertNotIn('foreign failure', self.error.getvalue())

    def test_command_approval_uses_enter_default_and_explicit_decline(self):
        for answer, decision in [('yes', 'accept'), (' yes \t', 'accept'), ('', 'accept'), ('y', 'accept'), ('n', 'decline'), (' NO ', 'decline')]:
            with self.subTest(answer=answer):
                self.assertEqual(self.invoke('approve', [answer]), 0)
                self.assertEqual(self.records()[-1]['params']['decision'], decision)
                self.assertIn('Approved for this request' if decision == 'accept' else 'Request declined', self.error.getvalue())
        self.assertIn('cat README.md', self.error.getvalue())
        self.assertIn(str(self.root), self.error.getvalue())

    def test_approval_preview_omits_unselected_policy_metadata_and_reprompts_invalid_input(self):
        self.assertEqual(self.invoke('approve', ['maybe', 'n']), 0)
        self.assertEqual(self.records()[-1]['params'], {'decision': 'decline'})
        output = self.error.getvalue()
        self.assertEqual(output.count('cat README.md'), 1)
        self.assertNotIn('availableDecisions', output)
        self.assertNotIn('execpolicy_amendment', output)
        self.assertIn('\nCommand approval\n', output)
        self.assertIn('\n  $ cat README.md\n', output)
        self.assertIn('Press Enter or type y', output)

    def test_compact_approval_keeps_requested_access_and_environment_visible(self):
        self.assertEqual(self.invoke('approval-access', ['']), 0)
        output = self.error.getvalue()
        for detail in ('remote-test', 'Access the selected source', 'example.invalid', 'https', '/external/review-source'):
            self.assertIn(detail, output)
        self.assertEqual(output.count('cat README.md'), 1)
        self.assertEqual(self.records()[-1]['params'], {'decision': 'accept'})

    def test_approval_never_accepts_redirected_or_absent_interactive_input(self):
        with mock.patch.dict(os.environ, {'TEST_SERVER_MODE': 'approve'}), contextlib.redirect_stderr(self.error), \
                mock.patch.object(sys, 'stdin', io.StringIO()), self.assertRaisesRegex(ValueError, 'terminal is required'):
            configuration.run(self.command, self.root, 'PRIVATE BOOTSTRAP TEXT')
        self.assertFalse(any(r['method'] == 'answer' for r in self.records()))

    def test_accepted_requests_report_native_rejection_or_sandbox_failure_without_broader_retry(self):
        for mode, status, detail in [('approval-declined', 'declined', 'rejected by configuration'),
                                     ('approval-failed', 'failed', 'host/container')]:
            with self.subTest(mode=mode):
                self.log.unlink(missing_ok=True)
                self.assertEqual(self.invoke(mode, ['yes']), 0)
                records = self.records()
                self.assertEqual([r['params'] for r in records if r['method'] == 'answer'], [{'decision': 'accept'}])
                self.assertEqual(sum(r['method'] == 'turn/start' for r in records), 1)
                self.assertIn('waiting for the Codex execution result', self.error.getvalue())
                self.assertIn(f'Codex command result: {status}', self.error.getvalue())
                self.assertIn(detail, self.error.getvalue())
                self.assertEqual(list(self.root.iterdir()), [])

    def test_file_approval_displays_complete_diff(self):
        self.assertEqual(self.invoke('file', ['']), 0)
        self.assertIn('AGENTS.md', self.error.getvalue())
        self.assertIn('+ use project harness', self.error.getvalue())
        self.assertEqual(self.records()[-1]['params']['decision'], 'accept')

    def test_missing_approval_previews_are_declined(self):
        for mode in ('missing-command', 'missing-file'):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'preview'):
                self.invoke(mode)
            self.assertEqual(self.records()[-1]['params']['decision'], 'decline')

    def test_questions_keep_native_answer_shape(self):
        self.assertEqual(self.invoke('question', ['1']), 0)
        self.assertEqual(self.records()[-1]['params'], {'answers': {'purpose': {'answers': ['Research']}}})
        self.assertIn('What is the project purpose?', self.error.getvalue())

    def test_unfamiliar_permission_scope_is_not_granted(self):
        with self.assertRaisesRegex(ValueError, 'No permissions were granted'):
            self.invoke('permissions')
        self.assertEqual(self.records()[-1]['params'], {'permissions': {}, 'scope': 'turn'})

    def test_unknown_requests_fail_with_native_fallback(self):
        with self.assertRaisesRegex(ValueError, '--interactive'):
            self.invoke('unknown')
        self.assertEqual(self.records()[-1]['params']['code'], -32601)

    def test_interruption_is_not_success(self):
        self.assertEqual(self.invoke('interrupted'), 130)
        self.assertIn('interrupted', self.error.getvalue())
        self.assertNotIn(': finished', self.error.getvalue())

    def test_connection_failures_and_timeout_close_child(self):
        for mode, error in [('malformed', ValueError), ('eof', ValueError), ('timeout', TimeoutError)]:
            with self.subTest(mode=mode), self.assertRaises(error):
                self.invoke(mode, timeout=1 if mode == 'timeout' else 5)
        self.assertNotIn(': finished', self.error.getvalue())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_default_init_validates_real_generated_artifacts_and_partial_configuration(self):
        parser = argparse.ArgumentParser()
        project.register_project_commands(parser.add_subparsers(dest='command'))
        args = parser.parse_args(['init', '--no-codex-integration', '--project', str(self.root), '--settings', 'native'])
        with mock.patch.object(project, '_codex_command', return_value=self.command), \
                mock.patch.object(sys, 'stdin', Terminal()), contextlib.redirect_stdout(self.output), \
                contextlib.redirect_stderr(self.error):
            self.assertEqual(project.run_project_command(args, source_root=ROOT), 1)
            self.assertIn('generator-only', self.error.getvalue())
            self.assertNotIn('"validationLayers"', self.error.getvalue())
            with mock.patch.dict(os.environ, {'TEST_SERVER_MODE': 'generate'}):
                args = parser.parse_args(['config', '--no-codex-integration', '--project', str(self.root), '--settings', 'native'])
                self.assertEqual(project.run_project_command(args, source_root=ROOT), 0, self.error.getvalue())
        self.assertTrue((self.root / '.harness/manifest.json').is_file())
        self.assertIn('Project harness files validate', self.output.getvalue())
        self.assertEqual(sum(r['method'] == 'thread/archive' for r in self.records()), 1)
        args = parser.parse_args(['config', '--no-codex-integration', '--project', str(self.root), '--settings', 'native', '--resume', 'owned-by-user'])
        with mock.patch.object(project, '_codex_command', return_value=self.command), \
                mock.patch.object(sys, 'stdin', Terminal()), contextlib.redirect_stdout(self.output), \
                contextlib.redirect_stderr(self.error):
            self.assertEqual(project.run_project_command(args, source_root=ROOT), 0)
        self.assertEqual(sum(r['method'] == 'thread/archive' for r in self.records()), 1)

    def test_settings_preserve_defaults_and_use_only_catalog_efforts(self):
        self.assertEqual(self.invoke(settings='manual', answers=['', '', '', '']), 0)
        turn = next(r['params'] for r in self.records() if r['method'] == 'turn/start')
        self.assertEqual(set(turn), {'threadId', 'input', 'outputSchema'})
        self.log.unlink()
        self.assertEqual(self.invoke(settings='manual', answers=['2', '2', '2', '']), 0)
        turn = next(r['params'] for r in self.records() if r['method'] == 'turn/start')
        self.assertEqual((turn['model'], turn['effort']), ('catalog-alternative', 'ultra'))
        self.assertEqual(turn['sandboxPolicy']['type'], 'workspaceWrite')
        self.assertEqual(turn['sandboxPolicy']['writableRoots'], [str(self.root)])
        self.assertFalse(turn['sandboxPolicy']['networkAccess'])
        self.assertEqual(turn['approvalPolicy'], 'on-request')
        self.assertEqual(turn['approvalsReviewer'], 'user')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_changed_model_uses_its_advertised_default_and_invalid_choices_reprompt(self):
        self.assertEqual(self.invoke(settings='manual', answers=['9999', 'no', '2', '', '1', '']), 0)
        turn = next(r['params'] for r in self.records() if r['method'] == 'turn/start')
        self.assertEqual(turn['effort'], 'low')
        self.assertEqual(turn['sandboxPolicy'], {'type': 'readOnly', 'networkAccess': False})

    def test_full_access_requires_selected_permission_and_separate_confirmation(self):
        for answer in ('', 'y', 'yes', 'n', 'no'):
            with self.subTest(answer=answer):
                self.assertEqual(self.invoke(settings='manual', answers=['', '', '3', answer, '']), 0)
                turn = [r['params'] for r in self.records() if r['method'] == 'turn/start'][-1]
                if answer in {'', 'y', 'yes'}:
                    self.assertEqual(turn['sandboxPolicy'], {'type': 'dangerFullAccess'})
                    self.assertEqual(turn['approvalPolicy'], 'never')
                else:
                    self.assertNotIn('sandboxPolicy', turn)
                    self.assertNotIn('approvalPolicy', turn)

    def test_settings_back_navigation_replaces_stale_model_reasoning_and_permissions(self):
        cases = [(['2', 'b', '1', '2', 'b', '1', '2', ''], 'native-configured-model', 'medium', 'workspaceWrite'),
                 (['2', '2', '3', 'yes', 'b', '0', ''], 'catalog-alternative', 'ultra', None)]
        for answers, model, effort, sandbox in cases:
            with self.subTest(answers=answers):
                self.log.unlink(missing_ok=True)
                self.assertEqual(self.invoke(settings='manual', answers=answers), 0)
                records = self.records()
                turns = [r['params'] for r in records if r['method'] == 'turn/start']
                self.assertEqual(len(turns), 1)
                self.assertEqual((turns[0]['model'], turns[0]['effort']), (model, effort))
                self.assertEqual(turns[0].get('sandboxPolicy', {}).get('type'), sandbox)
                if sandbox is None:
                    self.assertNotIn('approvalPolicy', turns[0])
                output = self.error.getvalue()
                self.assertIn(f'Model: {model}\nReasoning: {effort}\n', output)
                self.assertIn('Review settings', output)

    def test_settings_review_cancellation_does_not_create_a_conversation(self):
        self.assertEqual(self.invoke(settings='manual', answers=['', '', '', KeyboardInterrupt]), 130)
        self.assertFalse(any(r['method'] in {'thread/start', 'turn/start'} for r in self.records()))

    def test_model_back_can_return_to_mode_selection_without_carrying_manual_overrides(self):
        for mode in ('0', '2'):
            with self.subTest(mode=mode):
                self.log.unlink(missing_ok=True)
                self.assertEqual(self.invoke(settings='manual', answers=['b', mode]), 0)
                turns = [r['params'] for r in self.records() if r['method'] == 'turn/start']
                self.assertEqual(len(turns), 1)
                self.assertNotIn('sandboxPolicy', turns[0])
                if mode == '2':
                    self.assertNotIn('model', turns[0])
                else:
                    self.assertEqual(turns[0]['model'], 'native-configured-model')
        from harness_cli.native_session import settings_arguments
        self.log.unlink(missing_ok=True)
        with mock.patch.object(sys, 'stdin', Terminal()), contextlib.redirect_stderr(self.error), mock.patch('builtins.input', side_effect=['b', '2']):
            self.assertEqual(settings_arguments(self.command, self.root, 'manual'), [])
        self.assertFalse(any(r['method'] in {'thread/start', 'turn/start'} for r in self.records()))

    def test_setting_selection_interruption_never_starts_a_model_turn(self):
        with mock.patch('harness_cli.presentation.Progress.ask', side_effect=KeyboardInterrupt):
            self.assertEqual(self.invoke(settings='manual'), 130)
        self.assertFalse(any(r['method'] == 'turn/start' for r in self.records()))
        self.assertFalse(any(r['method'] == 'thread/start' for r in self.records()))

    def test_auto_uses_recommended_supported_defaults_without_permission_overrides(self):
        self.assertEqual(self.invoke(settings='ask', answers=['']), 0)
        records = self.records()
        turn = next(r['params'] for r in records if r['method'] == 'turn/start')
        self.assertEqual((turn['model'], turn['effort']), ('native-configured-model', 'medium'))
        self.assertNotIn('sandboxPolicy', turn)
        self.assertNotIn('approvalPolicy', turn)
        methods = [r['method'] for r in records]
        self.assertLess(methods.index('model/list'), methods.index('thread/start'))
        self.assertTrue(self.result.created_session)
        self.log.unlink()
        self.assertEqual(self.invoke(settings='auto', resume_id='saved'), 0)
        self.assertFalse(self.result.created_session)
        self.assertIn('model/list', [r['method'] for r in self.records()])
        turn = next(r['params'] for r in self.records() if r['method'] == 'turn/start')
        self.assertNotIn('model', turn)

    def test_resume_revalidates_removed_model_or_effort_before_opening_without_permission_changes(self):
        for mode in ('removed-model', 'removed-effort'):
            for settings in ('auto', 'manual'):
                with self.subTest(mode=mode, settings=settings):
                    self.log.unlink(missing_ok=True)
                    self.assertEqual(self.invoke(mode, settings=settings, resume_id='saved', answers=['', '', '', '']), 0)
                    calls = self.records()
                    resumed = next(r['params'] for r in calls if r['method'] == 'thread/resume')
                    turn = next(r['params'] for r in calls if r['method'] == 'turn/start')
                    self.assertEqual(resumed['config'], {'model_reasoning_effort': 'medium'})
                    if mode == 'removed-model' or settings == 'auto':
                        self.assertEqual(resumed['model'], 'native-configured-model')
                    self.assertEqual(turn['effort'], 'medium')
                    for params in (resumed, turn):
                        self.assertNotIn('sandboxPolicy', params)
                        self.assertNotIn('approvalPolicy', params)
                    self.assertEqual(next(r['params'] for r in calls if r['method'] == 'thread/read')['includeTurns'], False)

    def test_configuration_menu_discovery_never_creates_threads_and_native_starts_no_server(self):
        from harness_cli.native_session import settings_arguments
        with contextlib.redirect_stdout(self.output), contextlib.redirect_stderr(self.error):
            self.assertEqual(settings_arguments(self.command, self.root, 'native'), [])
            self.assertFalse(self.log.exists())
            arguments = settings_arguments(self.command, self.root, 'auto')
        self.assertEqual(arguments, ['--model', 'native-configured-model', '-c', 'model_reasoning_effort="medium"'])
        self.assertFalse(any(r['method'].startswith(('thread/', 'turn/')) for r in self.records()))

    def test_invalid_catalog_stops_before_selection_or_generation(self):
        for mode in ('bad-catalog', 'repeated-cursor'):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'catalog'):
                self.invoke(mode, settings='manual')
            self.assertFalse(any(r['method'] == 'turn/start' for r in self.records()))

    def test_managed_permission_rejection_is_not_retried_or_downgraded(self):
        with self.assertRaisesRegex(ValueError, 'Managed policy'):
            self.invoke('managed-rejection', settings='manual', answers=['', '', '2', ''])
        turns = [r for r in self.records() if r['method'] == 'turn/start']
        self.assertEqual(len(turns), 1)
        self.assertNotIn(': finished', self.error.getvalue())

    def test_unstructured_final_is_visible_and_not_reported_as_success(self):
        with self.assertRaisesRegex(ValueError, 'confirmed configuration outcome'):
            self.invoke('unstructured')
        self.assertIn('Which dataset should be used?', self.error.getvalue())
        self.assertNotIn(': finished', self.error.getvalue())

    def test_completed_existing_harness_does_not_hide_a_new_question(self):
        parser = argparse.ArgumentParser()
        project.register_project_commands(parser.add_subparsers(dest='command'))
        with mock.patch.object(project, '_codex_command', return_value=self.command), \
                mock.patch.object(sys, 'stdin', Terminal('\n\n')), contextlib.redirect_stdout(self.output), \
                contextlib.redirect_stderr(self.error):
            args = parser.parse_args(['init', '--no-codex-integration', '--project', str(self.root), '--settings', 'native'])
            with mock.patch.dict(os.environ, {'TEST_SERVER_MODE': 'generate'}):
                self.assertEqual(project.run_project_command(args, source_root=ROOT), 0)
            clean_output = self.output.getvalue()
            self.assertNotIn('Configuration result from Codex.', clean_output)
            self.assertNotIn('--resume', clean_output)
            self.output.seek(0)
            self.output.truncate()
            args = parser.parse_args(['config', '--no-codex-integration', '--project', str(self.root), '--settings', 'native'])
            with mock.patch.dict(os.environ, {'TEST_SERVER_MODE': 'needs-input'}):
                self.assertEqual(project.run_project_command(args, source_root=ROOT), 1)
            self.assertEqual(sum(r['method'] == 'thread/archive' for r in self.records()), 1)
            self.assertIn('Which dataset should be used?', self.output.getvalue())
            self.assertIn(presentation.command(['harness-codex', 'config', '--project', self.root, '--resume', 'native-thread']), self.output.getvalue())
            self.assertNotIn('Configuration complete.', self.output.getvalue())
            self.output.seek(0)
            self.output.truncate()
            args = parser.parse_args(['config', '--no-codex-integration', '--project', str(self.root), '--settings', 'native', '--details'])
            self.assertEqual(project.run_project_command(args, source_root=ROOT), 0)
            self.assertIn('Configuration result from Codex.', self.output.getvalue())
            self.assertIn('Completed setup session: native-thread', self.output.getvalue())

    def test_explicit_uuid_locates_saved_project_without_turns_and_project_flag_takes_precedence(self):
        from harness_cli.main import build_parser
        session = '01a085f7-ab6b-7241-a715-62b2baab5d73'
        args = build_parser(ROOT).parse_args(['resume', session])
        project.preflight_project_command(args, source_root=ROOT)
        self.assertIsNone(args.project)
        self.assertFalse(self.log.exists())
        args = build_parser(ROOT).parse_args(['resume', session, '--project', str(self.root)])
        project.preflight_project_command(args, source_root=ROOT)
        self.assertEqual(args.project, self.root)
        self.assertFalse(self.log.exists())

    def test_sandbox_diagnostics_do_not_classify_generic_failures_as_permission_errors(self):
        from harness_cli.native_session import execution_diagnostic
        self.assertIn('host/container', execution_diagnostic('bwrap RTM_NEWADDR operation not permitted'))
        self.assertIn('reviewer', execution_diagnostic('Approval budget limit exceeded'))
        self.assertIsNone(execution_diagnostic('pytest failed: assertion mismatch'))

    @unittest.skipUnless(os.name == 'posix', 'POSIX terminal; Windows ConPTY is checked separately')
    def test_arrow_menu_over_real_pseudoterminal(self):
        import pty
        import select
        import subprocess
        master, slave = pty.openpty()
        environment = dict(os.environ, TERM='xterm-256color')
        environment.pop('NO_COLOR', None)
        script = ('from harness_cli.presentation import Progress; from harness_cli.terminal_menu import choose; '
                  'p=Progress("probe", compact=True); '
                  'print("SELECTED:", choose(p, "Model selection", ["Auto", "Manual", "Native"]))')
        process = subprocess.Popen([sys.executable, '-B', '-c', script], cwd=ROOT, env=environment,
                                   stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        data, sent, deadline = b'', False, time.monotonic() + 10
        try:
            while time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    try:
                        chunk = os.read(master, 8192)
                    except OSError:
                        break
                    if not chunk:
                        break
                    data += chunk
                    if not sent and b'Ctrl+C: cancel' in data:
                        os.write(master, b'\x1b[C\x1b[1~\x1b[3~\x1b[A\x1b[B\x1b[B\r')
                        sent = True
                if process.poll() is not None and b'SELECTED:' in data:
                    break
            self.assertEqual(process.wait(timeout=2), 0)
            self.assertIn(b'SELECTED: 1', data)
            self.assertIn(b'\x1b[1;36m> Manual', data)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)

class PresentationTests(unittest.TestCase):
    def test_only_ctrl_c_cancels_and_only_enter_accepts(self):
        from harness_cli import terminal_menu
        for key in ('\x1b', '\x04', 'right', 'left', '', ' ', 'y'):
            with self.subTest(key=repr(key)):
                self.assertEqual(terminal_menu.next_selection(1, key, 3), (1, False))
        for key in ('\r', '\n'):
            self.assertEqual(terminal_menu.next_selection(1, key, 3), (1, True))
        with self.assertRaises(KeyboardInterrupt):
            terminal_menu.next_selection(1, '\x03', 3)

    def test_escape_sequences_do_not_cancel_or_leave_special_key_tails(self):
        from collections import deque
        from harness_cli import terminal_menu
        for sequence, expected in [(b'', '\x1b'), (b'[A', 'up'), (b'OB', 'down'), (b'[D', 'left'),
                                   (b'[C', ''), (b'[1~', ''), (b'[3~', ''), (b'[1;5C', ''), (b'[', '')]:
            pending = deque(bytes([value]) for value in sequence)
            with self.subTest(sequence=sequence), \
                    mock.patch.object(terminal_menu.select, 'select', side_effect=lambda *args: ([0] if pending else [], [], [])), \
                    mock.patch.object(terminal_menu.os, 'read', side_effect=lambda *args: pending.popleft()):
                key = terminal_menu.escape_key(0)
            self.assertEqual(key, expected)
            self.assertFalse(pending)
            if not expected:
                self.assertEqual(terminal_menu.next_selection(1, key, 3), (1, False))

    def test_semantic_colors_respect_terminal_no_color_and_sanitize_external_text(self):
        for stream, term, disabled, colored in [(Terminal(), 'xterm', False, True), (Terminal(), 'xterm', True, False),
                                                (Terminal(), 'dumb', False, False), (io.StringIO(), 'xterm', False, False)]:
            with self.subTest(term=term, disabled=disabled, colored=colored), mock.patch.dict(os.environ, {'TERM': term}):
                os.environ.pop('NO_COLOR', None)
                if disabled:
                    os.environ['NO_COLOR'] = '1'
                progress = presentation.Progress('preview', stream=stream)
                progress.line('Command\x1b[31m', style='heading')
                text = stream.getvalue()
                self.assertIn('Command?[31m', text)
                self.assertEqual('\x1b[1;36m' in text, colored)
                self.assertNotIn('\x1b[31m', text)

    def test_keyboard_menu_summary_spacing_back_and_cleanup(self):
        from harness_cli import terminal_menu
        class MenuTerminal(Terminal):
            def fileno(self):
                return 0
        for keys, expected in [(['\x1b', 'right', '\x04', 'down', '\r'], 1), (['left'], -1), (['b'], -1)]:
            output, inputs = MenuTerminal(), iter(keys)
            with mock.patch.object(sys, 'stdin', MenuTerminal()), mock.patch.dict(os.environ, {'TERM': 'xterm', 'NO_COLOR': '1'}), \
                    mock.patch.object(terminal_menu, 'keyboard', return_value=contextlib.nullcontext(lambda: next(inputs))), \
                    mock.patch.object(terminal_menu.shutil, 'get_terminal_size', return_value=os.terminal_size((60, 24))):
                progress = presentation.Progress('settings', stream=output)
                result = terminal_menu.choose(progress, 'Reasoning', ['Keep current', 'High'], back=True, summary=['Model: catalog-model'])
                self.assertEqual(result, expected)
                self.assertIn('Model: catalog-model\n\r\x1b[2K\n', output.getvalue())
                self.assertNotIn('\x1b[1;36m', output.getvalue())
                self.assertTrue(output.getvalue().endswith('A\r'))
                self.assertFalse(progress.paused)
        output, inputs = MenuTerminal(), iter(['left', '\x1b', 'right', 'down', '\r'])
        with mock.patch.object(sys, 'stdin', MenuTerminal()), mock.patch.dict(os.environ, {'TERM': 'xterm'}), \
                mock.patch.object(terminal_menu, 'keyboard', return_value=contextlib.nullcontext(lambda: next(inputs))):
            self.assertEqual(terminal_menu.choose(presentation.Progress('settings', stream=output), 'First step', ['Auto', 'Manual']), 1)
        self.assertEqual(terminal_menu.fit_row('한글A', 4), '한글')
        self.assertEqual(terminal_menu.fit_row('title\n\x1b[31m', 9), 'title ?[3')

    def test_compact_progress_does_not_repeat_commands_or_wrap_narrow_terminals(self):
        for stream in (io.StringIO(), Terminal()):
            with mock.patch.dict(os.environ, {'TERM': 'xterm', 'COLUMNS': '40'}):
                with presentation.Progress('Configure project', stream=stream, compact=True) as progress:
                    for index in range(30):
                        progress.phase('Inspect files' if index % 2 else 'Validate the generated project harness files')
                    time.sleep(0.25)
            lines = stream.getvalue().split('\n')
            self.assertEqual(len(lines), 3)
            self.assertEqual(stream.getvalue().count('Configure project'), 2)
            self.assertNotIn('Inspect files\n', stream.getvalue())
    def test_progress_transport_accepts_large_brief_and_resume_requires_an_id(self):
        parser = argparse.ArgumentParser()
        project.register_project_commands(parser.add_subparsers(dest='command'))
        with tempfile.TemporaryDirectory() as directory:
            args = parser.parse_args(['config', '--no-codex-integration', '--project', directory, '--goal', 'x' * 50000])
            project.preflight_project_command(args, source_root=ROOT)
            for session in ('', '   ', '\n'):
                args = parser.parse_args(['config', '--no-codex-integration', '--project', directory, '--resume', session])
                with self.assertRaisesRegex(project.ProjectError, '--resume'):
                    project.preflight_project_command(args, source_root=ROOT)

    def test_human_reports_and_explicit_json(self):
        parser = argparse.ArgumentParser()
        project.register_project_commands(parser.add_subparsers(dest='command'))
        with tempfile.TemporaryDirectory() as directory:
            for command in ('status', 'doctor', 'init'):
                flags = ['--dry-run'] if command == 'init' else []
                for use_json in (False, True):
                    args = parser.parse_args([command, '--project', directory, *flags, *(['--json'] if use_json else [])])
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                        project.run_project_command(args, source_root=ROOT)
                    if use_json:
                        self.assertIsInstance(json.JSONDecoder().raw_decode(out.getvalue())[0], dict)
                    else:
                        self.assertNotIn('"validationLayers"', out.getvalue())
                        self.assertFalse(out.getvalue().lstrip().startswith('{'))
        presentation.JSON_MODE.set(False)

    def test_timer_ticks_but_redirected_output_has_no_escapes(self):
        for tty in (False, True):
            stream = Terminal() if tty else io.StringIO()
            with mock.patch.dict(os.environ, {'TERM': 'xterm'}):
                with presentation.Progress('Waiting', stream=stream):
                    time.sleep(1.25)
            text = stream.getvalue()
            self.assertIn('(1s)', text)
            self.assertEqual('\x1b[2K' in text, tty)
            if tty:
                self.assertIn('  1s', text)

    def test_pause_file_keeps_exact_cross_platform_bytes_and_preserves_unowned_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'harness-codex-progress-test'
            path.write_bytes(b'Harness installation progress\nrunning\n')
            with mock.patch.dict(os.environ, {'HARNESS_INSTALL_PAUSE_FILE': str(path)}):
                setup._pause_installer(True)
                self.assertEqual(path.read_bytes(), b'Harness installation progress\npaused\n')
                setup._pause_installer(False)
                self.assertEqual(path.read_bytes(), b'Harness installation progress\nrunning\n')
                path.write_bytes(b'Unrelated user file')
                setup._pause_installer(True)
                self.assertEqual(path.read_bytes(), b'Unrelated user file')
