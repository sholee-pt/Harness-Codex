"""Prepare an isolated Linux retrieval runtime once, without changing user tools."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import tarfile
import tempfile

from .distribution import _lock, _relative
from .native_ui import _download
from .paths import checked_path

OWNER = 'harness-graft-runtime-v1'
NODE_URL = 'https://nodejs.org/dist/latest-v22.x/'


def _read(root, version):
    value = json.loads(checked_path(root / 'runtime.json').read_text(encoding='utf-8'))
    if value != {'owner': OWNER, 'packageVersion': version}:
        raise ValueError('Unowned or incompatible Graft runtime; existing files were preserved.')
    node = checked_path(root / 'node/bin/node')
    package = checked_path(root / 'package/node_modules/@nanonets/graft')
    metadata = json.loads((package / 'package.json').read_text(encoding='utf-8'))
    if not node.is_file() or not isinstance(metadata, dict) or metadata.get('name') != '@nanonets/graft' or metadata.get('version') != version:
        raise ValueError('Incomplete Graft runtime; existing files were preserved.')
    return node, package


def _extract(archive, output, prefix):
    # npm/npx symlinks are unnecessary: invoke npm-cli.js through the owned Node.
    with tarfile.open(archive, 'r:xz') as incoming:
        seen, total = set(), 0
        for member in incoming:
            if member.name.rstrip('/') == prefix:
                continue
            if not member.name.startswith(prefix + '/'):
                raise ValueError('Unexpected Node archive root')
            name = _relative(member.name[len(prefix) + 1:].rstrip('/'))
            if name in seen or len(seen) >= 10000:
                raise ValueError('Duplicate or excessive Node archive entries')
            seen.add(name)
            if member.issym() or member.islnk():
                continue
            if not (member.isfile() or member.isdir()) or not 0 <= member.size <= 256 * 1024 * 1024:
                raise ValueError('Unsupported Node archive entry')
            total += member.size
            if total > 512 * 1024 * 1024:
                raise ValueError('Node archive exceeds its unpacked size bound')
            target = checked_path(output / name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with incoming.extractfile(member) as source, target.open('xb') as destination:
                    while block := source.read(1024 * 1024):
                        destination.write(block)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)


def _install(node, prefix, version, log):
    npm = node.parent.parent / 'lib/node_modules/npm/bin/npm-cli.js'
    user_config, global_config = prefix.parent.parent / 'user.npmrc', prefix.parent.parent / 'global.npmrc'
    for path in (user_config, global_config):
        path.write_text('', encoding='utf-8')
    # All dependency writes stay in this disposable staging directory. Ignore
    # project/user npm configuration, lifecycle NODE_OPTIONS and credential envs.
    env = {key: value for key, value in os.environ.items()
           if not key.lower().startswith(('npm_', 'node_', 'graft_')) and key not in {'NPM_TOKEN', 'NODE_AUTH_TOKEN'}}
    env.update(PATH=str(node.parent) + os.pathsep + env.get('PATH', ''), DO_NOT_TRACK='1',
               npm_config_cache=str(prefix.parent.parent / 'npm-cache'), npm_config_userconfig=str(user_config),
               npm_config_globalconfig=str(global_config), npm_config_registry='https://registry.npmjs.org/',
               npm_config_devdir=str(prefix.parent.parent / 'node-gyp'), npm_config_nodedir=str(node.parent.parent),
               npm_config_fetch_retries='1', npm_config_fetch_timeout='30000')
    arguments = [str(node), str(npm), 'install', '--prefix', str(prefix), '--no-audit', '--no-fund',
                 '--no-update-notifier', '--save-exact', '@nanonets/graft@' + version]
    with log.open('wb') as output, subprocess.Popen(arguments, cwd=prefix.parent, env=env,
            stdout=output, stderr=subprocess.STDOUT, start_new_session=True) as process:
        try:
            result = process.wait(timeout=180)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise
        if result:
            raise ValueError('Graft dependency preparation failed; details: ' + str(log))


def prepare(home, version):
    if sys.platform != 'linux':
        raise ValueError('Automatic Graft setup currently supports Linux only.')
    arch = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine().lower())
    if arch is None:
        raise ValueError('Automatic Graft setup supports Linux x86_64 and aarch64.')
    base = checked_path(home / '.runtime')
    root = checked_path(base / ('graft-' + version + '-linux-' + arch))
    if root.exists():
        return _read(root, version)
    base.mkdir(parents=True, exist_ok=True)
    with _lock(base):
        if root.exists():
            return _read(root, version)
        fd, log_name = tempfile.mkstemp(prefix='graft-setup-', suffix='.log', dir=base)
        os.close(fd)
        log = Path(log_name)
        with tempfile.TemporaryDirectory(prefix='.pending-', dir=base) as directory:
            stage = Path(directory)
            sums = stage / 'SHASUMS256.txt'
            _download(NODE_URL + sums.name, sums, 256 * 1024)
            matches = re.findall(r'^([0-9a-f]{64})  (node-v22\.\d+\.\d+-linux-' + arch + r'\.tar\.xz)$', sums.read_text(), re.M)
            if len(matches) != 1:
                raise ValueError('Node release checksum did not identify one supported archive.')
            digest, name = matches[0]
            archive = stage / name
            _download(NODE_URL + name, archive, 80 * 1024 * 1024)
            with archive.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != digest:
                    raise ValueError('Node archive checksum mismatch; no runtime was installed.')
            runtime = stage / 'runtime'
            _extract(archive, runtime / 'node', name.removesuffix('.tar.xz'))
            _install(runtime / 'node/bin/node', runtime / 'package', version, log)
            (runtime / 'runtime.json').write_text(json.dumps({'owner': OWNER, 'packageVersion': version}), encoding='utf-8')
            _read(runtime, version)
            runtime.rename(root)
        log.unlink()
    return _read(root, version)
