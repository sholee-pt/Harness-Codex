"""Check source identity before expensive native compilation and packaging."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def source_commit():
    git = ['git', '-c', 'safe.directory=' + ROOT.as_posix(), '-C', str(ROOT)]
    status = subprocess.check_output([*git, 'status', '--porcelain', '--untracked-files=all'], text=True).strip()
    if status:
        raise ValueError('Native release packages require a clean Harness source commit:\n' + status)
    return subprocess.check_output([*git, 'rev-parse', 'HEAD'], text=True).strip()


if __name__ == '__main__':
    print('Verified clean Harness source:', source_commit())
