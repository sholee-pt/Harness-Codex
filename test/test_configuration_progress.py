"""Exercise the progress client over real subprocess JSON-RPC, without model calls."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
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
    send({"method": "item/completed", "params": {"threadId": "native-thread", "item": {"id": "final", "type": "agentMessage", "text": "Configuration result from Codex."}}})
    send({"method": "turn/completed", "params": {"threadId": "native-thread", "turn": {"id": "turn-1", "status": "interrupted" if mode == "interrupted" else "completed"}}})
for line in sys.stdin:
    value = json.loads(line)
    method, params = value.get("method"), value.get("params", {})
    note(method or "answer", params if method else value.get("result", value.get("error")))
    if method == "initialize":
        send({"id": value["id"], "result": {"userAgent": "test"}})
    elif method in {"thread/start", "thread/resume"}:
        send({"id": value["id"], "result": {"thread": {"id": "native-thread"}, "model": "native-configured-model"}})
    elif method == "turn/start":
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
        if mode in {"approve", "missing-command"}:
            request = {"threadId": "native-thread", "turnId": "turn-1", "itemId": "command"}
            if mode == "approve":
                request.update({"command": "cat README.md", "cwd": str(pathlib.Path.cwd()), "availableDecisions": ["accept", "decline"]})
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
        mock.patch.dict(os.environ, {'TEST_SERVER_MODE': 'noop', 'TEST_SERVER_LOG': str(self.log),
                                   'TEST_SOURCE': str(ROOT)}).start()
        self.output, self.error = Terminal(), io.StringIO()

    def invoke(self, mode='noop', answers=(), **kwargs):
        with mock.patch.dict(os.environ, {'TEST_SERVER_MODE': mode}), contextlib.redirect_stdout(self.output), \
                contextlib.redirect_stderr(self.error), mock.patch.object(sys, 'stdin', Terminal()), \
                mock.patch('builtins.input', side_effect=list(answers)):
            return configuration.run(self.command, self.root, 'PRIVATE BOOTSTRAP TEXT', **kwargs)

    def records(self):
        return [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines()]

    def test_native_protocol_preserves_settings_and_hides_transport_and_prompt(self):
        self.assertEqual(self.invoke(), 0)
        records = self.records()
        start = next(r['params'] for r in records if r['method'] == 'thread/start')
        self.assertEqual(start, {'cwd': str(self.root)})
        turn = next(r['params'] for r in records if r['method'] == 'turn/start')
        self.assertEqual(set(turn), {'threadId', 'input'})
        output = self.output.getvalue() + self.error.getvalue()
        self.assertNotIn('PRIVATE BOOTSTRAP TEXT', output)
        self.assertNotIn('"method"', output)
        self.assertIn('native-configured-model', output)
        self.assertIn('Configuration result from Codex.', output)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_resume_uses_native_session_without_project_registry(self):
        self.assertEqual(self.invoke(resume_id='earlier-native-session'), 0)
        records = self.records()
        self.assertEqual(next(r['params'] for r in records if r['method'] == 'thread/resume'),
                         {'cwd': str(self.root), 'threadId': 'earlier-native-session'})
        self.assertFalse(any(r['method'] == 'thread/start' for r in records))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_early_completion_and_foreign_thread_events(self):
        for mode in ('early', 'foreign'):
            with self.subTest(mode=mode):
                self.assertEqual(self.invoke(mode), 0)
        self.assertNotIn('foreign failure', self.error.getvalue())

    def test_command_approval_requires_explicit_yes_and_displays_action(self):
        for answer, decision in [('yes', 'accept'), ('', 'decline'), ('y', 'decline')]:
            with self.subTest(answer=answer):
                self.assertEqual(self.invoke('approve', [answer]), 0)
                self.assertEqual(self.records()[-1]['params']['decision'], decision)
        self.assertIn('cat README.md', self.error.getvalue())
        self.assertIn(str(self.root), self.error.getvalue())

    def test_file_approval_displays_complete_diff(self):
        self.assertEqual(self.invoke('file', ['yes']), 0)
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
        args = parser.parse_args(['init', '--project', str(self.root)])
        with mock.patch.object(project, '_codex_command', return_value=self.command), \
                mock.patch.object(sys, 'stdin', Terminal()), contextlib.redirect_stdout(self.output), \
                contextlib.redirect_stderr(self.error):
            self.assertEqual(project.run_project_command(args, source_root=ROOT), 1)
            self.assertIn('generator-only', self.error.getvalue())
            self.assertNotIn('"validationLayers"', self.error.getvalue())
            with mock.patch.dict(os.environ, {'TEST_SERVER_MODE': 'generate'}):
                args = parser.parse_args(['config', '--project', str(self.root)])
                self.assertEqual(project.run_project_command(args, source_root=ROOT), 0, self.error.getvalue())
        self.assertTrue((self.root / '.harness/manifest.json').is_file())
        self.assertIn('Project harness files validate', self.output.getvalue())

class PresentationTests(unittest.TestCase):
    def test_progress_transport_accepts_large_brief_and_resume_requires_an_id(self):
        parser = argparse.ArgumentParser()
        project.register_project_commands(parser.add_subparsers(dest='command'))
        with tempfile.TemporaryDirectory() as directory:
            args = parser.parse_args(['config', '--project', directory, '--goal', 'x' * 50000])
            project.preflight_project_command(args, source_root=ROOT)
            for session in ('', '   ', '\n'):
                args = parser.parse_args(['config', '--project', directory, '--resume', session])
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
