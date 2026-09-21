"""Real Graft package smoke, without model calls, global wiring or project rewrites."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def verify(package):
    with tempfile.TemporaryDirectory(prefix='harness-graft-smoke-') as directory:
        base = Path(directory)
        project = base / 'project'
        project.mkdir()
        source = project / 'math.py'
        source.write_text('def add(left, right):\n    return left + right\n', encoding='utf-8')
        (project / 'AGENTS.md').write_bytes(b'User-owned instructions\n')
        (project / '.gitignore').write_bytes(b'outputs/\n')
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in project.iterdir()}
        guard = ROOT / 'test/integration/graft_deny_network.mjs'
        env = {**os.environ, 'HARNESS_GRAFT_HOME': str(base / 'storage'), 'DO_NOT_TRACK': '1',
               'NODE_OPTIONS': '--import ' + json.dumps(guard.as_uri())}
        def call(*args):
            completed = subprocess.run([sys.executable, '-B', str(ROOT / 'harness.py'), 'graft', *args,
                                        '--project', str(project), '--json'], env=env, capture_output=True,
                                       text=True, encoding='utf-8', timeout=150)
            if completed.returncode:
                raise AssertionError(completed.stderr)
            return json.loads(completed.stdout)
        first = call('enable', '--package', str(package))
        assert first['nodes'] >= 1, first
        graph_files = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (base / 'storage').rglob('*') if p.is_file() and p.name != '.sync.lock'}
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
        call('disable')
        assert not call('status')['enabled']
        assert not (project / '.agents/skills/harness-retrieval/SKILL.md').exists()
        assert not (project / '.harness').exists()
        return {'realPackage': '0.18.0', 'unchangedQueryRebuilt': False, 'changedQueryRefreshed': True,
                'userFilesPreserved': True, 'modelCalls': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.package.resolve()), indent=2))
