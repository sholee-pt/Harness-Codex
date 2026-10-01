"""Bind owned installation paths to the current mount without rewriting history."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shlex

from .paths import checked_path


def absolute(value):
    if (not isinstance(value, str) or not Path(value).is_absolute() or '..' in Path(value).parts
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('Invalid installation location; preserve it for repair')
    return Path(value)


class Binding:
    def __init__(self, root, active):
        self.root = checked_path(root)
        if not isinstance(active, dict):
            raise ValueError('Invalid installation metadata')
        origin = active.get('pathOrigin')
        if origin is None:
            launchers = active.get('launchers', {})
            candidates = [absolute(p).parent for p in launchers if Path(p).name == 'launcher.py']
            if len(candidates) != 1:
                raise ValueError('Invalid launcher ownership metadata')
            old = candidates[0]
            paths = [old, absolute(active['binDir'])]
            try:
                anchor = Path(os.path.commonpath(paths))
            except ValueError:
                anchor = old
            from .paths import user_home
            home = user_home()
            if self.root.is_relative_to(home / '.local'):
                suffix = self.root.relative_to(home).parts
                candidate = old
                for _ in suffix:
                    candidate = candidate.parent
                if candidate.joinpath(*suffix) == old:
                    anchor = candidate
            origin = {'root': str(old), 'anchor': str(anchor)}
        if not isinstance(origin, dict) or set(origin) != {'root', 'anchor'}:
            raise ValueError('Invalid installation path origin')
        self.old, self.anchor = absolute(origin['root']), absolute(origin['anchor'])
        if not self.old.is_relative_to(self.anchor):
            raise ValueError('Installation origin is outside its anchor')
        self.origin = origin
        suffix = self.old.relative_to(self.anchor).parts
        self.current = self.root
        for _ in suffix:
            self.current = self.current.parent
        if self.current.joinpath(*suffix) != self.root or (self.old != self.root and self.anchor == Path(self.anchor.anchor)):
            raise ValueError('Installation layout changed; select the original relative layout before repair')

    def path(self, value, *, reverse=False):
        path = absolute(value)
        before, after = (self.current, self.anchor) if reverse else (self.anchor, self.current)
        return str(after / path.relative_to(before)) if path.is_relative_to(before) else str(path)

    def active(self, value, *, reverse=False):
        result = copy.deepcopy(value)
        for field in ('python', 'binDir'):
            result[field] = self.path(result[field], reverse=reverse)
        result['launchers'] = {self.path(p, reverse=reverse): digest for p, digest in result['launchers'].items()}
        if 'pathOrigin' in value or self.old != self.root:
            result['pathOrigin'] = self.origin
        return result


def binding(root):
    path = checked_path(Path(root) / 'active.json')
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Installation metadata is too large')
    return Binding(Path(root), json.loads(path.read_text(encoding='utf-8')))


def record(path, value, *, reverse=False):
    """Only known executable/location fields are translated; hashes stay exact."""
    path = Path(path)
    if path.name not in {'active.json', 'codex-integration.json', 'codex-relay.json', 'runtime.json'}:
        return value
    if not (path.parent / '.harness-tool.json').is_file():
        return value
    if path.name == 'active.json':
        if not {'launchers', 'python', 'binDir'} <= value.keys():
            return value
        return Binding(path.parent, value).active(value, reverse=reverse)
    fields = {'codex-integration.json': ('directory', 'original'), 'codex-relay.json': ('profiles',),
              'runtime.json': ('root',)}.get(path.name)
    if fields is None or not (path.parent / 'active.json').is_file():
        return value
    bound = binding(path.parent)
    result = copy.deepcopy(value)
    for field in fields:
        if result.get(field) is not None:
            result[field] = bound.path(result[field], reverse=reverse)
    return result


def shell_entry(root, directory, python, arguments=()):
    """Linux entrypoints follow their owned directory, not an old mount prefix."""
    root, directory, python = Path(root), Path(directory), Path(python)
    anchor = (binding(root).current if (root / 'active.json').is_file() else
              Binding(root, {'launchers': {str(root / 'launcher.py'): ''}, 'binDir': str(directory), 'python': str(python)}).anchor)
    location = '"$_harness_here"/' + shlex.quote(os.path.relpath(root, directory))
    interpreter = ('"$_harness_root"/' + shlex.quote(os.path.relpath(python, root))) if python.is_relative_to(anchor) else shlex.quote(str(python))
    return ('#!/bin/sh\n_harness_here=$(realpath -ms -- "$(dirname -- "$0")") || exit 1\n'
            '_harness_root=$(realpath -ms -- ' + location + ') || exit 1\n'
            '[ ! -L "$_harness_here" ] && [ ! -L "$_harness_root" ] || exit 1\n'
            '_harness_parent=$(CDPATH= cd -- "$(dirname -- "$_harness_root")" && pwd -P) || exit 1\n'
            '_harness_root="$_harness_parent/$(basename -- "$_harness_root")"\n'
            'exec ' + interpreter + ' -B "$_harness_root/launcher.py" '
            + ''.join(shlex.quote(arg) + ' ' for arg in arguments) + '"$@"\n').encode()


def home_expression(directory, home):
    path, home = Path(directory), Path(home)
    if path.is_relative_to(home):
        return '"${HOME}"/' + shlex.quote(path.relative_to(home).as_posix())
    return shlex.quote(str(path))


def repair_entrypoints(root):
    """Recoverable, exact-byte transition of an owned POSIX command entrypoint."""
    from . import distribution as dist
    if os.name != 'posix':
        return {'repaired': False, 'writes': 0}
    root = dist._storage_path(root)
    journal = checked_path(root / '.entrypoint-migration.json')
    dist._owned_root(root)
    with dist._launcher_repair_lock(root):
        if journal.exists():
            value = dist._read_json(journal)
            if (set(value) != {'schema', 'active', 'entry'} or type(value['schema']) is not int or value['schema'] != 1
                    or not isinstance(value['active'], str) or not isinstance(value['entry'], str)):
                raise ValueError('Invalid entrypoint recovery record; preserve it')
            before = value['active'].encode('utf-8')
            old = value['entry'].encode('utf-8')
            active = Binding(root, json.loads(before)).active(json.loads(before))
        else:
            state = dist._installation_status(root)
            before = (root / 'active.json').read_bytes()
            active = {key: item for key, item in state.items() if key not in {'dataRoot', 'sourceRoot', 'releasePath', 'release_root'}}
            old = checked_path(Path(active['binDir']) / active.get('command', 'harness')).read_bytes()
        path = checked_path(Path(active['binDir']) / active.get('command', 'harness'))
        expected = active['launchers'].get(str(path))
        if hashlib.sha256(old).hexdigest() != expected or len(old) > 65536 or len(before) > 65536:
            raise ValueError('Entrypoint recovery does not match its ownership receipt')
        desired = shell_entry(root, path.parent, active['python'])
        active['pathOrigin'] = Binding(root, active).origin
        active['launchers'][str(path)] = hashlib.sha256(desired).hexdigest()
        after = (json.dumps(record(root / 'active.json', active, reverse=True), indent=2, sort_keys=True) + '\n').encode()
        current, entry = (root / 'active.json').read_bytes(), path.read_bytes()
        if current not in (before, after) or entry not in (old, desired):
            raise ValueError('Installation changed during entrypoint repair; concurrent edits preserved')
        hashes = {**active['launchers'], str(path): hashlib.sha256(entry).hexdigest()}
        dist._installation_status(root, launcher_hashes_override=hashes)
        if not journal.exists() and current == after and entry == desired:
            return {'repaired': False, 'writes': 0}
        if not journal.exists():
            dist._write_json(journal, {'schema': 1, 'active': before.decode(), 'entry': old.decode()})
        from .shell import _replace_profile
        if entry != desired:
            _replace_profile(path, entry, desired)
        if current != after:
            _replace_profile(root / 'active.json', current, after)
        dist._installation_status(root)
        journal.unlink()
        return {'repaired': True, 'writes': int(entry != desired) + int(current != after)}
