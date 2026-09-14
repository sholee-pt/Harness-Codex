"""Reconcile the upstream release lock, rejecting new external dependencies."""
import argparse
import json
from pathlib import Path
import subprocess
import tomllib


def external(path):
    return {(p['name'], p['version'], p['source'], p.get('checksum'))
            for p in tomllib.loads(path.read_text())['package'] if 'source' in p}


def reconcile(root, *, test_target=None):
    path = root / 'codex-rs/Cargo.lock'
    before = external(path)
    command = ['cargo', 'metadata', '--format-version', '1', '--all-features']
    if test_target:
        # Cargo includes implicit path members (including nested test helpers).
        # Resolve the same graph nextest requests, without fetching new inputs.
        command += ['--filter-platform', test_target, '--offline']
    subprocess.run(command,
                   cwd=path.parent, stdout=subprocess.DEVNULL, check=True)
    after = external(path)
    added = sorted(after - before)
    print(json.dumps({'addedExternalDependencies': added,
                      'removedUnusedExternalDependencies': sorted(before - after)}, indent=2))
    if added or (test_target and before != after):
        raise ValueError('Refusing an unreviewed external dependency change')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    reconcile(parser.parse_args().root.resolve())
