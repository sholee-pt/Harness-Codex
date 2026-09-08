"""Register only the current user's Windows PATH, without setx or profile code."""
from __future__ import annotations

import ntpath
import os
from pathlib import Path

from .paths import checked_path as _path


def _normalized(value: str) -> str:
    return ntpath.normcase(ntpath.normpath(ntpath.expandvars(value.strip().strip('"'))))


def _read(registry, key):
    try:
        return registry.QueryValueEx(key, 'Path')
    except FileNotFoundError:
        return None


def _broadcast() -> bool:
    import ctypes
    from ctypes import wintypes
    call = ctypes.windll.user32.SendMessageTimeoutW
    call.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR,
                     wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    call.restype = wintypes.LPARAM
    result = ctypes.c_size_t()
    return bool(call(0xFFFF, 0x1A, 0, 'Environment', 0x0002, 2000, ctypes.byref(result)))


def register_path(bin_dir: Path, *, dry_run: bool = False, registry=None, broadcast=None) -> dict:
    if registry is None:
        import winreg as registry
    directory = str(_path(bin_dir))
    if any(ord(c) < 32 or ord(c) == 127 or c in ';%"' for c in directory):
        raise ValueError('Windows PATH directory contains unsupported characters')
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, 'Environment', 0, registry.KEY_READ) as key:
            before = _read(registry, key)
    except FileNotFoundError:
        before = None
    value, kind = before if before is not None else ('', registry.REG_EXPAND_SZ)
    if not isinstance(value, str) or kind not in (registry.REG_SZ, registry.REG_EXPAND_SZ):
        raise ValueError('User PATH must be a Windows string registry value')
    result = {'profile': r'HKCU\Environment\Path', 'state': 'unchanged', 'writes': 0}
    if any(_normalized(entry) == _normalized(directory) for entry in value.split(';')):
        return result
    after = value + (';' if value and not value.endswith(';') else '') + directory
    if len(after) > 32760:
        raise ValueError('User PATH would exceed the supported Windows environment length')
    if dry_run:
        return {**result, 'state': 'would-update'}
    with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, 'Environment', 0,
                              registry.KEY_QUERY_VALUE | registry.KEY_SET_VALUE) as key:
        if _read(registry, key) != before:
            raise ValueError('User PATH changed during registration; retry without overwriting it')
        registry.SetValueEx(key, 'Path', 0, kind, after)
    notified = (broadcast or _broadcast)()
    return {**result, 'state': 'updated', 'writes': 1, 'notified': notified,
            'currentShell': 'Open a new terminal to load the updated user PATH.'}
