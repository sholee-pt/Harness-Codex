"""Independent blocked/resume fixture; optional real Codex phases never run in default CI."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from harness_cli.environment import codex_environment


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(output, *, live=False, codex='codex', timeout=300):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='harness-checkpoint-smoke-') as temporary:
        base = Path(temporary)
        project, store = base / 'project', base / 'state'
        project.mkdir()
        for name in ('alpha', 'beta'):
            (project / (name + '.spec')).write_text('ALPHA' if name == 'alpha' else 'UNRESOLVED')
        checker = project / 'check.py'
        checker.write_text("from pathlib import Path\nimport sys\nfor name in sys.argv[1:]:\n    assert Path(name + '.txt').read_text() == name.upper()\n    assert Path(name + '.spec').read_text() == name.upper()\n")
        tasks = [{'id': name, 'dependsOn': [], 'inputs': [name + '.spec', 'check.py'], 'outputs': [name + '.txt'],
                  'context': {}, 'checks': [[sys.executable, 'check.py', name]]} for name in ('alpha', 'beta')]
        tasks.append({'id': 'qa', 'dependsOn': ['alpha', 'beta'], 'inputs': ['check.py'], 'outputs': [],
                      'context': {}, 'checks': [[sys.executable, 'check.py', 'alpha', 'beta']]})
        plan = base / 'plan.json'
        plan.write_text(json.dumps({'schemaVersion': 1, 'tasks': tasks}))
        helper = ROOT / '.agents/skills/harness/scripts/harness_checkpoint.py'
        protected = {path: fingerprint(path) for path in (checker, plan, helper, project / 'alpha.spec', project / 'beta.spec')}
        command = [sys.executable, '-B', str(helper)]
        common = ['--root', str(project), '--store', str(store), '--plan', str(plan)]
        report = {'scope': 'native-collaboration' if live else 'offline-checkpoint-cli',
                  'liveRequested': live, 'nativeDispatch': 'not-tested', 'taskQuality': 'not-measured',
                  'tokenBenefit': 'not-measured', 'phases': []}

        def call(action, run, *extra, failed=False):
            result = subprocess.run(command + [action, '--run', run] + common + list(extra),
                capture_output=True, text=True, timeout=25)
            if result.returncode != int(failed):
                raise AssertionError('Unexpected helper outcome: ' + action + ': ' + result.stderr)
            return json.loads(result.stdout)

        def preserve():
            assert all(fingerprint(path) == value for path, value in protected.items()), 'Protected fixture was changed'
            assert {p.relative_to(project).as_posix() for p in project.rglob('*') if p.is_file()} <= {
                'alpha.spec', 'beta.spec', 'check.py', 'alpha.txt', 'beta.txt'}, 'Unexpected project writes'

        def finish(name, run, failed=False):
            attempt = call('start', run, '--task', name)['attemptId']
            if name != 'qa':
                (project / (name + '.txt')).write_text(name.upper())
            result = call('record', run, '--task', name, '--attempt', attempt, failed=failed)
            assert result['status'] == ('blocked' if failed else 'completed')
            call('quiesce', run, '--task', name, '--observed', 'idle', '--attempt', attempt)

        def native_phase(run, names):
            help_result = subprocess.run([codex, 'exec', '--help'], capture_output=True, text=True,
                env=codex_environment(), timeout=15)
            if help_result.returncode or any(flag not in help_result.stdout for flag in ('--json', '--cd', '--add-dir')):
                raise ValueError('The current Codex lacks the required exec capabilities; no version gate or fallback was used')
            invocation = shlex.join(command) + ' ACTION --run ' + run + ' ' + shlex.join(common)
            prompt = ('Run a bounded checkpoint smoke fixture using actual native subagents for tasks ' + ', '.join(names) + '. '
                'Use one writer at a time. Do not edit check.py, specs, the plan, helpers or checkpoint JSON directly. '
                'Do not commit, push, change permissions, or recursively delegate. Require an observed native handle; '
                'if subagents are unavailable, stop and report the limitation. For each task the parent runs: ' + invocation +
                ' --task TASK, replacing ACTION with start before dispatch and record after the child returns. '
                'Retain the attemptId from start and pass --attempt ID to record and quiesce for that execution. '
                'Child alpha or beta writes only TASK.txt containing TASK uppercased, without a newline. '
                'Child qa is read-only and reviews both outputs. The first beta check deliberately fails: preserve it, '
                'report blocked, and do not fix its spec. After observing each child turn is idle, the parent runs '
                'the same command with ACTION quiesce and --observed idle. Do not claim a child was closed. '
                'Do not run any task other than the listed tasks or retry a blocked task. Stop after this phase.')
            result = subprocess.run([codex, 'exec', '--skip-git-repo-check', '--json', '--cd', str(project), '--add-dir', str(store), '-'],
                input=prompt, capture_output=True, text=True, env=codex_environment(), timeout=timeout)
            if result.returncode:
                raise AssertionError('Native fixture did not complete; no fallback or permission broadening was attempted')
            dispatched = set()
            for line in result.stdout.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                item = event.get('item', {})
                if (event.get('type') == 'item.completed' and isinstance(item, dict)
                        and item.get('type') == 'collab_tool_call' and item.get('tool') == 'spawn_agent'
                        and item.get('status') == 'completed'):
                    receivers = item.get('receiver_thread_ids', [])
                    if isinstance(receivers, list):
                        dispatched.update(value for value in receivers if isinstance(value, str) and value)
            report['phases'].append({'observedDispatchCount': len(dispatched), 'requiredTasks': len(names)})
            preserve()

        try:
            call('init', 'first', '--keep-days', '1')
            if live:
                native_phase('first', ['alpha', 'beta'])
            else:
                finish('alpha', 'first')
                finish('beta', 'first', failed=True)
            first = call('status', 'first')
            assert first['complete'] is False and first['reusable'] == ['alpha']
            old = json.loads((store / 'checkpoint.json').read_text())['runs']
            alpha = fingerprint(project / 'alpha.txt'), (project / 'alpha.txt').stat().st_mtime_ns
            (project / 'beta.spec').write_text('BETA')
            protected[project / 'beta.spec'] = fingerprint(project / 'beta.spec')
            resumed = call('resume', 'second', '--previous', 'first', '--keep-days', '1')
            assert resumed['reused'] == ['alpha'] and set(resumed['pending']) == {'beta', 'qa'}
            if live:
                native_phase('second', ['beta', 'qa'])
            else:
                finish('beta', 'second')
                finish('qa', 'second')
            assert call('status', 'second')['complete'] is True
            assert alpha == (fingerprint(project / 'alpha.txt'), (project / 'alpha.txt').stat().st_mtime_ns)
            after = json.loads((store / 'checkpoint.json').read_text())['runs']
            assert all(after[key] == value for key, value in old.items())
            preserve()
            report.update(functionalStatus='passed', previousRunPreserved=True, reusedOutputPreserved=True)
            if live:
                report['nativeDispatch'] = 'observed' if all(p['observedDispatchCount'] >= p['requiredTasks'] for p in report['phases']) else 'not-exposed'
            report['status'] = 'passed' if not live or report['nativeDispatch'] == 'observed' else 'incomplete-native-evidence'
        except Exception as error:
            report.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
        return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live', action='store_true', help='Spend model tokens in two ordinary native Codex conversations; never enabled by CI.')
    parser.add_argument('--codex-binary', default='codex')
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 600:
        parser.error('--timeout must be 1-600 seconds per native phase')
    raise SystemExit(verify(args.output, live=args.live, codex=args.codex_binary, timeout=args.timeout))
