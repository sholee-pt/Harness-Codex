"""Inference-only adapter for the official Codex TUI/app-server protocol.

No conversation renderer, user-turn injection, permission overrides or prompt
logs. Virtual model IDs exist only on the local TUI side of the connection.
"""
from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys

from .model_routing import Context, choose, catalog_entries, MAX_PROMPT

ALIAS = 'codex-auto-harness'
MAX_MESSAGE = 16 * 1024 * 1024


def dependency(*, install=False):
    try:
        from websockets.asyncio.server import serve
        return serve
    except ImportError:
        if not install:
            raise ValueError('Auto transport is unavailable; run harness-codex config to prepare it')
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
                        'websockets==15.0.1'], check=True, timeout=120, stdout=subprocess.DEVNULL)
        for name in list(sys.modules):
            if name == 'websockets' or name.startswith('websockets.'):
                del sys.modules[name]
        importlib.invalidate_caches()
    from websockets.asyncio.server import serve
    return serve


def selected_model(params):
    return ((params.get('collaborationMode') or {}).get('settings') or {}).get('model') or params.get('model')


def set_model(params, model, effort=None):
    params['model'] = model
    if effort is not None:
        params['effort'] = effort
    settings = (params.get('collaborationMode') or {}).get('settings')
    if isinstance(settings, dict):
        settings['model'] = model
        if effort is not None:
            settings['reasoning_effort'] = effort


