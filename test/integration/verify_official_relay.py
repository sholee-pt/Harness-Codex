"""Release gate: real official TUI with the production adapter and fixture inference."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
from unittest import mock

import auto_relay_probe as probe
from harness_cli import auto_relay, codex_entry


class ObservedPolicy(auto_relay.Policy):
    def __init__(self):
        super().__init__()
        self.decisions, self.events, self.errors, self.thread_ids, self.config_rewrites = [], [], [], [], []

    def request(self, method, params):
        result = super().request(method, params)
        if method == 'turn/start':
            self.decisions.append({'threadId': params['threadId'], 'inputSha256': probe.input_digest(probe.text_input(params.get('input'))),
                'auto': self.enabled(params['threadId']), 'model': result.get('model'), 'effort': result.get('effort')})
        if method in {'config/batchWrite', 'config/value/write'} and result != params:
            self.config_rewrites.append({'guarded': True})
        return result

    def response(self, message, method, params):
        result = message.get('result') or {}
        if method == 'turn/start' and 'result' in message:
            for decision in reversed(self.decisions):
                if decision['threadId'] == params.get('threadId') and 'turnId' not in decision:
                    decision['turnId'] = (result.get('turn') or {}).get('id')
                    break
        if method in {'thread/start', 'thread/resume'} and 'result' in message:
            self.thread_ids.append(result['thread']['id'])
        if message.get('method'):
            event = message.get('params') or {}
            turn = event.get('turn') or {}
            self.events.append({'method': message['method'], 'threadId': event.get('threadId'),
                'turnId': event.get('turnId') or turn.get('id'), 'status': turn.get('status')})
        if 'error' in message:
            self.errors.append({'method': method, 'error': message['error']})
        return super().response(message, method, params)


async def experiment(binary, output):
    from websockets.asyncio.server import serve
    home, project = output / 'home', output / 'project'
    home.mkdir()
    project.mkdir()
    provider = probe.ThreadingHTTPServer(('127.0.0.1', 0), probe.Provider)
    provider.records, provider.errors = [], []
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    config = ('model = "gpt-5.6-sol"\nmodel_provider = "probe"\nmodel_reasoning_effort = "medium"\n'
        'approval_policy = "never"\nsandbox_mode = "read-only"\n[tui]\nstatus_line = ["model-with-reasoning"]\n'
        '[model_providers.probe]\nname = "Local synthetic fixture"\n'
        f'base_url = "http://127.0.0.1:{provider.server_port}/v1"\n'
        'wire_api = "responses"\nrequires_openai_auth = false\nsupports_websockets = false\n'
        f'[projects.{json.dumps(str(project))}]\ntrust_level = "trusted"\n')
    (home / 'config.toml').write_text(config)
    env = {key: value for key, value in os.environ.items() if not key.startswith(('CODEX_', 'OPENAI_'))
           and not any(word in key for word in ('TOKEN', 'SECRET', 'API_KEY'))}
    env.update(CODEX_HOME=str(home), TERM='xterm-256color', COLORTERM='truecolor', NO_COLOR='')
    policy = ObservedPolicy()
    relay = auto_relay.Relay(binary, env, policy=policy)
    relay.events, relay.thread_ids = policy.events, policy.thread_ids
    try:
        with mock.patch.dict(os.environ, env, clear=True):
            codex_entry.compatible(binary, ['--cd', str(project)])
        async with serve(relay.connect, '127.0.0.1', 0, max_size=auto_relay.MAX_MESSAGE, compression=None) as server:
            port = server.sockets[0].getsockname()[1]
            result = await asyncio.to_thread(probe.drive, binary, env, project, output, port, relay, provider)
        result.update(protocolErrors=policy.errors, adapterError=relay.error, providerErrors=provider.errors, candidateProbe='passed')
        probe.save(output / 'events.json', policy.events)
        return result
    finally:
        provider.shutdown()
        provider.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    release = probe.api('releases/latest')
    binary, identity = probe.official_package(release, args.output)
    result = asyncio.run(experiment(binary, args.output))
    result['identity'] = identity
    result['binaryUnmodified'] = probe.sha256(binary) == identity['binarySha256Before']
    probe.save(args.output / 'result.json', result)
    passed = result.get('menuRoutingFooterSatisfied') and result['binaryUnmodified'] and not result.get('adapterError')
    print(json.dumps({'passed': bool(passed), 'officialVersion': identity['version'],
                      'error': result.get('experimentError'), 'liveInference': 'not-tested'}), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
