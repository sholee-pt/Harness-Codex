"""Optional empty-directory cleanup after ownership-checked project removal."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
import sys

from . import presentation as ui
from .paths import checked_path, project_root

ROOTS = {'.agents', '.codex', '.harness'}


def protected(root):
    home = Path.home().resolve()
    codex = Path(os.environ.get('CODEX_HOME', str(home / '.codex'))).expanduser()
    return {home / '.agents', home / '.codex', codex.resolve(), (root / codex).resolve()}


def candidates(root, report):
    root = project_root(root)
    paths = set()
    for action in report.get('actions', []):
        relative = Path(action['path'])
        if relative.is_absolute() or '..' in relative.parts or not relative.parts or relative.parts[0] not in ROOTS:
            continue
        parent = (root / relative).parent
        while parent != root:
            paths.add(parent)
            parent = parent.parent
    blocked = protected(root)
    result = []
    for path in sorted(paths, key=lambda item: (-len(item.parts), str(item))):
        if any(path == item or path in item.parents or item in path.parents for item in blocked):
            continue
        checked_path(path)
        if path.is_dir():
            info = path.stat()
            result.append({'path': path.relative_to(root).as_posix(), 'device': info.st_dev, 'inode': info.st_ino})
    return result


def remove_empty(root, selected):
    root = project_root(root)
    blocked = protected(root)
    removed, retained = [], []
    for entry in selected:
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts or not relative.parts or relative.parts[0] not in ROOTS:
            raise ValueError('Directory cleanup is restricted to project-local Harness component parents')
        path = checked_path(root / relative)
        if not path.is_relative_to(root) or path == root or any(path == item or path in item.parents or item in path.parents for item in blocked):
            raise ValueError('Directory cleanup cannot remove Codex home or user-level settings')
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != (entry['device'], entry['inode']):
            retained.append(entry['path'])
            continue
        try:
            # Never traverse, recursively delete, or remove an unlisted file.
            path.rmdir()
            removed.append(entry['path'])
        except OSError as exc:
            if exc.errno not in {errno.ENOTEMPTY, errno.EEXIST, errno.ENOENT}:
                raise
            retained.append(entry['path'])
    return {'removed': removed, 'retained': retained}


def after_removal(root, report, *, requested=False, json_mode=False):
    if report.get('dryRun') or report.get('recoveryRequired') or report.get('state') != 'removed':
        return None
    selected = candidates(root, report)
    if not selected:
        return {'removed': [], 'retained': []}
    if not requested:
        if json_mode or not sys.stdin.isatty() or not sys.stdout.isatty():
            return {'removed': [], 'retained': [entry['path'] for entry in selected], 'confirmationRequired': True}
        print('\nOwned files were removed. Optional project directory cleanup:')
        for entry in selected:
            print('  ' + ui.clean(entry['path']))
        print('Only empty directories are removed. Remaining files and global Codex settings are preserved.')
        if not ui.confirm('Remove these directories if they are empty?'):
            return {'removed': [], 'retained': [entry['path'] for entry in selected]}
    return remove_empty(root, selected)