class Policy:
    def __init__(self, *, mode='manual', profiles=None, session_modes=None, remember=None):
        self.mode, self.profiles = mode, profiles
        self.auto, self.contexts, self.catalog, self.aliases = dict(session_modes or {}), {}, [], {}
        self.default_model = self.default_effort = None
        self.pending_modes = {}
        self.remember = remember or (lambda thread, enabled: None)

    def model_list(self, result):
        result = copy.deepcopy(result)
        entries = catalog_entries(result.get('data'))
        if not entries or result.get('nextCursor') or any(name.startswith(ALIAS) for name in entries):
            raise ValueError('Auto needs a complete, distinct model catalog; use native mode')
        self.catalog = list(entries.values())
        first = copy.deepcopy(self.catalog[0])
        first.update(id=ALIAS, model=ALIAS, displayName='Auto', hidden=False, isDefault=False,
            description='Harness selects model and reasoning for each request.', defaultReasoningEffort='medium',
            supportedReasoningEfforts=[{'reasoningEffort': 'medium', 'description': 'Selected automatically per request'}])
        aliases = []
        for index, entry in enumerate(self.catalog):
            name = ALIAS + '-' + entry['model']
            self.aliases[name] = entry['model']
            alias = copy.deepcopy(entry)
            alias.update(id=name, model=name, hidden=True, isDefault=False,
                         displayName='Auto selected: ' + entry.get('displayName', entry['model']))
            aliases.append(alias)
        result['data'] = [first, *result['data'], *aliases]
        return result

    def real(self, model):
        if model == ALIAS:
            visible = {entry['model'] for entry in self.catalog}
            model = self.default_model if self.default_model in visible else next((x['model'] for x in self.catalog if x.get('isDefault')), None)
            return model or (self.catalog[0]['model'] if self.catalog else None)
        return self.aliases.get(model, model)

    def enabled(self, thread):
        return self.auto.get(thread, self.mode == 'auto')

    def settings(self, params):
        model = selected_model(params)
        if model:
            thread = params['threadId']
            self.auto[thread] = model == ALIAS or model in self.aliases
            self.remember(thread, self.auto[thread])

    def request(self, method, params):
        result = copy.deepcopy(params)
        selected = selected_model(result)
        thread = result.get('threadId')
        if method in {'config/batchWrite', 'config/value/write'}:
            edits = result.get('edits', []) if method == 'config/batchWrite' else [result]
            virtual = any(item.get('keyPath') == 'model' and (item.get('value') == ALIAS or item.get('value') in self.aliases) for item in edits)
            if virtual:
                kept = [edit for edit in edits if edit.get('keyPath') not in {'model', 'model_reasoning_effort'}]
                result = {key: value for key, value in result.items() if key not in {'keyPath', 'value', 'mergeStrategy'}}
                result['edits'] = kept
            return result
        if method == 'thread/settings/update' and selected:
            self.pending_modes[thread] = selected == ALIAS or selected in self.aliases
        if selected == ALIAS or selected in self.aliases:
            real = self.real(selected)
            if not real:
                raise ValueError('Auto has no available real model')
            set_model(result, real)
        if method == 'turn/start' and (selected == ALIAS or selected in self.aliases or self.enabled(thread)):
            if self.auto.get(thread) is not True:
                self.auto[thread] = True
                self.remember(thread, True)
            text = '\n'.join(item.get('text', '') for item in result.get('input', []) if item.get('type') in {'text', 'input_text'})
            # Image-only and large inputs retain native inference settings, never reject the user's task.
            has_images = any(item.get('type') in {'image', 'localImage'} for item in result.get('input', []))
            if text.strip() and '\0' not in text and len(text.encode()) <= MAX_PROMPT and not has_images:
                decision = choose(text, self.catalog, context=self.contexts.get(thread, Context()), profiles=self.profiles)
                if decision.model:
                    set_model(result, decision.model, decision.effort)
                    self.contexts[thread] = Context(tier=decision.tier, model=decision.model, effort=decision.effort,
                        active_task=True, lighter_requests=int(decision.reason == 'lighter-request-pending'))
        return result

    def display(self, settings, thread):
        if self.pending_modes.get(thread, self.enabled(thread)) and isinstance(settings, dict):
            real = selected_model(settings)
            alias = next((key for key, value in self.aliases.items() if value == real), None)
            if alias:
                set_model(settings, alias)

    def response(self, message, method, params):
        result = message.get('result')
        if method == 'config/read' and isinstance(result, dict):
            config = result.get('config') or {}
            self.default_model, self.default_effort = config.get('model'), config.get('model_reasoning_effort')
            self.default_model = self.real(self.default_model)
        if method == 'model/list' and isinstance(result, dict):
            message['result'] = self.model_list(result)
        if method == 'thread/settings/update' and 'result' in message:
            self.settings(params)
        if method == 'thread/settings/update':
            self.pending_modes.pop(params.get('threadId'), None)
        if method in {'thread/start', 'thread/resume'} and isinstance(result, dict):
            thread = (result.get('thread') or {}).get('id')
            if thread:
                model = selected_model(result)
                effort = result.get('reasoningEffort') or result.get('effort')
                if method == 'thread/resume' and model and effort:
                    tier = 'deep' if effort in {'high', 'xhigh', 'max', 'ultra'} else 'fast' if effort in {'none', 'minimal', 'low'} else 'balanced'
                    self.contexts[thread] = Context(tier=tier, model=self.real(model), effort=effort, active_task=True)
                if selected_model(params) == ALIAS or selected_model(params) in self.aliases:
                    self.settings({**params, 'threadId': thread})
                self.display(result, thread)
        if message.get('method') == 'thread/settings/updated':
            event = message.get('params') or {}
            self.display(event.get('threadSettings'), event.get('threadId'))
        return message


def native_arguments(args):
    """Read native options without treating their values or escaped prompts as flags."""
    valued = {'-c', '--config', '-C', '--cd', '-m', '--model', '-p', '--profile', '-s', '--sandbox',
              '-a', '--ask-for-approval', '-i', '--image', '--enable', '--disable', '--add-dir',
              '--local-provider', '--remote', '--remote-auth-token-env'}
    index = 0
    while index < len(args):
        value = args[index]
        index += 1
        if value == '--':
            return
        if value.startswith('--') and '=' in value:
            yield tuple(value.split('=', 1))
        elif not value.startswith('--') and len(value) > 2 and value[:2] in valued:
            yield value[:2], value[2:].removeprefix('=')
        elif value in valued:
            argument = args[index] if index < len(args) else None
            index += 1
            yield value, argument
        else:
            yield (value, None) if value.startswith('-') else (None, value)


