"""Real `curl | sh` installation; local Harness assets, real cold Miniforge setup.

The private Harness release endpoints are substituted with exact built assets.
Miniforge downloads and Conda creation are real; no Codex/model call is made.
"""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def snapshot(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


def verify(dist):
    assert os.name == 'posix'
    with tempfile.TemporaryDirectory(prefix='harness-public-install-') as directory:
        base = Path(directory)
        home, binary = base / 'home', base / 'transport'
        home.mkdir(); binary.mkdir()
        assets = {p.name: str(p) for p in dist.iterdir() if p.is_file()}
        real_curl = shutil.which('curl')
        wrapper = binary / 'curl'
        wrapper.write_text('#!' + sys.executable + '\n' + '''import json, os, pathlib, sys
args = sys.argv[1:]
url = next((a for a in args if a.startswith('https://')), '')
if url.startswith('https://github.com/sholee-pt/Harness/releases/download/codex-v'):
    name = url.rsplit('/', 1)[1]
    source = pathlib.Path(json.loads(os.environ['TEST_ASSETS'])[name])
    with open(os.environ['TEST_DOWNLOAD_LOG'], 'a') as log: log.write(name + '\\n')
    if '-o' in args:
        pathlib.Path(args[args.index('-o') + 1]).write_bytes(source.read_bytes())
    else:
        sys.stdout.buffer.write(source.read_bytes())
else:
    os.execv(os.environ['TEST_REAL_CURL'], [os.environ['TEST_REAL_CURL'], *args])
''')
        wrapper.chmod(0o755)
        env = {'HOME': str(home), 'USER': os.environ.get('USER', 'runner'),
               'PATH': str(binary) + ':/usr/bin:/bin', 'XDG_DATA_HOME': str(home / 'share'),
               'TMPDIR': str(base), 'TEST_ASSETS': json.dumps(assets), 'TEST_REAL_CURL': real_curl,
               'TEST_DOWNLOAD_LOG': str(base / 'downloads.log'), 'PYTHONDONTWRITEBYTECODE': '1'}
        # Do not inherit Conda, project, credential or shell-hook variables.
        version = json.loads((dist / 'build.json').read_text())['version']
        pipeline = f'curl -fsSL https://github.com/sholee-pt/Harness/releases/download/codex-v{version}/install_harness_codex.sh | sh'
        def run(command, timeout=120):
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=timeout)
            if result.returncode:
                raise AssertionError(result.stdout[-6000:] + result.stderr[-6000:])
            return result.stdout
        run(['/bin/bash', '-o', 'pipefail', '-c', pipeline], timeout=1200)
        executable = home / '.local/bin/harness-codex'
        assert executable.is_file() and not (home / '.local/bin/harness').exists()
        assert run([executable, '--version']).strip() == 'Harness for Codex ' + version
        assert 'config' in run([executable, '--help'])
        # A fresh real interactive Bash reads .bashrc without manual PATH setup.
        located = run(['/bin/bash', '--noprofile', '-ic', 'command -v harness-codex']).strip()
        assert located == str(executable), located
        data = home / 'share/harness-codex'
        before = snapshot(data), snapshot(home / '.local/bin'), (home / '.bashrc').read_bytes(), (home / '.bashrc').stat().st_mtime_ns
        run(['/bin/bash', '-o', 'pipefail', '-c', pipeline], timeout=300)
        after = snapshot(data), snapshot(home / '.local/bin'), (home / '.bashrc').read_bytes(), (home / '.bashrc').stat().st_mtime_ns
        assert before == after, 'Repeated installation changed owned tool or Bash profile bytes/mtime'
        assert (home / 'share/harness-codex-conda/bin/conda').is_file()
        project = base / 'project'
        project.mkdir()
        (home / '.bashrc').unlink()
        run([executable, 'init', '--project', project, '--install-only', '--no-update-check'])
        assert 'harness-codex PATH' in (home / '.bashrc').read_text()
        assert (project / '.agents/skills/harness/SKILL.md').is_file()
        return {'valid': True, 'version': version, 'pipelineExecuted': True,
                'harnessAssetTransport': 'exact local build substituted for private release URLs',
                'miniforgeDownload': 'real official HTTPS with pinned SHA-256',
                'freshCondaEnvironmentCreated': True, 'freshBashFoundCommand': True,
                'repeatBytesAndMtimesPreserved': True, 'initRepairedMissingProfileEntry': True,
                'nativeCodexInvoked': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.dist.resolve()), indent=2))
