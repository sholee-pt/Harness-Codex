"""Exercise native hook trust in an isolated home; no conversation or inference."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.agents/skills/harness/scripts'))
sys.path.insert(0, str(ROOT / 'test'))
from harness_cli import distribution, hook_trust, maintenance, presentation
from harness_maintenance import Maintenance
from harness_routing_evidence import RoutingEvidence
from test_harness_tools import harness_apply, minimal_plan


def verify(binary):
    version = subprocess.check_output([str(binary), '--version'], text=True, timeout=10).strip()
    with tempfile.TemporaryDirectory(prefix='harness-hook-trust-') as directory:
        base = Path(directory)
        home, root, state = base / 'codex', base / 'project', base / 'state'
        home.mkdir()
        root.mkdir()
        harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))
        config = home / 'config.toml'
        config.write_text('approval_policy = "on-request"\nsandbox_mode = "read-only"\n'
                          '[hooks.state.unrelated-state]\nenabled = false\ntrusted_hash = "prior-unrelated-hash"\n', encoding='utf-8')
        path = home / 'hooks.json'
        unrelated = {'type': 'command', 'command': 'unrelated-fixture-command'}
        path.write_text(json.dumps({'hooks': {'Stop': [{'hooks': [unrelated]}]}}), encoding='utf-8')
        environment = {key: value for key, value in os.environ.items() if not key.startswith(('CODEX_', 'OPENAI_', 'HARNESS_'))
                       and not any(word in key for word in ('TOKEN', 'SECRET', 'API_KEY'))}
        environment.update(CODEX_HOME=str(home), HARNESS_STATE_HOME=str(state))
        data = base / 'tool'
        distribution.install_tool(ROOT, data, base / 'bin', sys.executable)
        environment['HARNESS_TOOL_HOME'] = str(data)
        with mock.patch.dict(os.environ, environment, clear=True), contextlib.redirect_stdout(io.StringIO()):
            first = hook_trust.prepare(ROOT, root, binary=str(binary))
            if first['status'] != 'trusted':
                raise AssertionError(first)
            snapshot = {target: (target.read_bytes(), target.stat().st_mtime_ns)
                        for target in (config, path, home / 'harness-maintenance-hooks.json')}
            repeated = hook_trust.prepare(ROOT, root, binary=str(binary))
            assert repeated['status'] == 'trusted' and repeated['changed'] is False, repeated
            assert all((target.read_bytes(), target.stat().st_mtime_ns) == value for target, value in snapshot.items())
            content = tomllib.loads(config.read_text(encoding='utf-8'))
            assert content['approval_policy'] == 'on-request' and content['sandbox_mode'] == 'read-only'
            assert content['hooks']['state']['unrelated-state'] == {'enabled': False, 'trusted_hash': 'prior-unrelated-hash'}
            assert len(content['hooks']['state']) == len(maintenance.EVENTS) + 1, content
            native = hook_trust.MetadataServer([str(binary)], root, presentation.Progress('inspect', stream=io.StringIO()))
            try:
                native.initialize(timeout=10)
                entries = native.call('hooks/list', {'cwds': [str(root)]}, timeout=10)['data'][0]['hooks']
                foreign, = [hook for hook in entries if hook.get('command') == unrelated['command']]
                assert foreign['trustStatus'] == 'untrusted', foreign
            finally:
                native.close()
            manager = Maintenance(root, state)
            assert manager.status()['mode'] == 'off'
            assert not RoutingEvidence(root, state).status()['enabled']
            for event in maintenance.EVENTS:
                assert manager.hook({'hook_event_name': event, 'session_id': 'fixture'}) == ''
            assert not state.exists(), 'off hooks unexpectedly created local state'
            # Toggling the project changes neither global definitions nor native trust.
            manager.configure('suggest')
            manager.configure('off')
            assert all((target.read_bytes(), target.stat().st_mtime_ns) == value for target, value in snapshot.items())
            fresh = base / 'fresh-home'
            fresh.mkdir()
            with mock.patch.dict(os.environ, {'CODEX_HOME': str(fresh)}):
                empty = hook_trust.prepare(ROOT, root, binary=str(binary))
                assert empty['status'] == 'trusted', empty
            cleanup = maintenance.remove_hooks(data, dry_run=False)
            assert cleanup['handlers'] == len(maintenance.EVENTS) and not cleanup['warnings'], cleanup
            remaining = tomllib.loads(config.read_text(encoding='utf-8'))
            assert remaining['hooks']['state'] == {'unrelated-state': {'enabled': False, 'trusted_hash': 'prior-unrelated-hash'}}, remaining
            assert remaining['approval_policy'] == 'on-request' and remaining['sandbox_mode'] == 'read-only'
            assert json.loads(path.read_text())['hooks']['Stop'] == [{'hooks': [unrelated]}]
            assert not (home / 'harness-maintenance-hooks.json').exists()
        return {'passed': True, 'codexVersion': version, 'ownedHandlers': first['count'],
                'unrelatedHookUntrusted': True, 'repeatWrites': 0, 'offModesPreserved': True,
                'nativePermissionsPreserved': True, 'unrelatedTrustPreserved': True,
                'freshHomeTrusted': True, 'ownedTrustRemoved': True, 'unrelatedConfigurationPreservedOnRemoval': True,
                'liveInference': 'not-run'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.codex_binary.resolve())
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
