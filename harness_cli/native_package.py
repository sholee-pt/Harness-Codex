"""Bounded native UI archives; file ownership is recorded, never inferred."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tarfile

from .paths import checked_path

MAX_FILE = 512 * 1024 * 1024
MAX_TREE = 1024 * 1024 * 1024
MAX_FILES = 256
UPSTREAM = '6b9826e3aa83b1a5947db50f4332cb9c65f1b340'
TARGETS = {'linux-x86_64': 'x86_64-unknown-linux-musl', 'windows-x86_64': 'x86_64-pc-windows-msvc'}


def relative(name):
    from .distribution import _relative
    return _relative(name)


def fingerprint(path):
    path = checked_path(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE:
        raise ValueError('Native UI file must be a bounded regular file')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('Native UI file changed during inspection')
    return {'sha256': digest, 'size': before.st_size}


def extract(archive, output):
    """Extract only portable regular files/directories into a new directory."""
    output = checked_path(output)
    output.mkdir(parents=True, exist_ok=False)
    with tarfile.open(checked_path(archive), 'r:gz') as incoming:
        seen, total = set(), 0
        for member in incoming:
            name = relative(member.name.rstrip('/'))
            folded = name.casefold()
            if folded in seen or len(seen) >= MAX_FILES:
                raise ValueError('Duplicate or excessive native UI archive entries')
            seen.add(folded)
            if not (member.isdir() or member.isfile()) or not 0 <= member.size <= MAX_FILE:
                raise ValueError('Unsupported native UI archive member')
            total += member.size
            if total > MAX_TREE:
                raise ValueError('Native UI archive exceeds the unpacked size bound')
            target = checked_path(output / name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with incoming.extractfile(member) as source, target.open('xb') as destination:
                remaining = member.size
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError('Truncated native UI member')
                    destination.write(block)
                    remaining -= len(block)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)


def inventory(root):
    files, directories, total = {}, set(), 0
    root = checked_path(root)
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            path = checked_path(Path(directory) / name)
            key = relative(path.relative_to(root).as_posix())
            if path.is_dir():
                directories.add(key)
            elif key != 'harness-ui.json':
                files[key] = fingerprint(path)
                total += files[key]['size']
            if len(files) + len(directories) > MAX_FILES or total > MAX_TREE:
                raise ValueError('Native UI installation exceeds its size bound')
    return files, directories


def verify(root, version, platform):
    root = checked_path(root)
    metadata = checked_path(root / 'harness-ui.json')
    if metadata.stat().st_size > 128 * 1024:
        raise ValueError('Native UI metadata exceeds its size bound')
    value = json.loads(metadata.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or platform not in TARGETS
            or value.get('schema') != 1 or value.get('version') != version or value.get('platform') != platform
            or value.get('upstreamCommit') != UPSTREAM or value.get('target') != TARGETS.get(platform)
            or not re.fullmatch('[0-9a-f]{64}', value.get('extensionSha256', ''))):
        raise ValueError('Native UI package is incompatible with this Harness release')
    files, directories = inventory(root)
    if files != value.get('files') or sorted(directories) != value.get('directories'):
        raise ValueError('Native UI package files differ from their receipt; preserved for inspection')
    suffix = '.exe' if platform.startswith('windows-') else ''
    required = {'bin/codex' + suffix, 'bin/codex-code-mode-host' + suffix,
                'codex-path/rg' + suffix, 'codex-package.json', 'UPSTREAM_LICENSE', 'UPSTREAM_NOTICE'}
    required.update({'codex-resources/codex-command-runner.exe', 'codex-resources/codex-windows-sandbox-setup.exe'}
                    if suffix else {'codex-resources/bwrap', 'codex-resources/zsh/bin/zsh'})
    if not required <= files.keys():
        raise ValueError('Native Codex package is missing required execution resources')
    layout = json.loads((root / 'codex-package.json').read_text(encoding='utf-8'))
    if (not isinstance(layout, dict) or layout.get('layoutVersion') != 1 or layout.get('target') != TARGETS[platform]
            or layout.get('entrypoint') != 'bin/codex' + suffix
            or layout.get('resourcesDir') != 'codex-resources' or layout.get('pathDir') != 'codex-path'):
        raise ValueError('Unsupported native Codex package layout')
    return value
