"""Real Conda and source installer under a competing-Python PATH; no new env."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from harness_cli import distribution


def verify():
    conda = os.environ.get('CONDA_EXE') or shutil.which('conda')
    if not conda:
        raise ValueError('Run from the existing harness Conda environment')
    info = json.loads(subprocess.check_output([conda, 'info', '--json'], text=True))
    target, base = Path(sys.prefix), Path(info['root_prefix'])
    if target.resolve() == base.resolve():
        raise ValueError('The selected harness environment must differ from Conda base')
    target_bin = target if os.name == 'nt' else target / 'bin'
    base_bin = base if os.name == 'nt' else base / 'bin'
    environment = {**os.environ, 'CONDA_EXE': str(conda), 'CONDA_PREFIX': str(target), 'CONDA_SHLVL': '1',
                   'PATH': os.pathsep.join([str(base_bin), str(target_bin), os.environ.get('PATH', '')]),
                   'PYTHONDONTWRITEBYTECODE': '1', 'HARNESS_NO_UPDATE_CHECK': '1',
                   'CONDA_OFFLINE': 'true', 'CONDA_REPORT_ERRORS': 'false'}
    probe = 'import json,sys;print(json.dumps({"prefix":sys.prefix,"executable":sys.executable}))'
    def run(command):
        result = subprocess.run([str(arg) for arg in command], env=environment, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=180)
        if result.returncode:
            raise AssertionError(result.stdout[-4000:] + result.stderr[-4000:])
        return result.stdout
    legacy = json.loads(run([conda, 'run', '--no-capture-output', '--prefix', target, 'python', '-B', '-c', probe]).strip())
    exact = json.loads(run([conda, 'run', '--no-capture-output', '--prefix', target, sys.executable, '-B', '-c', probe]).strip())
    assert Path(legacy['prefix']).resolve() != target.resolve(), 'Fixture did not reproduce PATH selection failure'
    assert Path(exact['prefix']).resolve() == target.resolve(), exact
    with tempfile.TemporaryDirectory(prefix='harness-interpreter-install-') as directory:
        # The source installer receives the resolved native path. Use that same
        # spelling for the initial fixture receipt (Windows temp may use 8.3).
        scratch = Path(directory).resolve()
        data, binary = scratch / 'tool data', scratch / 'command bin'
        distribution.install_tool(ROOT, data, binary, python_executable=sys.executable, auto_update='off')
        before = distribution.installed_status(data)
        environment.update(TMPDIR=str(scratch), TMP=str(scratch), TEMP=str(scratch))
        if os.name == 'nt':
            shell = shutil.which('powershell') or shutil.which('pwsh')
            run([shell, '-NoProfile', '-File', ROOT / 'installer/install.ps1', '-CondaExe', conda,
                 '-DataDir', data, '-BinDir', binary, '-Existing', 'reuse', '-NoModifyPath'])
        else:
            run(['/bin/bash', ROOT / 'installer/install.sh', '--data-dir', data, '--bin-dir', binary,
                 '--existing', 'reuse', '--no-modify-path', '--activate', 'skip'])
        after = distribution.installed_status(data)
        assert after['python'] == before['python'] == str(Path(sys.executable).resolve()), after
        assert after['treeHash'] == before['treeHash'], 'Reuse installation changed the release tree'
        assert 'Harness for Codex ' + after['version'] in run([sys.executable, '-B', data / 'launcher.py', '--version'])
    return {'status': 'passed', 'legacyPythonMismatchReproduced': True, 'absolutePythonPrefixVerified': True,
            'realSourceInstallerReusePassed': True, 'existingEnvironmentPreserved': True,
            'platform': sys.platform, 'newEnvironmentCreated': False, 'liveCodexInvoked': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify()
    text = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text)
