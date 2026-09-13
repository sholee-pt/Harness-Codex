"""Manage native Codex resolution. This module never owns or launches a conversation."""
from __future__ import annotations

import os
import json
from pathlib import Path
import shutil
import re

from . import distribution as dist, native_package, native_ui, integration_path

RECEIPT = 'codex-integration.json'


def read(data_root):
    root = dist._storage_path(data_root)
    path = dist._storage_path(root / RECEIPT)
    if not path.exists():
        return None
    value = dist._read_json(path)
    if (not isinstance(value, dict) or set(value) != {'schema', 'owner', 'version', 'directory', 'original', 'mode', 'files'}
            or value['schema'] != 1 or value['owner'] != 'harness-codex-native'
            or not isinstance(value['mode'], str) or value['mode'] not in {'manual', 'auto'}
            or not isinstance(value['version'], str) or not isinstance(value['directory'], str)
            or not isinstance(value['files'], dict) or len(value['files']) > 256):
        raise ValueError('Invalid native Codex ownership receipt; preserve the installation')
    dist._version(value['version'])
    directory = dist._storage_path(value['directory'])
    expected = root / 'native-ui' / ('v' + value['version'])
    if directory.parent.parent != expected or directory.name != 'bin' or directory.parent.name not in native_package.TARGETS:
        raise ValueError('Native Codex receipt points outside its owned package')
    if value['original'] is not None and (not isinstance(value['original'], str) or not Path(value['original']).is_absolute()
                                          or Path(value['original']).is_relative_to(root)):
        raise ValueError('Original Codex must remain outside Harness storage')
    for relative, digest in value['files'].items():
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Invalid native routing settings fingerprint')
        relative = native_package.relative(relative)
        path = dist._storage_path(root / relative)
        if (path.parent.parent != root / 'native-ui' or not path.parent.name.startswith('v')
                or path.name not in {platform + '.routing.json' for platform in native_package.TARGETS}):
            raise ValueError('Unrecognized native routing sidecar in receipt')
        if path.stat().st_size > 16384 or native_package.fingerprint(path)['sha256'] != digest:
            raise ValueError('Modified native routing settings preserved; run doctor')
    sidecar = directory.parent.with_name(directory.parent.name + '.routing.json')
    if sidecar.relative_to(root).as_posix() not in value['files']:
        raise ValueError('Active native routing settings are not owned')
    return value


def original_codex(root, *, path=None):
    root = dist._storage_path(root)
    directories = []
    for directory in (path if path is not None else os.environ.get('PATH', '')).split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory).expanduser().absolute()
        if candidate == root or root in candidate.parents:
            continue
        directories.append(directory)
    found = shutil.which('codex', path=os.pathsep.join(directories))
    return str(Path(found).absolute()) if found else None


