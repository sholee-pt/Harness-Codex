"""Use the generator's OS lock implementation without changing import search paths."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from .paths import checked_path

_path = checked_path(Path(__file__).resolve().parents[1] / '.agents/skills/harness/scripts/harness_eval_lock.py')
_spec = importlib.util.spec_from_file_location('_harness_shared_lock', _path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
FileLock = _module.FileLock


def state_lock(folder, *, timeout=1):
    return FileLock(checked_path(folder / '.state.lock'), timeout=timeout)


def process_alive(pid):
    if not 0 < pid < 2**32:
        raise ValueError('Invalid legacy lock process')
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
