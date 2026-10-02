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
import re
from pathlib import Path
import secrets
import signal
import subprocess
import sys

from .model_routing import Context, Decision, classify, choose, catalog_entries, available_model, MAX_PROMPT

ALIAS = 'codex-auto-harness'
MAX_MESSAGE = 16 * 1024 * 1024


class SelectionRequired(ValueError):
    """A recoverable selection error; never forward or replay the user's task."""


def inference_error(message):
    error = message.get('error')
    if message.get('method') == 'error':
        error = (message.get('params') or {}).get('error')
    text = str((error or {}).get('message', ''))[:4096].casefold() if isinstance(error, dict) else ''
    return bool(re.search(r'model|reasoning|effort', text) and re.search(
        r'not found|not available|unavailable|no longer|does not exist|unsupported|not supported|invalid|not have access', text))


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
    def __init__(self, *, mode='manual', profiles=None, session_modes=None, remember=None, observer=None):
        self.mode, self.profiles = mode, profiles
        self.auto, self.contexts, self.catalog, self.aliases = dict(session_modes or {}), {}, [], {}
        self.default_model = self.default_effort = None
        self.pending_modes = {}
        self.raw_catalog, self.loaded, self.refresh_needed = [], False, False
        self.notices = []
        self.remember = remember or (lambda thread, enabled: None)
        self.observer = observer

    def observe(self, operation, *args, **kwargs):
        if self.observer is not None:
            try:
                return getattr(self.observer, operation)(*args, **kwargs)
            except Exception:
                self.observer = None
                self.warn(None, 'Adaptive routing evidence is unavailable; ordinary routing continues. Existing records were preserved.')
        return None

    def model_list(self, result, *, update=True):
        result = copy.deepcopy(result)
        entries = catalog_entries(result.get('data'))
        if result.get('nextCursor') or any(name.startswith(ALIAS) for name in entries):
            raise ValueError('Auto needs a complete, distinct model catalog; use native mode')
        if update:
            self.catalog = list(entries.values())
            self.raw_catalog, self.loaded, self.refresh_needed = copy.deepcopy(result['data']), True, False
        # Old aliases are display identifiers only; retain them to recognize a
        # removed selection until the UI has fetched its new menu.
        if not self.catalog:
            return result
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
        if len(self.aliases) > 2048:
            current = {item['model'] for item in aliases}
            obsolete = [name for name in self.aliases if name not in current]
            for name in obsolete[:len(self.aliases) - 2048]:
                del self.aliases[name]
        result['data'] = [first, *result['data'], *aliases]
        return result

    def real(self, model):
        if model == ALIAS:
            visible = {entry['model'] for entry in self.catalog}
            model = self.default_model if self.default_model in visible else next((x['model'] for x in self.catalog if x.get('isDefault')), None)
            return model
        return self.aliases.get(model, model)

    def warn(self, thread, text):
        self.notices.append({'method': 'warning', 'params': {'threadId': thread, 'message': text}})

    def seed(self, thread, settings):
        model = selected_model(settings)
        if model:
            effort = settings.get('reasoningEffort') or settings.get('effort') or settings.get('reasoning_effort')
            self.contexts[thread] = Context(model=self.real(model), effort=effort, active_task=True)

    def reconcile(self, method, result, auto):
        thread = result.get('threadId')
        context = self.contexts.get(thread, Context())
        explicit = self.real(selected_model(result))
        model = explicit or context.model or self.default_model
        if model is None:
            model = next((item['model'] for item in self.catalog if item.get('isDefault')), None)
        settings = (result.get('collaborationMode') or {}).get('settings') or {}
        effort = settings.get('reasoning_effort', result.get('effort'))
        if method in {'thread/start', 'thread/resume', 'thread/fork'}:
            effort = (result.get('config') or {}).get('model_reasoning_effort', effort)
        inherited = effort is None
        if effort is None:
            effort = context.effort if model == context.model else self.default_effort if model == self.default_model else None
        entries = catalog_entries(self.catalog)
        entry = entries.get(model)
        options = [item['reasoningEffort'] for item in entry.get('supportedReasoningEfforts', [])] if entry else []
        if entry and inherited and explicit and context.model and model != context.model:
            default = entry.get('defaultReasoningEffort')
            if default not in options:
                raise SelectionRequired('Select a supported reasoning level for the new model. No task was submitted.')
            effort = default
            if method in {'thread/start', 'thread/resume', 'thread/fork'}:
                result['config'] = {**(result.get('config') or {}), 'model_reasoning_effort': default}
            else:
                set_model(result, model, default)
        if entry and (effort is None or effort in options):
            return
        if not auto:
            raise SelectionRequired('The selected model or reasoning option is no longer available. Use /model to select an available pair; '
                'if resume cannot open, use codex --model MODEL resume SESSION_ID. No task was submitted.')
        replacement = available_model(model, self.raw_catalog, entries) or next((item for item in self.catalog if item.get('isDefault')), None)
        default = replacement.get('defaultReasoningEffort') if replacement else None
        if not replacement or default not in [item['reasoningEffort'] for item in replacement.get('supportedReasoningEfforts', [])]:
            raise SelectionRequired('Auto has no supported default model/reasoning pair. Select one with /model or use native mode. No task was submitted.')
        if method in {'thread/start', 'thread/resume', 'thread/fork'}:
            result['model'] = replacement['model']
            result['config'] = {**(result.get('config') or {}), 'model_reasoning_effort': default}
        else:
            set_model(result, replacement['model'], default)
        self.contexts[thread] = Context(tier=context.tier, model=replacement['model'], effort=default, active_task=context.active_task)
        self.warn(thread, 'Harness Auto replaced an unavailable model/reasoning selection with ' + replacement['model'] + ' / ' + default + '.')

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
        inference = method in {'thread/start', 'thread/resume', 'thread/fork', 'thread/settings/update', 'turn/start'}
        auto = selected == ALIAS or selected in self.aliases or self.enabled(thread)
        if method in {'thread/settings/update', 'thread/fork'} and selected:
            auto = selected == ALIAS or selected in self.aliases
        if method in {'config/batchWrite', 'config/value/write'}:
            edits = result.get('edits', []) if method == 'config/batchWrite' else [result]
            virtual = any(item.get('keyPath') == 'model' and (item.get('value') == ALIAS or item.get('value') in self.aliases) for item in edits)
            if virtual:
                kept = [edit for edit in edits if edit.get('keyPath') not in {'model', 'model_reasoning_effort'}]
                result = {key: value for key, value in result.items() if key not in {'keyPath', 'value', 'mergeStrategy'}}
                result['edits'] = kept
            return result
        if selected == ALIAS or selected in self.aliases:
            real = self.real(selected)
            if real:
                set_model(result, real)
        if inference and self.loaded:
            self.reconcile(method, result, auto)
        if method == 'thread/settings/update' and selected:
            self.pending_modes[thread] = selected == ALIAS or selected in self.aliases
        self.observe('request', method, result)
        if method == 'turn/start' and (selected == ALIAS or selected in self.aliases or self.enabled(thread)):
            if self.auto.get(thread) is not True:
                self.auto[thread] = True
                self.remember(thread, True)
            text = '\n'.join(item.get('text', '') for item in result.get('input', []) if item.get('type') in {'text', 'input_text'})
            # Image-only and large inputs retain native inference settings, never reject the user's task.
            has_images = any(item.get('type') in {'image', 'localImage'} for item in result.get('input', []))
            if text.strip() and '\0' not in text and len(text.encode()) <= MAX_PROMPT and not has_images:
                decision = choose(text, self.raw_catalog, context=self.contexts.get(thread, Context()), profiles=self.profiles)
                if decision.model:
                    decision = self.observe('decision', thread, text, decision, self.raw_catalog, self.contexts.get(thread, Context()), self.profiles, params=result) or decision
                    set_model(result, decision.model, decision.effort)
                    self.contexts[thread] = Context(tier=decision.tier, model=decision.model, effort=decision.effort,
                        active_task=True, lighter_requests=int(decision.reason == 'lighter-request-pending'))
        elif method == 'turn/start' and self.observer is not None:
            context = self.contexts.get(thread, Context())
            model = self.real(selected_model(result)) or context.model or self.default_model
            effort = ((result.get('collaborationMode') or {}).get('settings') or {}).get('reasoning_effort', result.get('effort'))
            effort = effort or context.effort or self.default_effort
            text = '\n'.join(item.get('text', '') for item in result.get('input', []) if item.get('type') in {'text', 'input_text'})
            entry = catalog_entries(self.raw_catalog).get(model)
            if (text.strip() and '\0' not in text and len(text.encode()) <= MAX_PROMPT
                    and not any(item.get('type') in {'image', 'localImage'} for item in result.get('input', []))
                    and entry and effort in [item['reasoningEffort'] for item in entry.get('supportedReasoningEfforts', [])]):
                tier, _ = classify(text, context)
                decision = Decision(tier, model, effort, 'manual-fixed', 'manual', False)
                self.observe('decision', thread, text, decision, self.raw_catalog, context, self.profiles, allow_advice=False, params=result)
        return result

    def display(self, settings, thread):
        if self.pending_modes.get(thread, self.enabled(thread)) and isinstance(settings, dict):
            real = selected_model(settings)
            alias = next((key for key, value in self.aliases.items() if value == real), None)
            if alias:
                set_model(settings, alias)

    def response(self, message, method, params):
        self.observe('response', message, method, params)
        if inference_error(message):
            self.refresh_needed = True
            self.warn(params.get('threadId') or (message.get('params') or {}).get('threadId'),
                'Harness will refresh model availability before the next request. No failed task was replayed. Review its outcome before retrying.')
        result = message.get('result')
        if method == 'config/read' and isinstance(result, dict):
            config = result.get('config') or {}
            self.default_model, self.default_effort = config.get('model'), config.get('model_reasoning_effort')
            self.default_model = self.real(self.default_model)
        if method == 'model/list' and isinstance(result, dict):
            message['result'] = self.model_list(result)
        if method == 'thread/settings/update' and 'result' in message:
            self.settings(params)
            settings = result.get('threadSettings', result) if isinstance(result, dict) else {}
            self.seed(params.get('threadId'), settings if selected_model(settings) else params)
        if method == 'thread/settings/update':
            self.pending_modes.pop(params.get('threadId'), None)
        if method in {'thread/start', 'thread/resume', 'thread/fork'} and isinstance(result, dict):
            thread = (result.get('thread') or {}).get('id')
            if thread:
                model = selected_model(result)
                effort = result.get('reasoningEffort') or result.get('effort')
                if model:
                    tier = 'deep' if effort in {'high', 'xhigh', 'max', 'ultra'} else 'fast' if effort in {'none', 'minimal', 'low'} else 'balanced'
                    self.contexts[thread] = Context(tier=tier, model=self.real(model), effort=effort, active_task=True)
                if selected_model(params) == ALIAS or selected_model(params) in self.aliases:
                    self.settings({**params, 'threadId': thread})
                elif method == 'thread/fork':
                    self.auto[thread] = False if selected_model(params) else params.get('_harnessForkAuto', self.enabled(params.get('threadId')))
                    self.remember(thread, self.auto[thread])
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
    management_controls = True

    def __init__(self, binary, env, *, args=(), policy=None):
        self.binary, self.env, self.args = str(binary), env, server_arguments(args)
        self.cwd = working_directory(args)
        self.policy = policy or Policy()
        self.token = secrets.token_urlsafe(32)
        self.auth_env = 'HARNESS_CODEX_RELAY_TOKEN_' + secrets.token_hex(8).upper()
        self.connected = False
        self.connection_lock = asyncio.Lock()
        self.error = None
        self.after_exit = None

    def client(self, port, args=()):
        command = [self.binary, '--remote', f'ws://127.0.0.1:{port}', '--remote-auth-token-env', self.auth_env, *args]
        return command, {**self.env, self.auth_env: self.token}

    async def connect(self, websocket):
        try:
            authorization = websocket.request.headers.get('Authorization', '')
        except ValueError:
            authorization = ''
        if (websocket.request.path != '/' or 'Origin' in websocket.request.headers
                or not secrets.compare_digest(authorization.encode(), ('Bearer ' + self.token).encode())):
            await websocket.close(code=1008, reason='Local Codex client required')
            return
        # The native resume/fork picker closes its metadata connection before
        # opening the conversation. Serialize teardown; never replay requests.
        try:
            await asyncio.wait_for(self.connection_lock.acquire(), 10)
        except asyncio.TimeoutError:
            await websocket.close(code=1013, reason='Previous Codex connection is still active')
            return
        self.connected = True
        try:
            await self.session(websocket)
        except OSError:
            self.error = 'The Codex backend could not start. Check the installed executable or use native mode.'
            await websocket.close(code=1011, reason='Codex backend unavailable')
        finally:
            self.policy.pending_modes.clear()
            self.connected = False
            self.connection_lock.release()

    async def session(self, websocket):
        pending = {}
        internal = {}
        prefix = 'harness-catalog-' + secrets.token_hex(8) + '-'
        sequence = 0
        process = await asyncio.create_subprocess_exec(self.binary, *self.args, 'app-server', '--listen', 'stdio://',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env=self.env, cwd=self.cwd, limit=MAX_MESSAGE, start_new_session=True)

        async def write(message):
            process.stdin.write((json.dumps(message) + '\n').encode())
            await process.stdin.drain()

        async def call(method, params, *, raw=False):
            nonlocal sequence
            sequence += 1
            identity = prefix + str(sequence)
            future = asyncio.get_running_loop().create_future()
            internal[identity] = future
            try:
                await write({'id': identity, 'method': method, 'params': params})
                response = await asyncio.wait_for(future, 15)
                if raw:
                    return response
                if 'error' in response:
                    raise SelectionRequired('Codex metadata is unavailable. Use native mode or retry the metadata lookup; no task was submitted.')
                return response.get('result') or {}
            finally:
                internal.pop(identity, None)

        async def refresh():
            data, cursors, cursor = [], set(), None
            for _ in range(20):
                params = {'limit': 50, 'includeHidden': True}
                if cursor:
                    params['cursor'] = cursor
                page = await call('model/list', params)
                catalog_entries(page.get('data'))
                data.extend(page['data'])
                cursor = page.get('nextCursor')
                if cursor is None:
                    self.policy.model_list({'data': data, 'nextCursor': None})
                    return
                if not isinstance(cursor, str) or not cursor or cursor in cursors or len(data) > 1000:
                    break
                cursors.add(cursor)
            raise SelectionRequired('Codex model catalog pagination did not finish. No task was submitted.')

        async def notices():
            while self.policy.notices:
                await websocket.send(json.dumps(self.policy.notices.pop(0)))

        from .management_relay import Controls
        async def send(message):
            await websocket.send(json.dumps(message))
        async def submit(params):
            if not self.policy.loaded or self.policy.refresh_needed:
                await asyncio.wait_for(refresh(), 20)
            request = self.policy.request('turn/start', params)
            response = await call('turn/start', request, raw=True)
            self.policy.response(response, 'turn/start', params)
            await notices()
            if 'error' in response:
                raise SelectionRequired('Codex did not confirm the requested turn. Inspect the conversation before retrying.')
        controls = Controls(self, send, call, submit)

        async def incoming():
            async for raw in websocket:
                message = json.loads(raw)
                method, params = message.get('method'), message.get('params') or {}
                if method and 'id' in message:
                    if len(pending) >= 1024 or message['id'] in pending or str(message['id']).startswith(prefix):
                        raise ValueError('Unsupported outstanding Codex requests')
                try:
                    if await controls.intercept(message):
                        continue
                    params = message.get('params') or {}
                    if method == 'model/list':
                        await asyncio.wait_for(refresh(), 20)
                        data = self.policy.raw_catalog
                        if not params.get('includeHidden'):
                            data = [item for item in data if not item.get('hidden')]
                        result = self.policy.model_list({'data': data, 'nextCursor': None}, update=False)
                        await websocket.send(json.dumps({'id': message['id'], 'result': result}))
                        continue
                    if method in {'thread/start', 'thread/resume', 'thread/fork', 'thread/settings/update', 'turn/start'}:
                        if not self.policy.loaded or self.policy.refresh_needed:
                            await asyncio.wait_for(refresh(), 20)
                        if method in {'thread/resume', 'thread/fork'} and params.get('threadId'):
                            saved = await call('thread/read', {'threadId': params['threadId'], 'includeTurns': False})
                            self.policy.seed(params['threadId'], saved.get('thread') or {})
                    if method and 'params' in message:
                        message['params'] = self.policy.request(method, params)
                        if method == 'config/value/write' and 'edits' in message['params']:
                            message['method'] = 'config/batchWrite'
                except (ValueError, TimeoutError) as error:
                    if 'id' not in message:
                        raise
                    await websocket.send(json.dumps({'id': message['id'], 'error': {'code': -32602,
                        'message': str(error) or 'Model metadata lookup timed out; no task was submitted.'}}))
                    continue
                if method and 'id' in message:
                    pending[message['id']] = (method, copy.deepcopy(params))
                    if method == 'thread/fork':
                        pending[message['id']][1]['_harnessForkAuto'] = self.policy.enabled(params.get('threadId'))
                await notices()
                await write(message)

        async def outgoing():
            while raw := await process.stdout.readline():
                message = json.loads(raw)
                identity = message.get('id')
                if 'method' not in message and isinstance(identity, str) and identity.startswith(prefix):
                    future = internal.get(identity)
                    if future is not None and not future.done():
                        future.set_result(message)
                    continue
                # Server requests also have IDs; they are never client responses.
                method, params = pending.pop(message.get('id'), (None, {})) if 'method' not in message else (None, {})
                await controls.observe(message)
                await websocket.send(json.dumps(self.policy.response(message, method, params)))
                await notices()

        tasks = [asyncio.create_task(incoming()), asyncio.create_task(outgoing())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except Exception:
            self.error = 'Codex protocol connection ended unexpectedly. Resume in native mode; no automatic replay was attempted.'
        finally:
            await controls.close()
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
    while True:
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
        selected = relay.after_exit
        if code or not selected:
            return code
        if selected['action'] in {'update', 'uninstall', 'jev'}:
            action = selected['action']
            arguments = [action] if action != 'jev' else ['jev', selected['operation'], '--project', selected['root']]
            command = [sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'harness.py'), '--no-update-check', *arguments]
            process = await asyncio.create_subprocess_exec(*command, env=env)
            return await process.wait()
        from .paths import project_root, project_target
        if selected['action'] == 'configure':
            root = project_target(selected['root'])
            if str(root) != selected['root']:
                raise ValueError('Queued project location changed; configuration was not started.')
            if not root.exists():
                command = [sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'harness.py'), '--no-update-check', 'init', '--install-only', '--project', str(root)]
                process = await asyncio.create_subprocess_exec(*command, env=env)
                code = await process.wait()
                if code:
                    return code
        else:
            root = project_root(selected['root'])
        from .workspace_context import PATH as context_path, prepare
        if (root / context_path).is_file():
            prepare(root, [str(binary)])
        # A new native launch reads the target instructions and permission policy.
        # Never carry the source conversation's flags, input or sandbox overrides.
        args = ['-c', 'check_for_update_on_startup=false', '--cd', str(root)]
        if selected['action'] == 'configure':
            import shlex
            arguments = selected['arguments'] or ['--goal', 'Inspect the project evidence and ask about any unclear purpose before generating a harness.']
            args += ['--', '/harness/' + selected['command'] + ' ' + shlex.join(['--project', str(root), *arguments])]
        elif selected['resume']:
            args += ['resume']
        if policy.observer is not None:
            policy.observer.cwd = root
        policy.refresh_needed = True
