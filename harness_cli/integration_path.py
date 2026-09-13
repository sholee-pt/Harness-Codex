"""Reversible registration of a versioned native Codex directory, not a shim."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex

from .paths import checked_path

START = '# >>> harness-codex native integration >>>'
END = '# <<< harness-codex native integration <<<'


def block(directory):
    directory = str(checked_path(directory))
    if ':' in directory or any(ord(c) < 32 or ord(c) == 127 for c in directory):
        raise ValueError('Unsupported native Codex PATH directory')
    quoted = shlex.quote(directory)
    return (f'{START}\ncase ":${{PATH:-}}:" in\n'
            f'  *:{quoted}:*) ;;\n  *) export PATH={quoted}"${{PATH:+:$PATH}}" ;;\nesac\n{END}\n').encode()


def plan(directory=None, *, previous=None, remove_tool=None, home=None, registry=None):
    """Capture one compare-and-swap PATH edit; user content stays outside ownership."""
    if os.name == 'nt' or registry is not None:
        from . import windows_path as windows
        if registry is None:
            import winreg as registry
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, 'Environment', 0, registry.KEY_READ) as key:
                before = windows._read(registry, key)
        except FileNotFoundError:
            before = None
        value, kind = before if before is not None else ('', registry.REG_EXPAND_SZ)
        if not isinstance(value, str) or kind not in (registry.REG_SZ, registry.REG_EXPAND_SZ):
            raise ValueError('User PATH is not a supported registry string')
        entries = value.split(';') if value else []
        for owned in (previous, remove_tool):
            if owned:
                entries = [entry for entry in entries if entry.casefold().rstrip('\\/') != str(owned).casefold().rstrip('\\/')]
        if directory:
            directory = str(checked_path(directory))
            if any(ord(c) < 32 or ord(c) == 127 or c in ';%"' for c in directory):
                raise ValueError('Unsupported native Codex PATH directory')
            if any(windows._normalized(entry) == windows._normalized(directory) for entry in entries):
                raise ValueError('Native Codex PATH entry exists without matching ownership; preserve it')
            entries.insert(0, directory)
        after = (';'.join(entries), kind)
        if len(after[0]) > 32760:
            raise ValueError('User PATH exceeds its supported length')
        return {'kind': 'windows', 'before': before, 'after': after,
                'changed': (before or ('', kind)) != after}
    profile = checked_path((home or Path.home()) / '.bashrc')
    if profile.exists() and (not profile.is_file() or profile.stat().st_size > 1024 * 1024):
        raise ValueError('Bash startup file must be a bounded regular file')
    before = profile.read_bytes() if profile.exists() else b''
    before.decode('utf-8')
    after = before
    if directory and previous and str(directory) == str(previous) and not remove_tool:
        owned = block(directory)
        if after.count(START.encode()) == after.count(END.encode()) == 1 and owned in after:
            return {'kind': 'bash', 'profile': str(profile), 'before': before, 'after': before, 'changed': False}
    if previous and block(previous) in after:
        after = after.replace(block(previous), b'', 1)
    if START.encode() in after or END.encode() in after:
        raise ValueError('Modified or unowned native Codex PATH block preserved; review .bashrc')
    if remove_tool:
        from .shell import _block
        tool_block = _block(str(checked_path(remove_tool)))
        if after.count(tool_block) == 1:
            after = after.replace(tool_block, b'', 1)
    if directory:
        after += (b'\n' if after and not after.endswith(b'\n') else b'') + block(directory)
    return {'kind': 'bash', 'profile': str(profile), 'before': before, 'after': after, 'changed': before != after}


def apply(change, *, registry=None, broadcast=None):
    if not change['changed']:
        return
    if change['kind'] == 'bash':
        from .shell import _replace_profile
        profile = checked_path(change['profile'])
        current = profile.read_bytes() if profile.exists() else b''
        if current != change['before']:
            raise ValueError('Bash PATH changed during native integration; retry')
        _replace_profile(profile, current, change['after'])
        return
    from . import windows_path as windows
    if registry is None:
        import winreg as registry
    with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, 'Environment', 0,
                             registry.KEY_QUERY_VALUE | registry.KEY_SET_VALUE) as key:
        if windows._read(registry, key) != change['before']:
            raise ValueError('User PATH changed during native integration; retry')
        value, kind = change['after']
        registry.SetValueEx(key, 'Path', 0, kind, value)
    try:
        (broadcast or windows._broadcast)()
    except OSError:
        pass  # Fresh terminals still load the committed PATH.


def describe(change):
    before = change['before']
    data = before if isinstance(before, bytes) else json.dumps(before).encode()
    return {'profile': change.get('profile', r'HKCU\Environment\Path'),
            'state': 'would-update' if change['changed'] else 'unchanged',
            'fingerprint': hashlib.sha256(data).hexdigest()}
