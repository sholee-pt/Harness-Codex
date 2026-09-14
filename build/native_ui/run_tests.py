"""Run unchanged upstream UI assertions with their development-version fixture.

The release tag changes 0.0.0 to 0.154.0, but its snapshots retain padding for
0.0.0. Use that fixture version only while testing and restore both manifests
byte-for-byte before compiling or packaging the actual release executable.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from build.native_ui.lockfile import reconcile


def run_tests(root: Path, target: str, *, metadata_only: bool = False) -> int:
    cargo = root / 'codex-rs'
    manifest, lock = cargo / 'Cargo.toml', cargo / 'Cargo.lock'
    saved = {path: path.read_bytes() for path in (manifest, lock)}
    content = saved[manifest].decode('utf-8')
    version = tomllib.loads(content)['workspace']['package']['version']
    if version != '0.154.0':
        raise ValueError('UI tests require the pinned 0.154.0 release source')
    pattern = r'(?m)(^\[workspace\.package\]\s*\n(?:(?!\[)[^\n]*\n)*?version\s*=\s*)"0\.154\.0"'
    fixture, count = re.subn(pattern, lambda match: match[1] + '"0.0.0"', content)
    if count != 1:
        raise ValueError('Expected one pinned workspace version declaration')
    env = os.environ.copy()
    env.update(RUST_MIN_STACK='8388608', CODEX_REPO_ROOT=str(root), NEXTEST_PROFILE='default',
               CARGO_PROFILE_CI_TEST_DEBUG='0', INSTA_UPDATE='no')
    try:
        manifest.write_text(fixture, encoding='utf-8', newline='\n')
        reconcile(root, test_target=target)
        print(json.dumps({'releaseVersion': version, 'testFixtureVersion': '0.0.0',
                          'cargoProfile': 'ci-test', 'target': target,
                          'metadataOnly': metadata_only}), flush=True)
        if metadata_only:
            return subprocess.run(['cargo', 'metadata', '--format-version', '1', '--all-features',
                                   '--filter-platform', target, '--locked', '--offline'],
                                  cwd=cargo, env=env, stdout=subprocess.DEVNULL, check=False).returncode
        return subprocess.run(['cargo', 'nextest', 'run', '--no-fail-fast', '-p', 'codex-tui',
                               '--cargo-profile', 'ci-test', '--target', target, '--locked'],
                              cwd=cargo, env=env, check=False).returncode
    finally:
        for path, data in saved.items():
            path.write_bytes(data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--metadata-only', action='store_true',
                        help='Validate the real locked test graph without compiling or running tests')
    args = parser.parse_args()
    raise SystemExit(run_tests(args.root.resolve(), args.target, metadata_only=args.metadata_only))
