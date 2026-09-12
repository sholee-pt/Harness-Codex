"""Reconcile the upstream release lock, rejecting new external dependencies."""
import argparse
import json
from pathlib import Path
import subprocess
import tomllib


def external(path):
    return {(p['name'], p['version'], p['source'], p.get('checksum'))
            for p in tomllib.loads(path.read_text())['package'] if 'source' in p}


def reconcile(root):
    path = root / 'codex-rs/Cargo.lock'
    before = external(path)
    subprocess.run(['cargo', 'metadata', '--format-version', '1'],
                   cwd=path.parent, stdout=subprocess.DEVNULL, check=True)
    after = external(path)
    added = sorted(after - before)
    print(json.dumps({'addedExternalDependencies': added,
                      'removedUnusedExternalDependencies': sorted(before - after)}, indent=2))
    if added:
        raise ValueError('Refusing an unreviewed external dependency change')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    reconcile(parser.parse_args().root.resolve())
