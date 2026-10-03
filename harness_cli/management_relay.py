"""User-requested /harness/ controls over the native protocol, without inference for queries.

The qualified namespace passes the native path-input parser. It is not a new
built-in slash menu and does not intercept terminal keys or relax permissions.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shlex
import signal
import sys
import uuid

from . import presentation as ui
from .paths import project_root

COMMANDS = ('status', 'settings', 'init', 'config', 'maintenance', 'doctor', 'routing', 'jev', 'graft', 'switch', 'update', 'remove', 'reset', 'tool', 'help')
REVIEW_PROMPT = (
    'Review this project\'s eligible Harness maintenance concerns using its installed maintenance workflow. '
    'Read current status first. Respect existing off/suggest/auto mode, review leases, budgets, active sessions and existing-skill scope. '
    'Do not manufacture a concern or bypass a limit. If no review is eligible, report that without regenerating the harness. '
    'Use the current conversation permissions and record the actual outcome; do not claim measured savings without evidence.')


def manifest_stamp(root):
    try:
        info = (root / '.harness/manifest.json').stat()
        return info.st_mtime_ns, info.st_ctime_ns, info.st_size
    except OSError:
        return None


def parse(params):
    items = params.get('input')
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict) or items[0].get('type') != 'text':
        return None
    text = items[0].get('text', '')
    if not isinstance(text, str) or not text.startswith('/harness/'):
        return None
    if len(text) > 8192 or '\n' in text or '\r' in text:
        raise ValueError('Use one bounded /harness/ command; quote ordinary discussion of this namespace.')
    arguments = shlex.split(text[len('/harness/'):])
    command = arguments.pop(0) if arguments else 'help'
    if command not in COMMANDS:
        raise ValueError('Unknown Harness command. Use /harness/help.')
    return command, arguments


class Controls:
    def __init__(self, relay, send, call, submit=None):
        self.relay, self.send, self.call = relay, send, call
        self.submit = submit
        self.source = Path(__file__).resolve().parents[1]
        self.tasks, self.answers, self.busy, self.configuring = {}, {}, set(), {}
        self.completions, self.completion_turns = {}, {}
        self.prefix = 'harness-control-' + uuid.uuid4().hex + '-'

    async def event(self, method, **params):
        await self.send({'method': method, 'params': params})

    async def cwd(self, thread):
        result = await self.call('thread/read', {'threadId': thread, 'includeTurns': False})
        cwd = (result.get('thread') or {}).get('cwd')
        if not isinstance(cwd, str):
            raise ValueError('Codex did not report the conversation directory; no project was selected.')
        return project_root(cwd)

    async def root(self, params):
        location = await self.cwd(params['threadId'])
        # Match the nearest existing project harness, including launches in children.
        for root in (location, *location.parents):
            if (root / '.harness/manifest.json').is_file():
                return root
        return location

    async def cli(self, root, arguments, *, timeout=60, global_command=False, output_limit=96 * 1024):
        env = {**self.relay.env, 'HARNESS_NO_UPDATE_CHECK': '1', 'PYTHONIOENCODING': 'utf-8'}
        starting = asyncio.create_task(asyncio.create_subprocess_exec(sys.executable, '-B', str(self.source / 'harness.py'),
            '--no-update-check', *arguments, *([] if global_command else ['--project', str(root)]), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env, cwd=root, start_new_session=True))
        interrupted = False
        while True:
            try:
                process = await asyncio.shield(starting)
                break
            except asyncio.CancelledError:
                if starting.cancelled():
                    raise
                interrupted = True
        chunks, length, truncated = [], 0, False
        async def output():
            nonlocal length, truncated
            while block := await process.stdout.read(4096):
                if len(block) > output_limit - length:
                    truncated = True
                if length < output_limit:
                    chunks.append(block[:output_limit - length])
                    length += len(chunks[-1])
            await process.wait()
        async def stop():
            if os.name == 'posix' or process.returncode is None:
                try:
                    if os.name == 'posix':
                        # Let Python helpers unwind and reap separately grouped
                        # npm, sandbox probes and native metadata subprocesses.
                        os.killpg(process.pid, signal.SIGINT)
                    else:
                        process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(output(), 15)
                except asyncio.TimeoutError:
                    pass
                finally:
                    # A completed leader does not establish that its children
                    # stopped; some helpers also close their inherited output.
                    try:
                        if os.name == 'posix':
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                    except ProcessLookupError:
                        pass
                    await asyncio.wait_for(process.wait(), 5)
        try:
            if interrupted:
                raise asyncio.CancelledError
            await asyncio.wait_for(output(), timeout)
        finally:
            cleanup = asyncio.create_task(stop())
            while True:
                try:
                    await asyncio.shield(cleanup)
                    break
                except asyncio.CancelledError:
                    if cleanup.cancelled():
                        raise
                    interrupted = True
            if interrupted:
                raise asyncio.CancelledError
        text = ui.clean(b''.join(chunks).decode('utf-8', errors='replace').replace('\r\n', '\n'))
        if truncated:
            raise ValueError('Management output exceeded its display limit. Inspect the project with the terminal CLI before continuing.')
        if process.returncode:
            raise ValueError(text[-12000:] or 'Harness command did not complete')
        return text

    async def ask(self, thread, turn, question, options=None):
        identity = self.prefix + uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.answers[identity] = future
        try:
            await self.send({'id': identity, 'method': 'item/tool/requestUserInput', 'params': {
                'threadId': thread, 'turnId': turn, 'itemId': identity, 'isBlocking': True,
                'questions': [{'id': 'choice', 'header': 'Harness', 'question': question, 'isOther': False, 'isSecret': False,
                               'options': [{'label': label, 'description': description} for label, description in options] if options is not None else None}]}})
            value = await future
            answers = (value.get('result', {}).get('answers', {}).get('choice') or {}).get('answers', [])
            if options is None and len(answers) == 1 and isinstance(answers[0], str):
                # Native free-text questions serialize their note with this prefix.
                answers = [answers[0].removeprefix('user_note: ')]
            if (len(answers) != 1 or not isinstance(answers[0], str) or not answers[0].strip()
                    or len(answers[0]) > 4000 or any(ord(c) < 32 and c not in '\n\t' for c in answers[0])
                    or options is not None and answers[0] not in [label for label, _ in options]):
                raise ValueError('No valid Harness input was confirmed; nothing further was applied.')
            return answers[0]
        finally:
            self.answers.pop(identity, None)

    async def choose(self, thread, turn, question, options):
        return await self.ask(thread, turn, question, options)

    async def enter(self, thread, turn, question):
        while True:
            value = (await self.ask(thread, turn, question)).strip()
            if '\n' not in value and '\r' not in value and '\t' not in value:
                return value
            await self.text(thread, turn, 'Use one line for this input. Choose a Markdown brief for longer project descriptions.')

    def queued_action(self, action=None):
        action = self.relay.after_exit if action is None else action
        if not action:
            return 'After exit: no action queued.'
        kind = action.get('action')
        label = {'switch': 'Open project conversation', 'configure': 'Configure project',
                 'update': 'Update Harness', 'uninstall': 'Uninstall Harness', 'jev': 'Private Jev ' + action.get('operation', '')}.get(kind, 'Unknown action')
        if action.get('root'):
            label += ': ' + ui.clean(action['root'])
        if kind == 'switch':
            label += ' (resume picker)' if action.get('resume') else ' (new conversation)'
        return 'After exit: ' + label + '. Use /quit when ready.'

    async def queue(self, thread, turn, action):
        current = self.relay.after_exit
        if current and current != action:
            choice = await self.choose(thread, turn, self.queued_action(current) + '\nRequested: ' + self.queued_action(action),
                [('Keep queued action', 'Preserve the existing reservation'), ('Replace queued action', 'Replace it with the displayed request')])
            if choice != 'Replace queued action':
                return False
        self.relay.after_exit = action
        return True

    def cancel_queued(self, kind):
        current = self.relay.after_exit
        if not current or current.get('action') != kind:
            return 'No ' + kind + ' action was cancelled.\n' + self.queued_action()
        self.relay.after_exit = None
        return 'Queued ' + kind + ' action cancelled.\n' + self.queued_action()

    async def configuration(self, params, root, command, arguments):
        from .management_wizard import goal_arguments
        from .project import _configuration_prompt, load_installer, _assert_no_transaction
        goal, _ = goal_arguments(root, arguments)
        _assert_no_transaction(root, load_installer(self.source))
        await self.cancel_completion(params['threadId'])
        await self.cli(root, ['init', '--install-only'], timeout=90)
        await self.call('skills/list', {'cwds': [str(root)], 'forceReload': True})
        self.configuring[params['threadId']] = (root, command, manifest_stamp(root))
        return {**params, 'cwd': str(root), 'input': [{'type': 'text', 'text': _configuration_prompt(goal)}]}

    async def text(self, thread, turn, text):
        item = {'id': self.prefix + uuid.uuid4().hex, 'type': 'agentMessage', 'text': text, 'phase': 'final', 'memoryCitation': None}
        await self.event('item/started', threadId=thread, turnId=turn, item={**item, 'text': ''})
        await self.event('item/agentMessage/delta', threadId=thread, turnId=turn, itemId=item['id'], delta=text)
        await self.event('item/completed', threadId=thread, turnId=turn, item=item)

    async def intercept(self, message):
        identity, method = message.get('id'), message.get('method')
        if method is None and isinstance(identity, str) and identity.startswith(self.prefix):
            future = self.answers.get(identity)
            if future is not None and not future.done():
                future.set_result(message)
            return True
        params = message.get('params') or {}
        if method == 'turn/interrupt' and params.get('turnId') in self.completion_turns:
            thread = self.completion_turns[params['turnId']]
            await self.cancel_completion(thread)
            await self.send({'id': identity, 'result': {}})
            return True
        if method == 'turn/interrupt' and params.get('turnId') in self.tasks:
            self.tasks[params['turnId']].cancel()
            await self.send({'id': identity, 'result': {}})
            return True
        if method not in {'turn/start', 'turn/steer'}:
            return False
        parsed = parse(params)
        if parsed is None:
            if self.tasks:
                raise ValueError('Finish or cancel the Harness menu before submitting another task.')
            return False
        if method == 'turn/steer' or self.busy or self.tasks:
            raise ValueError('Wait for the current task to finish before running Harness management.')
        command, arguments = parsed
        root = await self.root(params)
        if command in {'init', 'config'} and arguments:
            if arguments[0] == '--project' and len(arguments) >= 2:
                selected = project_root(root / Path(arguments[1]).expanduser())
                if selected != await self.cwd(params['threadId']):
                    raise ValueError('Use the Init menu to open another project with its own conversation and permissions.')
                root, arguments = selected, arguments[2:]
            if arguments and (arguments[0] not in {'--goal', '--goal-file'} or len(arguments) != 2):
                raise ValueError('Use /harness/' + command + ' [--goal "DESCRIPTION" | --goal-file "PATH"].')
            if command == 'init' and (root / '.harness/manifest.json').exists():
                command, arguments = 'status', []
            else:
                message['params'] = await self.configuration(params, root, command, arguments)
                return False
        if command == 'maintenance' and arguments == ['review']:
            message['params'] = {**params, 'input': [{'type': 'text', 'text': REVIEW_PROMPT}]}
            return False
        turn = str(uuid.uuid4())
        task = asyncio.create_task(self.handle(identity, params['threadId'], turn, root, command, arguments, params))
        self.tasks[turn] = task
        task.add_done_callback(lambda done: self.tasks.pop(turn, None))
        return True

    async def handle(self, identity, thread, turn, root, command, arguments, params=None):
        value = {'id': turn, 'items': [], 'status': 'inProgress', 'error': None}
        await self.send({'id': identity, 'result': {'turn': value}})
        await self.event('turn/started', threadId=thread, turn=value)
        status = 'completed'
        submission = None
        try:
            text = await self.execute(thread, turn, root, command, arguments)
            if isinstance(text, dict) and 'configuration' in text:
                if self.submit is None:
                    raise ValueError('Native configuration submission is unavailable; no model task was started.')
                submission = await self.configuration(params, *text['configuration'])
                text = 'Settings confirmed. Starting project configuration with this conversation model and permissions.'
            elif isinstance(text, dict) and 'review' in text:
                if self.submit is None:
                    raise ValueError('Native review submission is unavailable; no model task was started.')
                submission = {**params, 'input': [{'type': 'text', 'text': REVIEW_PROMPT}]}
                text = 'Starting the requested maintenance review with the current model and permissions.'
            await self.text(thread, turn, 'Harness management · local command\n\n```text\n' + text.replace('```', "'''") + '\n```')
        except asyncio.CancelledError:
            status = 'interrupted'
            self.configuring.pop(thread, None)
        except Exception as exc:
            status = 'failed'
            value['error'] = {'message': ui.clean(exc), 'codexErrorInfo': None, 'additionalDetails': None}
            self.configuring.pop(thread, None)
            await self.text(thread, turn, 'Harness management: ' + ui.clean(exc))
        finally:
            await self.event('turn/completed', threadId=thread, turn={**value, 'status': status})
        if submission is not None and status == 'completed':
            try:
                if self.submit is None:
                    raise ValueError('Native configuration submission is unavailable; no model task was started.')
                await self.submit(submission)
            except (OSError, ValueError, TimeoutError) as exc:
                self.configuring.pop(thread, None)
                await self.event('warning', threadId=thread, message='Configuration submission was not confirmed. Check the conversation before retrying; no automatic replay. ' + ui.clean(exc))

    async def execute(self, thread, turn, root, command, arguments, *, from_menu=False):
        if command == 'help':
            if arguments:
                raise ValueError('Use /harness/help without arguments.')
            from .management_wizard import menu
            return await menu(self, thread, turn, root)
        if command == 'settings' and not arguments:
            from .management_wizard import settings
            result = await settings(self, thread, turn, root)
            return result if result is not None or from_menu else 'No settings changed.'
        if command in {'remove', 'reset'}:
            if arguments not in ([], ['--include-generator']) or command == 'reset' and arguments:
                raise ValueError('Removal accepts only --include-generator; reset accepts no arguments.')
            plan = json.loads(await self.cli(root, ['remove', *arguments, '--dry-run', '--json'], output_limit=4 * 1024 * 1024))
            if not plan.get('actions'):
                return 'No owned files to remove. Use /harness/init to configure the project.'
            preview = '\n'.join(item['action'] + ': ' + item['path'] for item in plan['actions'])
            await self.text(thread, turn, '```text\n' + preview.replace('```', "'''") + '\n```')
            choice = await self.choose(thread, turn, 'Remove only the displayed owned project files?', [('Remove', 'Apply the reviewed removal'), ('Back', 'Preserve all files')])
            if choice == 'Back':
                return None if from_menu else 'Removal cancelled; no files changed.'
            self.configuring.pop(thread, None)
            await self.cancel_completion(thread)
            result = await self.cli(root, ['remove', *arguments, '--yes', '--json', '--expected-plan', plan['planDigest']], output_limit=4 * 1024 * 1024)
            report = json.loads(result)
            from .project_cleanup import candidates, remove_empty
            selected = candidates(root, report)
            if report.get('state') != 'removed' or report.get('recoveryRequired'):
                return 'Removal needs attention. Use /harness/doctor before continuing.\n' + result
            if selected:
                choice = await self.choose(thread, turn, 'Owned files removed. Also remove empty component folders? User files and global Codex settings remain protected.',
                    [('Remove empty folders', 'Only empty parents of removed files'), ('Keep folders', 'Leave remaining directories in place')])
                if choice == 'Remove empty folders':
                    cleanup = await asyncio.to_thread(remove_empty, root, selected)
                    result = 'Empty folders removed: ' + str(len(cleanup['removed'])) + '; retained: ' + str(len(cleanup['retained']))
                else:
                    result = 'Remaining directories retained.'
            else:
                result = 'No empty component parents remain.'
            if command == 'reset':
                return 'Owned files removed. ' + result + '\nRun /harness/init to review the new design with the current model and permissions. No replacement was generated yet.'
            return 'Owned files removed. ' + result + '\nExisting conversation context may still contain old instructions; use a fresh conversation before further project work.'
        if command == 'switch':
            return await self.switch(thread, turn, root, arguments, from_menu=from_menu)
        if command == 'update':
            if arguments == ['--cancel']:
                return self.cancel_queued('update')
            if arguments not in ([], ['--check']):
                raise ValueError('Use /harness/update or /harness/update --check.')
            value = json.loads(await self.cli(root, ['update', '--check', '--json'], timeout=45, global_command=True))
            import io
            from contextlib import redirect_stdout
            with redirect_stdout(io.StringIO()) as output:
                ui.update_report(value)
            report = output.getvalue()
            if arguments or not value.get('updateAvailable'):
                return report + '\n' + self.queued_action()
            await self.text(thread, turn, report)
            choice = await self.choose(thread, turn, 'Install a Harness update after leaving this Codex screen?',
                [('Later', 'Keep this installation and conversation running'), ('Update after exit', 'Run the updater when you exit Codex normally')])
            if choice == 'Update after exit':
                if not await self.queue(thread, turn, {'action': 'update'}):
                    return 'Existing reservation retained.\n' + self.queued_action()
                return 'Update queued. Finish active work, then use /quit. Harness will update outside the conversation; launch codex again afterwards.'
            return 'No new update was queued.\n' + self.queued_action()
        if command in {'init', 'config'}:
            from .management_wizard import configure
            result = await configure(self, thread, turn, root, command)
            return result if result is not None or from_menu else 'Returned without configuring a project.'
        if command == 'tool' and not arguments:
            from .management_wizard import tools
            result = await tools(self, thread, turn, root, command)
            return result if result is not None or from_menu else 'No tool changes.'
        if command not in {'status', 'settings', 'doctor', 'maintenance', 'routing', 'jev', 'graft'}:
            raise ValueError('Unsupported local command')
        # Do not let command options redirect work away from the active conversation.
        if any(word.startswith(('--project', '--data-dir', '--codex-binary', '--hook', '--runtime', '--agent', '--json')) for word in arguments):
            raise ValueError('Project and runtime come from the current conversation. Use the CLI for another target.')
        if command == 'jev' and any(word in {'login', 'logout', '--replace-key'} for word in arguments):
            return 'Run harness-codex jev login/logout in your terminal. Never paste API keys into a Codex conversation.'
        if command == 'routing' and not arguments:
            arguments = ['--adaptive', 'status']
        if command == 'graft' and not arguments:
            arguments = ['status']
        result = await self.cli(root, [command, *arguments], timeout=180 if command == 'graft' else 60)
        return result + '\n' + self.queued_action() if command == 'status' else result

    async def switch(self, thread, turn, root, arguments, *, from_menu=False):
        if arguments == ['--cancel']:
            return self.cancel_queued('switch')
        from .management_wizard import switch
        result = await switch(self, thread, turn, root, arguments)
        return result if result is not None or from_menu else 'Project unchanged.'

    async def observe(self, message):
        method, params = message.get('method'), message.get('params') or {}
        thread = params.get('threadId')
        if method == 'turn/started':
            self.busy.add(thread)
        elif method == 'turn/completed':
            setup = self.configuring.get(thread)
            if setup:
                root, command, previous = setup
                if (params.get('turn') or {}).get('status') != 'completed':
                    self.configuring.pop(thread, None)
                else:
                    current = manifest_stamp(root)
                    if current is not None and current != previous and thread not in self.completions:
                        self.configuring[thread] = (root, command, current)
                        turn = params['turn']['id']
                        task = asyncio.create_task(self.finish_configuration(thread, turn, root, command, current))
                        self.completions[thread] = task
                        self.completion_turns[turn] = thread
            self.busy.discard(thread)

    async def finish_configuration(self, thread, turn, root, command, stamp):
        try:
            if await self.complete_init(thread, turn, root, command):
                if self.configuring.get(thread) == (root, command, stamp):
                    self.configuring.pop(thread, None)
        finally:
            self.completions.pop(thread, None)
            self.completion_turns.pop(turn, None)

    async def cancel_completion(self, thread):
        task = self.completions.get(thread)
        if task is not None:
            self.configuring.pop(thread, None)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.completions.pop(thread, None)
            for turn, owner in list(self.completion_turns.items()):
                if owner == thread:
                    self.completion_turns.pop(turn, None)

    async def complete_init(self, thread, turn, root, command):
        try:
            arguments = ['_complete-init' if command == 'init' else '_complete-config', '--codex-binary', self.relay.binary]
            result = await self.cli(root, arguments, timeout=240)
            observer = getattr(getattr(self.relay, 'policy', None), 'observer', None)
            if observer is not None:
                observer.managers.clear()
            await self.text(thread, turn, 'Harness configuration validation\n\n```text\n' + result.replace('```', "'''") + '\n```\nUse /harness/settings for preferences. Native agent loading still requires confirmation.')
            return True
        except (OSError, ValueError, TimeoutError) as exc:
            await self.text(thread, turn, 'Harness configuration not confirmed: ' + ui.clean(exc))
            return False

    async def close(self):
        tasks = [*self.tasks.values(), *self.completions.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.completions.clear()
        self.completion_turns.clear()
        for future in self.answers.values():
            if not future.done():
                future.cancel()
