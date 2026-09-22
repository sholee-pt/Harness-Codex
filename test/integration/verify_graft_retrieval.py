"""Real Graft package smoke, without model calls, global wiring or project rewrites."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def verify_advice(base, env, package, node):
    """Real graph and adapter, fixture Jev response: this does not evaluate Jev quality."""
    sys.path.insert(0, str(ROOT))
    from harness_cli import graft, jev, main
    project = base / 'advice-project'
    project.mkdir()
    for i in range(8):
        (project / f'validation_{i}.py').write_text(f'def validation_request_{i}(request):\n    return request + {i}\n', encoding='utf-8')
    parser = main.build_parser(ROOT)
    def query():
        return graft.execute(parser.parse_args(['graft', 'query', 'Where are validation request handlers implemented?',
            '--project', str(project)]), ROOT)
    with mock.patch.dict(os.environ, {**env, 'TYPESAFE_API_KEY': 'fixture-only'}):
        graft.execute(parser.parse_args(['graft', 'enable', '--project', str(project), '--package', package, '--node', node]), ROOT)
        baseline = query()
        assert baseline['hits'] == 6, baseline
        with contextlib.redirect_stdout(io.StringIO()):
            jev.run(parser.parse_args(['jev', 'enable', '--project', str(project)]), ROOT)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in project.rglob('*') if p.is_file()}
        def answer(payload):
            return {'model': payload['model'], 'answers': {key: {'type': 'noul', 'noul': .9 if key == 'c5' else .5}
                for key in payload['questions']}, 'usage': {'input_tokens': 500, 'output_tokens': 6}}
        with mock.patch.object(jev, '_request', side_effect=answer) as provider:
            observed = query()
            repeated = query()
            assert observed['text'] == baseline['text'] == repeated['text']
            assert observed['jev']['suggestedOrder'][0] == 'c5', observed
            assert repeated['jev']['state'] == 'cached', repeated
            assert provider.call_count == 1
        assert all((p.read_bytes(), p.stat().st_mtime_ns) == value for p, value in before.items())
    return {'realGraph': True, 'provider': 'fixture-only', 'batchCalls': 1, 'cachedRepeat': True,
            'shadowPreservedText': True, 'projectFilesPreserved': True, 'liveJevQuality': 'not-tested'}


def verify(package=None):
    with tempfile.TemporaryDirectory(prefix='harness-graft-smoke-') as directory:
        base = Path(directory)
        project = base / 'project'
        project.mkdir()
        source = project / 'math.py'
        source.write_text('def add(left, right):\n    return left + right\n', encoding='utf-8')
        (project / 'AGENTS.md').write_bytes(b'User-owned instructions\n')
        (project / '.gitignore').write_bytes(b'outputs/\n')
        if package is None:
            sys.path.insert(0, str(ROOT / 'test'))
            from test_harness_tools import harness_apply, minimal_plan
            harness_apply.apply_application(harness_apply.build_application(project, minimal_plan(project)))
        before = {p.relative_to(project): (p.read_bytes(), p.stat().st_mtime_ns) for p in project.rglob('*') if p.is_file()}
        guard = ROOT / 'test/integration/graft_deny_network.mjs'
        env = {**os.environ, 'HARNESS_GRAFT_HOME': str(base / 'storage'), 'DO_NOT_TRACK': '1', 'TYPESAFE_API_KEY': ''}
        env.pop('NODE_OPTIONS', None)
        def init():
            completed = subprocess.run([sys.executable, '-B', str(ROOT / 'harness.py'), '--no-update-check', 'init',
                                        '--project', str(project), '--no-codex-integration'], env=env,
                                       capture_output=True, text=True, encoding='utf-8', timeout=900)
            if completed.returncode:
                raise AssertionError(completed.stdout + completed.stderr)
            return completed
        def call(*args):
            completed = subprocess.run([sys.executable, '-B', str(ROOT / 'harness.py'), 'graft', *args,
                                        '--project', str(project), '--json'], env=env, capture_output=True,
                                       text=True, encoding='utf-8', timeout=150)
            if completed.returncode:
                raise AssertionError(completed.stderr)
            return json.loads(completed.stdout)
        if package is None:
            setup = init()
            assert call('status')['enabled'], setup.stdout + setup.stderr
            with mock.patch.dict(os.environ, env):
                sys.path.insert(0, str(ROOT))
                from harness_cli import jev
                assert jev._read(jev._path(project))['mode'] == 'shadow'
        else:
            first = call('enable', '--package', str(package))
            assert first['nodes'] >= 1, first
        env['NODE_OPTIONS'] = '--import ' + json.dumps(guard.as_uri())
        # Graph and project receipts only: do not rehash the unrelated Node runtime.
        graph_files = {p: (p.read_bytes(), p.stat().st_mtime_ns) for directory in (base / 'storage').iterdir()
                       if directory.name != '.runtime' for p in directory.rglob('*') if p.is_file() and p.name != '.sync.lock'}
        if package is None:
            init()
        else:
            repeat = call('enable', '--package', str(package))
            assert not repeat['refreshed'], repeat
        query = call('query', 'add')
        assert query['hits'] > 0 and not query['refreshed'], query
        assert 'tokens saved' not in query['text']
        assert all((p.read_bytes(), p.stat().st_mtime_ns) == value for p, value in graph_files.items())
        assert all((project / name).read_bytes() == data and (project / name).stat().st_mtime_ns == timestamp
                   for name, (data, timestamp) in before.items())
        source.write_text('def multiply(left, right):\n    return left * right\n', encoding='utf-8')
        changed = call('query', 'multiply')
        assert changed['refreshed'] and changed['hits'] > 0, changed
        assert 'multiply' in changed['text']
        with mock.patch.dict(os.environ, env):
            sys.path.insert(0, str(ROOT))
            from harness_cli import graft
            settings = graft._load(graft.storage(project) / 'settings.json')
        advice = verify_advice(base, env, settings['package'], settings['node'])
        if package is None:
            with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
                from harness_cli import main
                jev.run(main.build_parser(ROOT).parse_args(['jev', 'disable', '--project', str(project)]), ROOT)
            init()
            with mock.patch.dict(os.environ, env):
                assert jev._read(jev._path(project))['mode'] == 'off'
        call('disable')
        if package is None:
            init()
        assert not call('status')['enabled']
        assert not (project / '.agents/skills/harness-retrieval/SKILL.md').exists()
        if package is not None:
            assert not (project / '.harness').exists()
        assert all((project / name).read_bytes() == data and (project / name).stat().st_mtime_ns == timestamp
                   for name, (data, timestamp) in before.items() if name != Path('math.py'))
        return {'realPackage': '0.18.0', 'unchangedQueryRebuilt': False, 'changedQueryRefreshed': True,
                'automaticInit': package is None, 'automaticJevInit': package is None,
                'explicitDisablePreserved': True, 'userFilesPreserved': True, 'modelCalls': 0, 'jev': advice}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, help='Existing package; omit to test real automatic init and cold setup.')
    args = parser.parse_args()
    print(json.dumps(verify(args.package.resolve() if args.package else None), indent=2))