def profile_requested(args):
    return any(option in {'-p', '--profile'} for option, _ in native_arguments(args))


def server_arguments(args):
    """Forward native configuration flags, never invent sandbox or approval settings."""
    result = []
    for option, value in native_arguments(args):
        if option in {'-p', '--profile'}:
            raise ValueError('Selected profiles require native Codex; the Auto backend cannot preserve profile settings')
        if option in {'-c', '--config', '--enable', '--disable'}:
            if value is None:
                raise ValueError('Missing native configuration argument')
            result += [option, value]
    return result


def working_directory(args):
    directory = Path.cwd()
    for option, value in native_arguments(args):
        if option in {'-C', '--cd'} and value is not None:
            directory = Path(value).expanduser().absolute()
    return directory


class Relay:
    def __init__(self, binary, env, *, args=(), policy=None):
        self.binary, self.env, self.args = str(binary), env, server_arguments(args)
        self.cwd = working_directory(args)
        self.policy = policy or Policy()
        self.token = secrets.token_urlsafe(32)
        self.auth_env = 'HARNESS_CODEX_RELAY_TOKEN_' + secrets.token_hex(8).upper()
        self.connected = False
        self.error = None

    def client(self, port, args=()):
        command = [self.binary, '--remote', f'ws://127.0.0.1:{port}', '--remote-auth-token-env', self.auth_env, *args]
        return command, {**self.env, self.auth_env: self.token}

    async def connect(self, websocket):
        try:
            authorization = websocket.request.headers.get('Authorization', '')
        except ValueError:
            authorization = ''
        if (self.connected or websocket.request.path != '/' or 'Origin' in websocket.request.headers
                or not secrets.compare_digest(authorization.encode(), ('Bearer ' + self.token).encode())):
            await websocket.close(code=1008, reason='Local Codex client required')
            return
        self.connected = True
        pending = {}
        process = await asyncio.create_subprocess_exec(self.binary, *self.args, 'app-server', '--listen', 'stdio://',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env=self.env, cwd=self.cwd, limit=MAX_MESSAGE, start_new_session=True)

        async def incoming():
            async for raw in websocket:
                message = json.loads(raw)
                method, params = message.get('method'), message.get('params') or {}
                if method and 'id' in message:
                    if len(pending) >= 1024 or message['id'] in pending:
                        raise ValueError('Unsupported outstanding Codex requests')
                    pending[message['id']] = (method, copy.deepcopy(params))
                if method and 'params' in message:
                    message['params'] = self.policy.request(method, params)
                    if method == 'config/value/write' and 'edits' in message['params']:
                        message['method'] = 'config/batchWrite'
                process.stdin.write((json.dumps(message) + '\n').encode())
                await process.stdin.drain()

        async def outgoing():
            while raw := await process.stdout.readline():
                message = json.loads(raw)
                # Server requests also have IDs; they are never client responses.
                method, params = pending.pop(message.get('id'), (None, {})) if 'method' not in message else (None, {})
                await websocket.send(json.dumps(self.policy.response(message, method, params)))

        tasks = [asyncio.create_task(incoming()), asyncio.create_task(outgoing())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except Exception:
            self.error = 'Codex protocol connection ended unexpectedly. Resume in native mode; no automatic replay was attempted.'
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if process.returncode is None:
                if os.name == 'posix':
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except asyncio.TimeoutError:
                    if os.name == 'posix':
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    await process.wait()
            await websocket.close()


async def run(binary, args, env, policy):
    serve = dependency()
    relay = Relay(binary, env, args=args, policy=policy)
    async with serve(relay.connect, '127.0.0.1', 0, max_size=MAX_MESSAGE, max_queue=16, compression=None) as server:
        port = server.sockets[0].getsockname()[1]
        command, client_env = relay.client(port, args)
        process = await asyncio.create_subprocess_exec(*command, env=client_env)
        try:
            code = await process.wait()
        finally:
            if process.returncode is None:
                process.terminate()
                await process.wait()
    if relay.error:
        print(relay.error, file=sys.stderr)
        return code or 1
    return code
