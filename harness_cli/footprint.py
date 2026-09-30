"""Receipts for a runtime created exclusively by the installer for one tool home.

Reused Conda installations are never inferred to be owned from their name. Each
file is removed only while it still matches the initial runtime receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile

from . import distribution as dist
from .paths import user_home
from .shell import _replace_profile

MARKER = '.harness-runtime-owner'
RECEIPT = '.harness-runtime-files.json'


def _relative(name: str) -> str:
    # Native Conda package paths are platform-specific. The portable source
    # archive validator must not reject valid Unix names such as `con`.
    if os.name == 'nt':
        return dist._relative(name)
    if (not isinstance(name, str) or not name or '\0' in name or PurePosixPath(name).is_absolute()
            or any(part in {'', '.', '..'} for part in name.split('/'))):
        raise ValueError('Unsafe runtime receipt path: ' + repr(name))
    return name


def marker(data_root: Path) -> bytes:
    return ('harness-codex runtime v1\n' + str(data_root.resolve()) + '\n').encode('utf-8')


def validate_root(root: Path, data_root: Path) -> Path:
    root, data_root = dist._storage_path(root).resolve(), dist._storage_path(data_root).resolve()
    if root == data_root or root in data_root.parents or data_root in root.parents:
        raise ValueError('Runtime and CLI storage must be separate directories')
    contents = dist._storage_path(root / MARKER).read_text(encoding='utf-8').splitlines()
    if len(contents) != 2 or contents[0] != 'harness-codex runtime v1' or dist._storage_path(contents[1]).resolve() != data_root:
        raise ValueError('Runtime ownership marker does not match this tool installation')
    return root


def _entry(path: Path) -> dict:
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode):
        return {'link': os.readlink(path)}
    if not stat.S_ISREG(before.st_mode) or getattr(before, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Runtime ownership requires regular files or Unix symlinks')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    after = path.lstat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('Runtime file changed during inspection')
    return {'sha256': digest.hexdigest(), 'size': before.st_size}


def _windows_registration(root: Path) -> dict:
    if os.name != 'nt':
        return {}
    import winreg
    base = r'Software\Microsoft\Windows\CurrentVersion\Uninstall'
    result = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as parent:
            for index in range(winreg.QueryInfoKey(parent)[0]):
                name = winreg.EnumKey(parent, index)
                with winreg.OpenKey(parent, name) as child:
                    subkeys, count, _ = winreg.QueryInfoKey(child)
                    values = {entry[0]: [entry[1], entry[2]] for entry in (winreg.EnumValue(child, i) for i in range(count))}
                location = values.get('InstallLocation', [None])[0]
                if (not subkeys and isinstance(location, str) and Path(location).resolve() == root
                        and all(type(v[0]) in {str, int} for v in values.values())):
                    result[base + '\\' + name] = values
    except FileNotFoundError:
        pass
    return result


def record(root: Path, data_root: Path, *, attach: bool = True) -> dict:
    root, data_root = validate_root(root, data_root), dist._storage_path(data_root).resolve()
    prefix = Path(sys.prefix).resolve()
    if root not in prefix.parents or prefix.name != 'harness':
        raise ValueError('Owned runtime must contain the running harness environment')
    receipt_path = dist._storage_path(root / RECEIPT)
    if not receipt_path.exists():
        if os.path.lexists(data_root / 'runtime.json'):
            raise ValueError('Recorded runtime receipt is missing; preserving files instead of claiming them again')
        files, directories = {}, ['.']
        for directory, dirs, names in os.walk(root, followlinks=False):
            parent = Path(directory)
            for name in list(dirs):
                path = parent / name
                if path.is_symlink():
                    files[path.relative_to(root).as_posix()] = _entry(path)
                    dirs.remove(name)
                else:
                    dist._storage_path(path)
                    directories.append(path.relative_to(root).as_posix())
            for name in names:
                path = parent / name
                files[path.relative_to(root).as_posix()] = _entry(path)
                if len(files) > 50000:
                    raise ValueError('Runtime receipt exceeds the supported file count')
        value = {'schema': 1, 'root': str(root), 'dataRoot': str(data_root),
                 'files': files, 'directories': directories,
                 'condaRegistration': str(user_home() / '.conda/environments.txt'),
                 'registry': _windows_registration(root)}
        payload = json.dumps(value, sort_keys=True).encode('utf-8')
        if len(payload) > dist.MAX_FILE_BYTES:
            raise ValueError('Runtime receipt is too large')
        with receipt_path.open('xb') as output:
            output.write(payload)
    reference = {'schema': 1, 'root': str(root), 'receiptSha256': _entry(receipt_path)['sha256']}
    inspect(reference, data_root)
    if attach:
        path = dist._storage_path(data_root / 'runtime.json')
        if not path.exists() or dist._read_json(path) != reference:
            dist._write_json(path, reference)
    return reference


def inspect(reference: dict, data_root: Path) -> dict:
    if set(reference) != {'schema', 'root', 'receiptSha256'} or reference['schema'] != 1:
        raise ValueError('Invalid owned-runtime reference')
    root = validate_root(reference['root'], data_root)
    data_root = dist._storage_path(data_root).resolve()
    if root == data_root or root in data_root.parents or data_root in root.parents:
        raise ValueError('Runtime and CLI storage overlap')
    receipt = dist._storage_path(root / RECEIPT)
    if _entry(receipt).get('sha256') != reference['receiptSha256']:
        raise ValueError('Runtime ownership receipt changed; preserving the runtime')
    if receipt.stat().st_size > dist.MAX_FILE_BYTES:
        raise ValueError('Runtime receipt is too large')
    value = json.loads(receipt.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Invalid runtime receipt')
    if value.get('schema') != 1 or value.get('root') != str(root) or value.get('dataRoot') != str(data_root):
        raise ValueError('Runtime receipt does not match the selected installation')
    if not isinstance(value.get('files'), dict) or not isinstance(value.get('directories'), list):
        raise ValueError('Invalid runtime file list')
    for name, expected in value['files'].items():
        _relative(name)
        if (not isinstance(expected, dict) or not (set(expected) == {'link'} or set(expected) == {'sha256', 'size'})):
            raise ValueError('Invalid runtime file fingerprint')
        if 'sha256' in expected and (not isinstance(expected['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', expected['sha256'])
                                    or type(expected['size']) is not int or expected['size'] < 0):
            raise ValueError('Invalid runtime file hash/size')
        if 'link' in expected and not isinstance(expected['link'], str):
            raise ValueError('Invalid runtime link')
    if value['files'].get(MARKER) != _entry(root / MARKER) or RECEIPT in value['files']:
        raise ValueError('Runtime marker fingerprint mismatch')
    for name in value['directories']:
        if name != '.':
            _relative(name)
    return {**value, 'receiptSha256': reference['receiptSha256']}


def _unregister_conda(plan: dict) -> None:
    prefix = Path(plan['root']) / 'envs/harness'
    if prefix.exists():
        return
    path = dist._storage_path(plan['condaRegistration'])
    if not path.exists() or path.stat().st_size > 1024 * 1024:
        return
    before = path.read_bytes()
    lines = before.splitlines(keepends=True)
    after = b''.join(line for line in lines if Path(line.decode('utf-8').strip()).resolve() != prefix.resolve())
    if after != before:
        _replace_profile(path, before, after)


def _file(root: Path, relative: str) -> Path:
    # Check every parent, but leave the final symlink itself available for unlink.
    path = root / relative
    dist._storage_path(path.parent)
    return path


def cleanup(plan: dict) -> list[str]:
    """Unix permits unlinking the running interpreter; retain unknown/changed files."""
    plan = inspect({'schema': 1, 'root': plan['root'], 'receiptSha256': plan['receiptSha256']}, Path(plan['dataRoot']))
    root = dist._storage_path(plan['root'])
    remaining = []
    for name, expected in plan['files'].items():
        if name == MARKER:
            continue
        path = root / name
        try:
            path = _file(root, name)
            if not os.path.lexists(path):
                continue
            if _entry(path) != expected:
                raise ValueError('Changed runtime file')
            path.unlink()
        except (OSError, ValueError):
            remaining.append(str(path))
    for name in sorted((x for x in plan['directories'] if x != '.'), key=lambda x: len(Path(x).parts), reverse=True):
        try:
            dist._storage_path(root / name).rmdir()
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            remaining.append(str(root / name))
    if not remaining and set(p.name for p in root.iterdir()) == {MARKER, RECEIPT}:
        if _entry(root / RECEIPT).get('sha256') == plan['receiptSha256']:
            (root / RECEIPT).unlink()
            (root / MARKER).unlink()
            root.rmdir()
    else:
        remaining.append(str(root))
    try:
        _unregister_conda(plan)
    except (OSError, ValueError, UnicodeError):
        remaining.append(plan['condaRegistration'])
    return remaining


def _windows_command(script: Path, plan_hash: str) -> tuple[list[str], dict]:
    shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    environment = dict(os.environ, HARNESS_CLEANUP_SCRIPT=str(script), HARNESS_CLEANUP_PLAN=plan_hash,
                       HARNESS_CLEANUP_SOURCE=hashlib.sha256(script.read_bytes()).hexdigest())
    # Execute verified local source like the public bootstrap, without changing
    # execution policy. Paths are arguments through the environment, never code.
    command = '''$bytes = [IO.File]::ReadAllBytes($env:HARNESS_CLEANUP_SCRIPT)
$hasher = [Security.Cryptography.SHA256]::Create()
try { $digest = [BitConverter]::ToString($hasher.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant() }
finally { $hasher.Dispose() }
if ($digest -cne $env:HARNESS_CLEANUP_SOURCE) { throw 'Cleanup source changed' }
& ([scriptblock]::Create([Text.Encoding]::UTF8.GetString($bytes))) -PlanSha256 $env:HARNESS_CLEANUP_PLAN -JobDirectory ([IO.Path]::GetDirectoryName($env:HARNESS_CLEANUP_SCRIPT)) -ScriptPath $env:HARNESS_CLEANUP_SCRIPT
'''
    return [str(shell), '-NoProfile', '-NonInteractive', '-Command', command], environment


def defer_windows_cleanup(plan: dict, source: bytes) -> str:
    """Use Windows PowerShell after the running Python/DLLs exit; no self-executing code from data."""
    job = Path(tempfile.mkdtemp(prefix='harness-codex-cleanup-'))
    (job / 'plan.json').write_text(json.dumps({**plan, 'waitPid': os.getpid()}), encoding='utf-8')
    script = job / 'cleanup.ps1'
    script.write_bytes(source)
    plan_hash = hashlib.sha256((job / 'plan.json').read_bytes()).hexdigest()
    command, environment = _windows_command(script, plan_hash)
    subprocess.Popen(command, env=environment,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
    return str(job)
