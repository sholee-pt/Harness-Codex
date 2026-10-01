"""Independently updated, unmodified official Linux Codex packages."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

from . import distribution as dist, native_package as package, release_updates as releases

REPOSITORY = 'openai/codex'
POINTER = 'official-codex.json'


def target():
    if platform.system() != 'Linux':
        raise ValueError('Official Codex relay integration is currently released for Linux only')
    machine = {'amd64': 'x86_64', 'x86_64': 'x86_64', 'aarch64': 'aarch64', 'arm64': 'aarch64'}.get(platform.machine().lower())
    if not machine:
        raise ValueError('No verified official Codex package for this architecture')
    return machine + '-unknown-linux-musl'


def release_version(value):
    tag = value.get('tag_name', '')
    if value.get('draft') or value.get('prerelease') or not re.fullmatch(r'rust-v[0-9]+\.[0-9]+\.[0-9]+', tag):
        raise ValueError('Official Codex release must be a published stable version')
    return tag.removeprefix('rust-v')


def read(data_root):
    root = dist._storage_path(data_root)
    pointer = dist._storage_path(root / POINTER)
    if not pointer.exists():
        return None
    state = dist._read_json(pointer)
    if (set(state) != {'schema', 'version', 'target'} or state['schema'] != 1
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', str(state['version']))
            or state['target'] not in {'x86_64-unknown-linux-musl', 'aarch64-unknown-linux-musl'}):
        raise ValueError('Invalid official Codex pointer; preserve installation')
    return state


def directory(root, state):
    return dist._storage_path(Path(root) / 'official-codex' / state['version'] / state['target'])


def verify(folder):
    receipt = dist._read_json(folder / 'harness-ui.json')
    if receipt.get('schema') != 1 or receipt.get('owner') != 'harness-official-codex':
        raise ValueError('Unowned official Codex package preserved')
    files, directories = package.inventory(folder)
    if files != receipt.get('files') or sorted(directories) != receipt.get('directories') or 'bin/codex' not in files:
        raise ValueError('Modified official Codex package preserved')
    return receipt


def binary(root):
    state = read(root)
    if state is None:
        raise ValueError('Official Codex has not been installed; run harness-codex config')
    folder = directory(root, state)
    verify(folder)
    return folder / 'bin/codex'


def check(root, *, timeout=5):
    state = read(root)
    release = releases.metadata(REPOSITORY, 'releases/latest', timeout=timeout)
    version = release_version(release)
    newer = state is None or dist._version(version) > dist._version(state['version'])
    return {'updateAvailable': newer, 'currentVersion': state['version'] if state else None,
            'availableVersion': version, 'release': release}


def install(root, *, selected=None):
    from .codex_entry import compatible
    root = dist._storage_path(root)
    before = read(root)
    selected = selected or check(root)
    if before and not selected['updateAvailable']:
        return binary(root)
    release = selected['release']
    version, platform_target = release_version(release), target()
    if before and dist._version(version) < dist._version(before['version']):
        raise ValueError('Official Codex downgrade refused')
    value = releases.asset(release, 'codex-package-' + platform_target + '.tar.gz', REPOSITORY)
    state = {'schema': 1, 'version': version, 'target': platform_target}
    destination = directory(root, state)
    with tempfile.TemporaryDirectory(prefix='harness-official-codex-') as temporary:
        temporary = Path(temporary).resolve()
        archive = temporary / 'codex.tar.gz'
        releases.download(value, archive)
        unpacked = temporary / 'package'
        package.extract(archive, unpacked)
        executable = unpacked / 'bin/codex'
        if not executable.is_file():
            raise ValueError('Official package has no Codex entry point')
        # Prove the packaged executable can start before switching the pointer.
        actual = subprocess.run([str(executable), '--version'], capture_output=True, text=True, timeout=10, check=True)
        if actual.stdout.strip() != 'codex-cli ' + version:
            raise ValueError('Official binary version differs from release metadata')
        files, directories = package.inventory(unpacked)
        dist._write_json(unpacked / 'harness-ui.json', {'schema': 1, 'owner': 'harness-official-codex',
            'version': version, 'target': platform_target, 'archiveSha256': value['digest'][7:],
            'files': files, 'directories': sorted(directories)})
        with dist._lock(root):
            if read(root) != before:
                raise ValueError('Official Codex changed during download; retry')
            if destination.exists():
                verify(destination)
                compatible(destination / 'bin/codex', ())
            else:
                created = [path for path in (destination.parent.parent, destination.parent) if not path.exists()]
                destination.parent.mkdir(parents=True, exist_ok=True)
                staging = Path(tempfile.mkdtemp(prefix='.pending-', dir=destination.parent))
                try:
                    shutil.copytree(unpacked, staging, dirs_exist_ok=True)
                    verify(staging)
                    # Keep the active package until the candidate's Auto protocol probe succeeds.
                    compatible(staging / 'bin/codex', ())
                    os.replace(staging, destination)
                finally:
                    if staging.exists():
                        shutil.rmtree(staging)
                    for path in reversed(created):
                        try:
                            path.rmdir()
                        except OSError:
                            pass
            dist._write_json(root / POINTER, state)
    return destination / 'bin/codex'


def removal_files(root):
    root = dist._storage_path(root)
    state = read(root)
    files = {root / POINTER: package.fingerprint(root / POINTER)} if state else {}
    base = dist._storage_path(root / 'official-codex')
    if base.exists():
        for version in base.iterdir():
            if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version.name):
                raise ValueError('Unrecognized official Codex directory preserved')
            for folder in dist._storage_path(version).iterdir():
                if folder.name not in {'x86_64-unknown-linux-musl', 'aarch64-unknown-linux-musl'}:
                    raise ValueError('Unrecognized official Codex target preserved')
                receipt = verify(dist._storage_path(folder))
                files.update({folder / name: value for name, value in receipt['files'].items()})
                files[folder / 'harness-ui.json'] = package.fingerprint(folder / 'harness-ui.json')
    return files
