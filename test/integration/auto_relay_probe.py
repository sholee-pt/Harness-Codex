"""Manual Linux feasibility experiment; no patched Codex and no paid model calls.

The official TUI and app-server are real. Only the local Responses provider is a
fixture. A completed experiment is not proof of live inference or full Auto UX.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from harness_cli.model_routing import Context, choose

ALIAS = 'codex-auto-harness'


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def text_input(items):
    if isinstance(items, str):
        return items
    return '\n'.join(item.get('text', '') for item in items or [] if item.get('type') in {'text', 'input_text'})


def input_digest(text):
    return hashlib.sha256(text.strip().encode()).hexdigest()


def footer_lines(screen):
    lines = screen.splitlines()
    prompts = [index for index, line in enumerate(lines) if re.match(r'^\s*›\s', line)]
    return [line.strip() for line in lines[prompts[-1] + 1:] if line.strip()] if prompts else []


def turn_evidence(relay, provider, thread_id, prompt):
    digest = input_digest(prompt)
    decisions = [item for item in relay.policy.decisions
                 if item.get('threadId') == thread_id and item.get('inputSha256') == digest]
    if not decisions or not decisions[-1].get('turnId'):
        return None
    decision = decisions[-1]
    completed = [event for event in relay.events if event.get('method') == 'turn/completed'
                 and event.get('threadId') == thread_id and event.get('turnId') == decision['turnId']]
    requests = [item for item in provider.records if item.get('inputSha256') == digest
                and item.get('threadId') == thread_id]
    if not completed or not requests:
        return None
    return {**decision, 'turnStatus': completed[-1].get('status')}, requests[-1]


def api(path):
    headers = {'User-Agent': 'Harness-Auto-feasibility-probe', 'Accept': 'application/vnd.github+json'}
    if os.environ.get('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    request = urllib.request.Request('https://api.github.com/repos/openai/codex/' + path, headers=headers)
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def official_package(release, output):
    from harness_cli.native_package import extract
    name = 'codex-package-x86_64-unknown-linux-musl.tar.gz'
    asset = next(item for item in release['assets'] if item['name'] == name)
    url = asset['browser_download_url']
    if not url.startswith('https://github.com/openai/codex/releases/download/'):
        raise ValueError('Unexpected official asset URL')
    archive = output / name
    with urllib.request.urlopen(url, timeout=90) as response, archive.open('wb') as stream:
        shutil.copyfileobj(response, stream)
    digest = sha256(archive)
    expected = asset.get('digest')
    if not isinstance(expected, str) or not expected.startswith('sha256:') or digest != expected[7:]:
        raise ValueError('Official asset digest missing or mismatched')
    extract(archive, output / 'official')
    binary = output / 'official/bin/codex'
    identity = {'tag': release['tag_name'], 'releaseUrl': release['html_url'],
                'assetUrl': url, 'archiveSha256': digest, 'binarySha256Before': sha256(binary),
                'version': subprocess.check_output([str(binary), '--version'], text=True).strip()}
    save(output / 'identity.json', identity)
    return binary, identity


class Provider(BaseHTTPRequestHandler):
    """A bounded, synthetic response; it never contacts a model provider."""
    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size < 4 * 1024 * 1024:
                raise ValueError('Unexpected fixture request size')
            body = self.rfile.read(size)
            if self.headers.get('Content-Encoding') == 'gzip':
                body = gzip.decompress(body)
            value = json.loads(body)
            sequence = len(self.server.records) + 1
            users = [item for item in value.get('input', []) if item.get('role') == 'user']
            prompt = text_input(users[-1].get('content')) if users else ''
            self.server.records.append({'model': value.get('model'), 'reasoning': value.get('reasoning'), 'sequence': sequence,
                'inputSha256': input_digest(prompt), 'threadId': self.headers.get('thread-id'),
                'sessionId': self.headers.get('session-id')})
            response_id, item_id = f'probe_response_{sequence}', f'probe_message_{sequence}'
            message = {'type': 'message', 'role': 'assistant', 'id': item_id,
                       'content': [{'type': 'output_text', 'text': f'PROBE_OK_{sequence}'}]}
            events = [
                {'type': 'response.created', 'response': {'id': response_id}},
                {'type': 'response.output_item.done', 'output_index': 0, 'item': message},
                {'type': 'response.completed', 'response': {'id': response_id, 'status': 'completed',
                    'output': [message], 'usage': {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}}},
            ]
            content = ''.join('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n' for event in events).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as exc:
            self.server.errors.append(str(exc))
            self.send_error(400, 'Fixture request failed')


class Policy:
    def __init__(self):
        self.catalog = []
        self.contexts, self.auto = {}, {}
        self.default_model = None
        self.config_rewrites = []
        self.decisions = []

    def model_list(self, result):
        result = copy.deepcopy(result)
        self.catalog = [entry for entry in result.get('data', []) if not entry.get('hidden')]
        if not self.catalog or any(entry.get('model') == ALIAS for entry in self.catalog):
            raise ValueError('Cannot add a distinct Auto fixture choice')
        alias = copy.deepcopy(self.catalog[0])
        alias.update(id=ALIAS, model=ALIAS, displayName='Auto', hidden=False, isDefault=False,
                     description='Harness experiment: choose model and reasoning per request.',
                     defaultReasoningEffort='medium', supportedReasoningEfforts=[
                         {'reasoningEffort': 'medium', 'description': 'Chosen by Harness during each request'}])
        result['data'].insert(0, alias)
        return result

    @staticmethod
    def selected_model(params):
        settings = (params.get('collaborationMode') or {}).get('settings') or {}
        return settings.get('model') or params.get('model')

    def settings(self, params):
        selected = self.selected_model(params)
        if selected:
            self.auto[params['threadId']] = selected == ALIAS

    def config_write(self, method, params):
        result = copy.deepcopy(params)
        edits = result.get('edits', []) if method == 'config/batchWrite' else [result]
        for edit in edits:
            if edit.get('keyPath') == 'model' and edit.get('value') == ALIAS:
                if not self.default_model or self.default_model == ALIAS:
                    raise ValueError('Cannot preserve the existing real default model')
                edit['value'] = self.default_model
                self.config_rewrites.append({'keyPath': 'model', 'replacement': self.default_model})
        return result

    def turn(self, params, request_id=None):
        result = copy.deepcopy(params)
        mode = result.get('collaborationMode') or {}
        settings = mode.get('settings') or {}
        selected = self.selected_model(result)
        thread_id = result['threadId']
        if selected == ALIAS:
            self.auto[thread_id] = True
        prompt = text_input(result.get('input'))
        identity = {'threadId': thread_id, 'requestId': request_id, 'inputSha256': input_digest(prompt)}
        if not self.auto.get(thread_id):
            self.decisions.append({**identity, 'auto': False, 'selected': selected, 'model': selected, 'effort': result.get('effort')})
            return result
        decision = choose(prompt, self.catalog, context=self.contexts.get(thread_id, Context()))
        if not decision.model or decision.model == ALIAS:
            raise ValueError('Auto failed to resolve to a real catalog model')
        result.update(decision.turn_overrides())
        if settings:
            settings['model'] = decision.model
            settings['reasoning_effort'] = decision.effort
        self.contexts[thread_id] = Context(tier=decision.tier, model=decision.model, effort=decision.effort, active_task=True)
        self.decisions.append({**identity, 'auto': True, **decision.report()})
        return result


class Relay:
    def __init__(self, binary, env, output):
        self.binary, self.env, self.output = binary, env, output
        self.policy = Policy()
        self.events, self.errors, self.thread_ids = [], [], []

    async def connect(self, websocket):
        pending = {}
        error_log = (self.output / f'app-server-{len(self.thread_ids)}.log').open('wb')
        process = await asyncio.create_subprocess_exec(str(self.binary), 'app-server', '--listen', 'stdio://',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=error_log, env=self.env, limit=16 * 1024 * 1024)

        async def incoming():
            async for raw in websocket:
                message = json.loads(raw)
                method = message.get('method')
                if method:
                    params = message.get('params') or {}
                    self.events.append({'direction': 'client', 'method': method, 'threadId': params.get('threadId'),
                                        'selectedModel': self.policy.selected_model(params)})
                    if 'id' in message:
                        pending[message['id']] = (method, copy.deepcopy(message.get('params') or {}))
                if method == 'turn/start':
                    message['params'] = self.policy.turn(message['params'], message['id'])
                if method in {'config/batchWrite', 'config/value/write'}:
                    message['params'] = self.policy.config_write(method, message['params'])
                process.stdin.write((json.dumps(message) + '\n').encode())
                await process.stdin.drain()

        async def outgoing():
            while raw := await process.stdout.readline():
                message = json.loads(raw)
                method, params = pending.pop(message.get('id'), (None, {})) if 'id' in message else (None, {})
                result = message.get('result') or {}
                if method == 'config/read':
                    model = (result.get('config') or {}).get('model')
                    if model and model != ALIAS:
                        self.policy.default_model = model
                if method == 'thread/settings/update' and 'result' in message:
                    self.policy.settings(params)
                if method == 'turn/start' and 'result' in message:
                    for decision in reversed(self.policy.decisions):
                        if decision['requestId'] == message['id'] and decision['threadId'] == params.get('threadId'):
                            decision['turnId'] = (result.get('turn') or {}).get('id')
                            break
                if method == 'model/list' and 'result' in message:
                    message['result'] = self.policy.model_list(message['result'])
                if method in {'thread/start', 'thread/resume'} and 'result' in message:
                    self.thread_ids.append(message['result']['thread']['id'])
                if message.get('method'):
                    event = message.get('params') or {}
                    turn = event.get('turn') or {}
                    self.events.append({'direction': 'server', 'method': message['method'], 'threadId': event.get('threadId'),
                                        'turnId': event.get('turnId') or turn.get('id'), 'status': turn.get('status')})
                if 'error' in message:
                    self.errors.append({'method': method, 'error': message['error']})
                await websocket.send(json.dumps(message))

        tasks = [asyncio.create_task(incoming()), asyncio.create_task(outgoing())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if not task.cancelled() and task.exception():
                    self.errors.append({'transport': str(task.exception())})
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            error_log.close()


class Terminal:
    def __init__(self, binary, args, env, output):
        import pexpect
        import pyte
        self.output = output
        self.screen = pyte.Screen(140, 42)
        self.stream = pyte.Stream(self.screen)
        self.control_tail = ''
        self.process = pexpect.spawn(str(binary), args, env=env, encoding='utf-8', codec_errors='replace', dimensions=(42, 140))
        self.raw = (output / 'terminal.ansi').open('w', encoding='utf-8')

    def read(self, seconds=0.5):
        import pexpect
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                data = self.process.read_nonblocking(65536, timeout=min(0.1, max(0.01, end - time.monotonic())))
                self.raw.write(data)
                self.raw.flush()
                self.stream.feed(data)
                control = self.control_tail + data
                self.control_tail = control[-3:]
                if '\x1b[6n' in control:
                    self.process.send('\x1b[1;1R')
                if '\x1b[c' in control:
                    self.process.send('\x1b[?1;2c')
            except pexpect.TIMEOUT:
                pass
            except pexpect.EOF:
                break
        return '\n'.join(self.screen.display)

    def snapshot(self, name):
        text = self.read(0.8)
        (self.output / (name + '.txt')).write_text(text + '\n', encoding='utf-8')
        return text

    def wait(self, predicate, seconds=30):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            text = self.read(0.25)
            if predicate(text):
                return text
            if not self.process.isalive():
                break
        self.snapshot('timeout')
        raise TimeoutError('Terminal did not reach the expected state; inspect timeout.txt and terminal.ansi')

    def command(self, text):
        self.process.send(text)
        self.read(0.3)
        self.process.send('\r')
        self.read(0.8)

    def startup(self, relay):
        dismissed = []

        def ready(text):
            if not dismissed and 'Try new model' in text and 'Use existing model' in text:
                self.snapshot('00-model-announcement')
                self.select('Use existing model')
                dismissed.append('Use existing model')
                return False
            return bool(relay.thread_ids) and 'Connecting' not in text

        self.wait(ready)
        return dismissed

    def select(self, label):
        text = self.read(0.4)
        rows = [line for line in text.splitlines() if re.search(r'\b\d+\.\s', line)]
        pattern = r'\b\d+\.\s+' + re.escape(label) + r'(?:\s{2,}|\s+\((?:current|default)\)|\s*$)'
        matches = [(index, line) for index, line in enumerate(rows) if re.search(pattern, line)]
        if len(matches) != 1:
            raise ValueError('Picker entry not visible: ' + label)
        self.process.send('\x1b[H')
        self.read(0.2)
        self.process.send('\x1b[B' * matches[0][0])
        self.read(0.2)
        self.process.send('\r')
        self.read(0.8)

    def close(self):
        if self.process.isalive():
            self.process.sendcontrol('c')
            self.read(0.3)
            self.process.sendcontrol('c')
            self.read(0.3)
            self.process.terminate(force=True)
        self.raw.close()


def drive(binary, env, project, output, port, relay, provider):
    terminal = Terminal(binary, ['--remote', f'ws://127.0.0.1:{port}', '--no-alt-screen', '-C', str(project)], env, output)
    findings = {'realModelInference': 'not-tested; local synthetic Responses provider', 'linuxTui': True}
    try:
        findings['startupChoices'] = terminal.startup(relay)
        thread_id = relay.thread_ids[0]
        findings['mainThreadId'] = thread_id
        terminal.snapshot('01-startup')
        terminal.command('/model')
        terminal.wait(lambda text: 'select model' in text.lower())
        menu = terminal.snapshot('02-model-menu')
        findings['autoMenuLabel'] = 'Auto' if re.search(r'\b\d+\.\s+Auto(?:\s{2,}|\s+\((?:current|default)\)|\s*$)', menu, re.MULTILINE) else ALIAS if ALIAS in menu else None
        findings['exactAutoLabel'] = findings['autoMenuLabel'] == 'Auto'
        position = re.search(r'\b(\d+)\.\s+' + re.escape(findings['autoMenuLabel'] or 'UNAVAILABLE') + r'\b', menu)
        findings['autoMenuPosition'] = int(position[1]) if position else None
        terminal.select(findings['autoMenuLabel'] or 'Auto')
        selected = terminal.snapshot('03-auto-selected')
        findings['autoSelectedFooter'] = footer_lines(selected)
        try:
            import tomllib
            settings = tomllib.loads((Path(env['CODEX_HOME']) / 'config.toml').read_text())
            findings['virtualModelPersistedAsDefault'] = settings.get('model') == ALIAS
        except (OSError, ValueError):
            findings['virtualModelPersistedAsDefault'] = 'unavailable'
        prompts = ['New task: Fix a typo in README.',
                   'New task: Investigate a distributed concurrency race and design a cross-service architecture migration.']
        for index, prompt in enumerate(prompts, 1):
            terminal.command(prompt)
            terminal.wait(lambda text: turn_evidence(relay, provider, thread_id, prompt) is not None, 45)
            screen = terminal.snapshot(f'04-turn-{index}')
            decision, received = turn_evidence(relay, provider, thread_id, prompt)
            footer = footer_lines(screen)
            model, effort = decision.get('model'), decision.get('effort')
            findings[f'turn{index}'] = {'decision': decision, 'providerRequest': received, 'footer': footer,
                'turnCompleted': decision.get('turnStatus') == 'completed',
                'modelReachedProvider': bool(model) and received['model'] == model,
                'effortReachedProvider': bool(effort) and (received.get('reasoning') or {}).get('effort') == effort,
                'footerShowsActualModel': bool(model) and any(model in line for line in footer),
                'footerShowsActualEffort': bool(effort) and any(effort.lower() in line.lower() for line in footer),
                'footerShowsAuto': any('auto' in line.lower() for line in footer)}
        main_decisions = [findings[f'turn{index}']['decision'] for index in (1, 2)]
        findings['autoMaintainedAcrossTurns'] = all(item['auto'] for item in main_decisions)
        findings['twoDistinctPairs'] = len({(item.get('model'), item.get('effort')) for item in main_decisions if item['auto']}) == 2
        findings['menuRoutingFooterSatisfied'] = (findings['exactAutoLabel'] and findings['autoMenuPosition'] == 1
            and findings['autoMaintainedAcrossTurns'] and findings['twoDistinctPairs']
            and findings['virtualModelPersistedAsDefault'] is False and all(
            findings[f'turn{index}'][key] for index in (1, 2)
            for key in ('turnCompleted', 'modelReachedProvider', 'effortReachedProvider', 'footerShowsActualModel', 'footerShowsActualEffort', 'footerShowsAuto')))
        findings['fullRequestedUX'] = 'not-established' if findings['menuRoutingFooterSatisfied'] else False
        findings['resumeAndApprovals'] = 'not-tested; this first-stage probe does not establish production compatibility'
    except Exception as exc:
        findings['experimentError'] = str(exc)
        findings['traceback'] = traceback.format_exc()
        terminal.snapshot('error-screen')
    finally:
        terminal.close()
    return findings


async def experiment(binary, output):
    from websockets.asyncio.server import serve
    home, project = output / 'home', output / 'project'
    home.mkdir()
    project.mkdir()
    (project / 'README.md').write_text('Synthetic Auto feasibility fixture.\n', encoding='utf-8')
    provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    provider.records, provider.errors = [], []
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    config = ('model = "gpt-5.6-sol"\nmodel_provider = "probe"\nmodel_reasoning_effort = "medium"\n'
              'approval_policy = "never"\nsandbox_mode = "read-only"\n'
              '[tui]\nstatus_line = ["model-with-reasoning"]\n'
              '[model_providers.probe]\nname = "Local synthetic fixture"\n'
              f'base_url = "http://127.0.0.1:{provider.server_port}/v1"\n'
              'wire_api = "responses"\nrequires_openai_auth = false\nsupports_websockets = false\n'
              f'[projects.{json.dumps(str(project))}]\ntrust_level = "trusted"\n')
    (home / 'config.toml').write_text(config, encoding='utf-8')
    env = {key: value for key, value in os.environ.items() if not key.startswith(('CODEX_', 'OPENAI_'))
           and not any(word in key for word in ('TOKEN', 'SECRET', 'API_KEY'))}
    env.update(CODEX_HOME=str(home), TERM='xterm-256color', COLORTERM='truecolor', NO_COLOR='')
    relay = Relay(binary, env, output)
    try:
        async with serve(relay.connect, '127.0.0.1', 0, max_size=16 * 1024 * 1024) as server:
            port = server.sockets[0].getsockname()[1]
            result = await asyncio.to_thread(drive, binary, env, project, output, port, relay, provider)
        result.update(protocolErrors=relay.errors, providerErrors=provider.errors,
                      providerRequests=provider.records, decisions=relay.policy.decisions, configRewrites=relay.policy.config_rewrites)
        save(output / 'events.json', relay.events)
        return result
    finally:
        provider.shutdown()
        provider.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    baseline = json.loads((ROOT / 'build/native_ui/upstream.json').read_text())['tag']
    latest = api('releases/latest')
    releases = [api('releases/tags/' + baseline)]
    if latest['tag_name'] != baseline:
        releases.append(latest)
    results = []
    for release in releases:
        directory = output / release['tag_name']
        directory.mkdir()
        print('Testing official ' + release['tag_name'] + ' without rebuilding', flush=True)
        identity, binary = {}, None
        try:
            binary, identity = official_package(release, directory)
            result = asyncio.run(experiment(binary, directory))
        except Exception as exc:
            result = {'experimentError': str(exc), 'traceback': traceback.format_exc()}
        if binary is not None:
            identity['binarySha256After'] = sha256(binary)
            result['binaryUnmodified'] = identity['binarySha256Before'] == identity['binarySha256After']
        result['identity'] = identity
        save(directory / 'result.json', result)
        results.append(result)
        print(json.dumps({'tag': release['tag_name'], 'fullRequestedUX': result.get('fullRequestedUX'),
                          'experimentError': result.get('experimentError')}), flush=True)
    save(output / 'results.json', results)
    summary = ['# Auto relay feasibility experiment', '',
               'Official Linux TUI/app-server, local synthetic model responses. No Codex compilation.',
               '**This run is an experiment, not a release or proof of live-model compatibility.**', '',
               '| Codex | Binary unchanged | Exact Auto label | Menu/routing/footer |', '|---|---|---|---|']
    for result in results:
        summary.append('| ' + ' | '.join(str(value) for value in (result['identity'].get('version', 'setup failed'),
            result.get('binaryUnmodified', 'not-tested'), result.get('exactAutoLabel', 'not-tested'),
            result.get('menuRoutingFooterSatisfied', 'not-tested'))) + ' |')
    summary += ['', 'See results.json, each terminal snapshot and terminal.ansi in the evidence artifact.',
                'Live model inference, real account restrictions, session resume and approvals are not established by this probe.']
    content = '\n'.join(summary) + '\n'
    (output / 'SUMMARY.md').write_text(content, encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as stream:
            stream.write(content)
    return int(any('experimentError' in result or result.get('binaryUnmodified') is not True for result in results))


if __name__ == '__main__':
    raise SystemExit(main())
