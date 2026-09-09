"""Stream native Codex app-server configuration without exposing bootstrap text.

Use native settings and approvals unchanged. JSON-RPC is transport only: no
transcripts, credentials or runtime records are written into the project.
"""
from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time

from .environment import codex_environment
from .presentation import Progress, clean

MAX_MESSAGE = 4 * 1024 * 1024


class Server:
    def __init__(self, command: list[str], root: Path, progress: Progress):
        self.progress = progress
        self.messages = queue.Queue(maxsize=16)
        self.stop = threading.Event()
        self.next_id = 0
        self.pending = {}
        self.completed = deque()
        self.items = {}
        self.thread_id = self.turn_id = None
        self.last_message = ''
        self.waiting = set()
        self.stderr = bytearray()
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        self.process = subprocess.Popen([*command, 'app-server', '--listen', 'stdio://'], cwd=root,
            env=codex_environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
        self.readers = [threading.Thread(target=self._read, daemon=True), threading.Thread(target=self._errors, daemon=True)]
        for thread in self.readers:
            thread.start()

    def _put(self, item):
        while not self.stop.is_set():
            try:
                self.messages.put(item, timeout=0.2)
                return
            except queue.Full:
                continue

    def _read(self):
        try:
            while not self.stop.is_set():
                line = self.process.stdout.readline(MAX_MESSAGE + 1)
                if not line:
                    break
                if len(line) > MAX_MESSAGE:
                    raise ValueError('Codex sent an oversized protocol message; use --interactive to inspect it.')
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError('Codex sent an invalid protocol message.')
                self._put(item)
        except (ValueError, OSError) as exc:
            self._put(exc)
        finally:
            self._put(None)

    def _errors(self):
        try:
            while not self.stop.is_set():
                data = self.process.stderr.read(4096)
                if not data:
                    return
                self.stderr.extend(data)
                del self.stderr[:-16384]
        except (OSError, ValueError):
            pass

    def send(self, value):
        payload = json.dumps(value, ensure_ascii=False).encode('utf-8') + b'\n'
        if len(payload) > MAX_MESSAGE:
            raise ValueError('Codex request exceeds the supported size.')
        self.process.stdin.write(payload)
        self.process.stdin.flush()

    def call(self, method, params, timeout=30):
        self.next_id += 1
        request = self.next_id
        self.waiting.add(request)
        self.send({'id': request, 'method': method, 'params': params})
        deadline = time.monotonic() + timeout
        while request not in self.pending:
            self.event(deadline)
        answer = self.pending.pop(request)
        self.waiting.discard(request)
        if 'error' in answer:
            message = answer['error'].get('message', 'Unknown protocol error') if isinstance(answer['error'], dict) else 'Invalid protocol error'
            raise ValueError(f'Codex {method}: {clean(message)}. Retry with --interactive if your Codex version needs its native UI.')
        result = answer.get('result', {})
        if not isinstance(result, dict):
            raise ValueError(f'Codex {method} returned an invalid result.')
        return result

    def event(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Codex configuration timed out. Project files are retained; inspect status before retrying.')
        try:
            item = self.messages.get(timeout=min(remaining, 0.2))
        except queue.Empty:
            return None
        if isinstance(item, Exception):
            raise item
        if item is None:
            detail = self.stderr.decode('utf-8', errors='replace').strip().splitlines()
            suffix = clean(detail[-1])[:1000] if detail else 'No completion event was received.'
            raise ValueError(f'Codex connection closed before completion. {suffix}')
        if 'method' not in item:
            if type(item.get('id')) is int and item['id'] in self.waiting:
                self.pending[item['id']] = item
            return None
        params = item.get('params') or {}
        if not isinstance(params, dict) or not isinstance(item['method'], str):
            raise ValueError('Codex sent invalid event parameters; retry with --interactive.')
        if 'id' in item:
            self.answer(item['id'], item['method'], params)
            return None
        if self.thread_id and params.get('threadId', self.thread_id) != self.thread_id:
            return None
        method = item['method']
        if method in {'turn/started', 'turn/completed'} and not isinstance(params.get('turn'), dict):
            raise ValueError('Codex sent an invalid turn event.')
        if method in {'item/started', 'item/completed'} and not isinstance(params.get('item'), dict):
            raise ValueError('Codex sent an invalid item event.')
        if method == 'turn/started':
            self.turn_id = params.get('turn', {}).get('id')
        elif method in {'item/started', 'item/completed'}:
            value = params.get('item', {})
            item_id = value.get('id')
            if method == 'item/started' and item_id:
                if len(self.items) >= 128:
                    raise ValueError('Too many pending Codex items; stop and inspect the native session.')
                self.items[item_id] = value
            kind = value.get('type')
            if kind == 'commandExecution' and method == 'item/started':
                command = str(value.get('command', ''))
                label = ('Validating proposed changes' if '--dry-run' in command else
                         'Applying the project harness' if 'harness_apply' in command else
                         'Checking the project harness' if any(s in command for s in ('validate_harness', 'harness_doctor')) else
                         'Preparing the harness proposal' if 'harness_plan_builder' in command else 'Inspecting project files and running checks')
                self.progress.phase(label)
            elif kind == 'fileChange' and method == 'item/started':
                self.progress.phase('Updating project harness files')
            elif kind == 'agentMessage' and method == 'item/completed':
                self.last_message = clean(value.get('text', ''))
            if method == 'item/completed':
                self.items.pop(item_id, None)
        elif method == 'error':
            detail = params.get('error', {}).get('message', params.get('message', 'Codex reported an error'))
            self.progress.line(f'Codex: {clean(detail)}')
        elif method == 'turn/completed':
            self.completed.append(params.get('turn', {}))
        return None

    def detail(self, value, prefix=''):
        """Render approval data completely without raw JSON or silent truncation."""
        if isinstance(value, dict):
            for key, item in value.items():
                self.detail(item, f'{prefix}.{key}' if prefix else str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self.detail(item, f'{prefix}[{index}]')
        elif value is not None:
            self.progress.line(f'  {prefix}: {clean(value)}')

    def answer(self, request_id, method, params):
        if method in {'item/commandExecution/requestApproval', 'item/fileChange/requestApproval'}:
            self.progress.line('Codex requests approval. Review the requested action:')
            self.detail({k: v for k, v in params.items() if k not in {'threadId', 'turnId', 'itemId', 'startedAtMs'}})
            if method == 'item/commandExecution/requestApproval' and not any(params.get(key) for key in ('command', 'networkApprovalContext', 'commandActions')):
                self.send({'id': request_id, 'result': {'decision': 'decline'}})
                raise ValueError('No command or network preview was received. Approval declined; use --interactive.')
            if method == 'item/fileChange/requestApproval':
                changes = self.items.get(params.get('itemId'), {}).get('changes')
                if not changes:
                    self.send({'id': request_id, 'result': {'decision': 'decline'}})
                    raise ValueError('No file-change preview was received. Approval declined; use --interactive for native review.')
                self.detail(changes, 'changes')
            available = params.get('availableDecisions')
            can_accept = available is None or 'accept' in available
            if not can_accept:
                self.send({'id': request_id, 'result': {'decision': 'cancel'}})
                raise ValueError('Codex requested an approval scope requiring native review. Use --interactive.')
            answer = self.progress.ask('Approve this request? Type yes; Enter declines: ')
            self.send({'id': request_id, 'result': {'decision': 'accept' if answer == 'yes' else 'decline'}})
        elif method == 'item/tool/requestUserInput':
            answers = {}
            questions = params.get('questions')
            if not isinstance(questions, list) or not questions or len(questions) > 10:
                raise ValueError('Codex returned an invalid question request.')
            for question in questions:
                if (not isinstance(question, dict) or not isinstance(question.get('question'), str)
                        or not isinstance(question.get('id'), str)):
                    raise ValueError('Codex returned an invalid question.')
                self.progress.line(question['question'])
                options = question.get('options') or []
                if not isinstance(options, list) or any(not isinstance(o, dict) or not isinstance(o.get('label'), str) for o in options):
                    raise ValueError('Codex returned invalid question options.')
                for index, option in enumerate(options, 1):
                    self.progress.line(f"  {index}. {option['label']} — {option.get('description', '')}")
                answer = self.progress.ask('Your answer (number or text): ', secret=bool(question.get('isSecret')))
                if answer.isdigit() and 1 <= int(answer) <= len(options):
                    answer = options[int(answer) - 1]['label']
                answers[question['id']] = {'answers': [answer] if answer else []}
            self.send({'id': request_id, 'result': {'answers': answers}})
        elif method == 'item/permissions/requestApproval':
            # Permission profiles can include durable or platform-specific
            # grants. Do not translate unfamiliar scopes into broader access.
            self.send({'id': request_id, 'result': {'permissions': {}, 'scope': 'turn'}})
            raise ValueError('Additional permission-profile review needs native Codex. No permissions were granted; retry with --interactive.')
        else:
            self.send({'id': request_id, 'error': {'code': -32601, 'message': 'Request requires the native Codex UI'}})
            raise ValueError(f'Codex requested {clean(method)}, which needs its native UI. Retry with --interactive; nothing was auto-approved.')

    def close(self):
        self.stop.set()
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32/taskkill.exe'), '/PID', str(self.process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.process.wait(timeout=5)
        for stream in (self.process.stdout, self.process.stderr):
            stream.close()
        for thread in self.readers:
            thread.join(timeout=1)


def run(command: list[str], root: Path, prompt: str, *, timeout=1800, resume_id=None) -> int:
    deadline = time.monotonic() + timeout
    with Progress('Connecting to Codex') as progress:
        server = Server(command, root, progress)
        try:
            server.call('initialize', {'clientInfo': {'name': 'harness_codex', 'title': 'Harness for Codex', 'version': '9.10'}}, timeout=min(30, deadline-time.monotonic()))
            server.send({'method': 'initialized', 'params': {}})
            params = {'cwd': str(root)}
            if resume_id:
                params['threadId'] = resume_id
            result = server.call('thread/resume' if resume_id else 'thread/start', params, timeout=min(30, deadline-time.monotonic()))
            thread = result.get('thread')
            if not isinstance(thread, dict) or not isinstance(thread.get('id'), str) or not thread['id']:
                raise ValueError('Codex did not return a native session ID; retry with --interactive.')
            server.thread_id = thread['id']
            progress.line(f'Codex configuration session: {server.thread_id}')
            if result.get('model'):
                progress.line(f"Model: {result['model']} (native Codex settings)")
            progress.phase('Analyzing the project and configuring its harness')
            server.call('turn/start', {'threadId': server.thread_id, 'input': [{'type': 'text', 'text': prompt}]}, timeout=min(30, deadline-time.monotonic()))
            while True:
                if not server.completed:
                    server.event(deadline)
                    continue
                turn = server.completed.popleft()
                if server.turn_id and turn.get('id') != server.turn_id:
                    continue
                if server.last_message:
                    progress.line(server.last_message)
                status = turn.get('status')
                if status == 'completed':
                    return 0
                if status == 'interrupted':
                    progress.outcome = 'interrupted'
                    return 130
                detail = turn.get('error') or {}
                raise ValueError('Codex configuration failed: ' + clean(detail.get('message', status)))
        except (KeyboardInterrupt, EOFError):
            if server.thread_id and server.turn_id:
                try:
                    server.call('turn/interrupt', {'threadId': server.thread_id, 'turnId': server.turn_id}, timeout=3)
                except (OSError, ValueError, TimeoutError):
                    pass
            progress.line('Configuration interrupted. Existing project files have been retained.')
            progress.outcome = 'interrupted'
            return 130
        finally:
            if server.thread_id:
                progress.line(f'To continue configuration: harness-codex config --resume {server.thread_id}')
            server.close()