def install(data_root, source_root, *, archive=None, mode=None, profiles=None, home=None, registry=None):
    """Verify a complete package, then atomically register its direct executable."""
    from .main import version
    root, source_root = dist._storage_path(data_root), dist._storage_path(source_root)
    state = dist.installed_status(root)
    if state['version'] != version(source_root):
        raise ValueError('Install or update the managed Harness tool before configuring native integration')
    source_root = Path(state['sourceRoot'])
    previous = read(root)
    selected_mode = mode or (previous['mode'] if previous else 'manual')
    if selected_mode not in {'manual', 'auto'}:
        raise ValueError('Auto model preference must be manual or auto')
    binary = native_ui.ensure(root, version(source_root), archive=archive)
    directory = binary.parent
    package_receipt = native_package.verify(directory.parent, version(source_root), directory.parent.name)
    if package_receipt.get('directIntegrationVersion') != 1:
        raise ValueError('This native package requires the retired Harness launcher; install the direct-integration package')
    script = source_root / 'harness_cli/native_router.py'
    sidecar = directory.parent.with_name(directory.parent.name + '.routing.json')
    settings = {'schema': 1, 'python': state['python'], 'script': str(script),
                'scriptSha256': native_package.fingerprint(script)['sha256'], 'mode': selected_mode, 'profiles': None}
    if profiles is not None:
        from .routing import read_json
        from .model_routing import choose
        profiles = dist._storage_path(profiles)
        choose('Validate routing preferences.', [], profiles=read_json(profiles))
        settings['profiles'] = str(profiles)
    elif previous:
        old_sidecar = Path(previous['directory']).parent.with_suffix('.routing.json')
        settings['profiles'] = dist._read_json(old_sidecar).get('profiles')
    with dist._lock(root):
        if read(root) != previous:
            raise ValueError('Native integration changed concurrently; retry')
        change = integration_path.plan(directory, previous=previous['directory'] if previous else None,
                                       home=home, registry=registry)
        files = dict(previous['files']) if previous else {}
        relative = sidecar.relative_to(root).as_posix()
        if sidecar.exists() and relative not in files:
            raise ValueError('Unowned native routing settings preserved')
        old_settings = sidecar.read_bytes() if sidecar.exists() else None
        receipt_path = root / RECEIPT
        old_receipt = receipt_path.read_bytes() if receipt_path.exists() else None
        written = {}
        try:
            if old_settings is None or dist._read_json(sidecar) != settings:
                written[sidecar] = ((json.dumps(settings, indent=2, sort_keys=True) + '\n').encode(), old_settings)
                dist._write_json(sidecar, settings)
            files[relative] = native_package.fingerprint(sidecar)['sha256']
            receipt = {'schema': 1, 'owner': 'harness-codex-native', 'version': version(source_root),
                       'directory': str(directory), 'original': previous['original'] if previous else original_codex(root),
                       'mode': selected_mode, 'files': files}
            if previous != receipt:
                written[receipt_path] = ((json.dumps(receipt, indent=2, sort_keys=True) + '\n').encode(), old_receipt)
                dist._write_json(receipt_path, receipt)
            integration_path.apply(change, registry=registry)
        except BaseException:
            # PATH is the final operation; its compare-and-swap refuses concurrent edits.
            for path, (expected, before) in reversed(written.items()):
                current = dist._storage_path(path).read_bytes() if path.exists() else None
                if current == before:
                    continue
                if current != expected:
                    raise ValueError('Concurrent native settings edits preserved; review integration ownership with doctor')
                if before is None:
                    path.unlink()
                else:
                    from .shell import _replace_profile
                    _replace_profile(path, expected, before)
            raise
    return {'state': 'installed', 'version': receipt['version'], 'directory': str(directory),
            'originalCodex': receipt['original'], 'mode': selected_mode, 'path': integration_path.describe(change),
            'nextStep': 'Open a new terminal.' if os.name == 'nt' else 'Apply PATH: source ~/.bashrc',
            'runtimeDiscovery': 'not-tested'}


def status(data_root, *, verify_package=True):
    try:
        value = read(data_root)
        if value is None:
            return {'state': 'not-installed', 'runtimeDiscovery': 'not-tested'}
        directory = Path(value['directory'])
        if verify_package:
            native_package.verify(directory.parent, value['version'], directory.parent.name)
        tool = dist.installed_status(data_root)
        settings = dist._read_json(directory.parent.with_suffix('.routing.json'))
        script = dist._storage_path(settings['script'])
        if native_package.fingerprint(script)['sha256'] != settings['scriptSha256']:
            raise ValueError('Native selector differs from the registered settings')
        resolved = shutil.which('codex')
        active = resolved is not None and Path(resolved).absolute().parent == directory
        state = ('upgrade-required' if tool['version'] != value['version'] else
                 'configured' if active else 'shell-refresh-or-path-review-required')
        return {'state': state,
                'version': value['version'], 'mode': value['mode'], 'directory': str(directory),
                'resolvedCodex': resolved, 'originalCodex': value['original'], 'runtimeDiscovery': 'not-tested'}
    except (OSError, ValueError, TypeError, KeyError) as error:
        return {'state': 'invalid', 'error': str(error), 'runtimeDiscovery': 'not-tested'}


def removal_files(data_root):
    root = dist._storage_path(data_root)
    value = read(root)
    if value is None:
        return {}
    return {path: native_package.fingerprint(path) for path in [root / RECEIPT, *(root / name for name in value['files'])]}
