"""Opt-in two-turn native smoke: different models, same saved conversation.

Consumes two real model turns. Never part of automatic unit discovery or CI.
Tests transport/history, not task quality or routing cost savings.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from harness_cli.configuration import Server
from harness_cli.presentation import Progress
from harness_cli.model_routing import Context, choose
from harness_cli.session_settings import model_catalog


class ObservedServer(Server):
    usage = None

    def observe(self, method, params):
        if method == 'thread/tokenUsage/updated':
            self.usage = params.get('tokenUsage')


def turn(server, text, decision):
    server.completed.clear()
    result = server.call('turn/start', {'threadId': server.thread_id,
        'input': [{'type': 'text', 'text': text}], 'model': decision.model, 'effort': decision.effort})
    server.turn_id = result['turn']['id']
    deadline = time.monotonic() + 90
    while not server.completed:
        server.event(deadline)
    return server.completed.popleft()['status']


def verify(output, codex):
    executable = shutil.which(codex)
    if not executable:
        raise ValueError('Codex executable unavailable.')
    report = {'scope': 'two-turn-native-model-switch', 'modelTurns': 0,
              'taskQuality': 'not-measured', 'costBenefit': 'not-measured'}
    report['codexVersion'] = subprocess.check_output([executable, '--version'], text=True, timeout=15).strip()
    with tempfile.TemporaryDirectory(prefix='harness-native-routing-') as temporary, Progress('Observe two native model turns') as console:
        root = Path(temporary)
        # Test-specific read-only sandbox; the production client does not set it.
        server = ObservedServer([executable, '-c', 'sandbox_mode="read-only"', '-c', 'approval_policy="on-request"'], root, console)
        try:
            server.initialize()
            catalog = model_catalog(server, time.monotonic() + 30)
            first = choose('Fix the README wording.', catalog)
            second = choose('Review a concurrency architecture.', catalog, new_task=True)
            if not first.model or not second.model or first.model == second.model:
                raise ValueError('Two distinct policy models are not available; model-switch smoke cannot be claimed.')
            server.thread_id = server.call('thread/start', {'cwd': str(root)})['thread']['id']
            session_id = server.thread_id
            marker = 'HARNESS_ROUTING_SMOKE_0_12'
            report['selections'] = [first.report(), second.report()]
            report['modelTurns'] += 1
            assert turn(server, 'Do not use tools or edit any files. Remember the marker ' + marker + '. Reply exactly ACK.', first) == 'completed'
            assert 'ACK' in server.last_message
            report['firstUsage'] = server.usage
            report['modelTurns'] += 1
            assert turn(server, 'Do not use tools. What exact marker did I ask you to remember earlier in this conversation? Reply only with that marker.', second) == 'completed'
            assert marker in server.last_message
            assert server.thread_id == session_id
            report['secondUsage'] = server.usage
            report['sameThread'] = True
            report['markerRetained'] = True
            report['projectFiles'] = [p.name for p in root.iterdir()]
            assert report['projectFiles'] == []
            server.call('thread/archive', {'threadId': session_id})
            report['ownedSmokeArchived'] = True
            report['status'] = 'passed'
        except Exception as exc:
            report['status'] = 'failed'
            report['error'] = str(exc)
            raise
        finally:
            server.close()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--codex-binary', default='codex')
    args = parser.parse_args()
    verify(args.output, args.codex_binary)
