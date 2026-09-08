"""Confirmed tool removal; validate every retained release before staging any file.

Projects, Conda environments, shared command directories and unknown files are
outside the removal set. Staging failures restore the original paths. Cleanup
after commit deletes individual unchanged files only and reports any leftovers.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
import uuid

from . import distribution as dist


def _io_path(path: Path) -> Path:
    # Staging adds a sibling directory name. Windows must still inspect links
    # and remove files when that pushes an otherwise valid path past MAX_PATH.
    value = str(path.absolute())
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        value = '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return dist._storage_path(value)


def _fingerprint(path: Path) -> tuple:
    path = _io_path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > dist.MAX_FILE_BYTES:
        raise ValueError(f'Expected a bounded regular file: {path}')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (info.st_size, info.st_mtime_ns, info.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('Installation changed while preparing removal')
    return digest, info.st_size, info.st_mtime_ns, stat.S_IMODE(info.st_mode)


def _path_action(bin_dir: Path, *, dry_run=True, expected=None) -> dict:
    if os.name == 'nt':
        from .windows_path import unregister_path
    else:
        from .shell import unregister_path
    return unregister_path(bin_dir, dry_run=dry_run, expected=expected)


def _windows_batch_parent() -> bool:
    if os.name != 'nt' or not os.environ.get('HARNESS_TOOL_HOME') or Path(sys.argv[0]).name != 'harness.py':
        return False
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, os.getppid())  # Query limited information only.
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        name = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(name))
        if not kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return Path(name.value).name.casefold() == 'cmd.exe'
    finally:
        kernel.CloseHandle(handle)


def prepare(data_root: Path, *, locked=False) -> dict:
    root = dist._storage_path(data_root)
    verified = {root / name: _fingerprint(root / name)[0] for name in ('.harness-tool.json', 'active.json')}
    state = dist.installed_status(root)
    verified.update({Path(path): digest for path, digest in state['launchers'].items()})
    binary = dist._storage_path(state['binDir'])
    if root == binary or root in binary.parents or binary in root.parents:
        raise ValueError('Tool and command directories must not overlap')
    if root == Path(sys.prefix).resolve() or root in Path(sys.prefix).resolve().parents:
        raise ValueError('The Conda interpreter must be outside the tool removal directory')
    if not locked and (root / '.install.lock').exists():
        raise ValueError('Another installation is active; retry uninstall after it finishes')
    expected = {root / '.harness-tool.json', root / 'active.json', root / 'launcher.py'}
    for release in (root / 'releases').iterdir():
        if not dist.RELEASE_RE.fullmatch(release.name):
            raise ValueError(f'Unrecognized release preserved: {release}')
        snapshot = dist._snapshot(release, managed=True)
        hashes = dist._hashes(snapshot)
        receipt_path = root / 'receipts' / (release.name + '.json')
        verified[receipt_path] = _fingerprint(receipt_path)[0]
        receipt = dist._read_json(receipt_path)
        if (receipt.get('schema') != 1 or receipt.get('runtime', 'codex') != 'codex'
                or receipt.get('files') != hashes or receipt.get('treeHash') != dist._tree_hash(hashes)):
            raise ValueError(f'Changed or invalid retained release preserved: {release}')
        if release.name.startswith('content-') and release.name != 'content-' + receipt['treeHash']:
            raise ValueError('Retained release identity does not match its receipt')
        expected.update(release / name for name in hashes)
        verified.update({release / name: digest for name, digest in hashes.items()})
        expected.add(receipt_path)
    if (root / 'last-check.json').exists():
        verified[root / 'last-check.json'] = _fingerprint(root / 'last-check.json')[0]
        dist.check_due(root)
        expected.add(root / 'last-check.json')
    migration_lock = root / '.launcher-migration.lock'
    if migration_lock.exists():
        verified[migration_lock] = _fingerprint(migration_lock)[0]
        if migration_lock.read_bytes() != b'Harness launcher migration lock v1\n':
            raise ValueError('Unrecognized launcher migration lock preserved')
        expected.add(migration_lock)
    directories = {root, root / 'releases', root / 'receipts'}
    for path in expected:
        directories.update(parent for parent in path.parents if parent == root or root in parent.parents)
    # Do not infer ownership from a parent directory: unknown/empty directories,
    # links, Git metadata, journals and orphaned receipts all block removal.
    seen = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = dist._storage_path(Path(directory) / name)
            if locked and path == root / '.install.lock':
                continue
            if path not in expected and path not in directories:
                raise ValueError(f'Unrecognized file or directory preserved: {path}')
            seen.add(path)
    if not expected.issubset(seen):
        raise ValueError('Managed files disappeared during uninstall inspection')
    external = {dist._storage_path(path) for path in state['launchers'] if Path(path).parent == binary}
    fingerprints = {path: _fingerprint(path) for path in sorted(expected | external)}
    if any(value[0] != verified[path] for path, value in fingerprints.items()):
        raise ValueError('Managed files changed during uninstall inspection')
    shared = any(path not in external for path in binary.iterdir())
    if shared:
        path_change = {'state': 'preserved', 'reason': 'shared command directory'}
    else:
        try:
            path_change = _path_action(binary)
        except (OSError, ValueError) as exc:
            path_change = {'state': 'preserved', 'reason': str(exc)}
    return {'root': root, 'binary': binary, 'version': state['version'], 'command': state.get('command', 'harness'),
            'files': fingerprints, 'directories': directories, 'external': external, 'path': path_change}


def _purge_files(files: dict[Path, tuple], directories: set[Path]) -> list[str]:
    """Never recursively delete a directory that could acquire unrelated files."""
    leftovers = []
    for path, expected in files.items():
        try:
            if _fingerprint(path) != expected:
                raise ValueError('Changed staged file')
            _io_path(path).unlink()
        except (OSError, ValueError):
            leftovers.append(str(path))
    for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        try:
            _io_path(path).rmdir()
        except (OSError, ValueError):
            leftovers.append(str(path))
    return leftovers


def remove(plan: dict) -> dict:
    root = plan['root']
    moved = []
    backup = None
    batch_cleanup = {}
    batch_parent = _windows_batch_parent()
    with dist._lock(root):
        if prepare(root, locked=True) != plan:
            raise ValueError('Installation or PATH changed after the preview; run uninstall again')
        backup = Path(tempfile.mkdtemp(prefix='.harness-uninstall-', dir=root.parent))
        try:
            for path in sorted(root.iterdir()):
                if path.name == '.install.lock':
                    continue
                target = backup / path.name
                os.replace(path, target)
                moved.append((path, target))
            for path in sorted(plan['external']):
                target = path.with_name('.harness-uninstall-' + uuid.uuid4().hex + '-' + path.name)
                if os.path.lexists(target):
                    raise ValueError('Uninstall staging destination already exists')
                os.replace(path, target)
                moved.append((path, target))
                if batch_parent and path.suffix.lower() == '.cmd':
                    # CMD resumes reading its batch file after Python exits.
                    # Leave the original bytes plus a self-delete-and-exit line
                    # in its place, so even legacy launchers finish successfully.
                    # End CMD's batch context before deleting the file; deleting
                    # first makes even `exit /b` try to reopen the missing batch.
                    payload = target.read_bytes() + b'@(goto) 2>nul & del "%~f0"\r\n'
                    with path.open('xb') as output:
                        output.write(payload)
                        output.flush()
                        os.fsync(output.fileno())
                    batch_cleanup[path] = payload
            staged = {}
            for path, fingerprint in plan['files'].items():
                target = next(destination / path.relative_to(original) for original, destination in moved
                              if original == path or original in path.parents)
                if _fingerprint(target) != fingerprint:
                    raise ValueError('Installation changed during uninstall staging')
                staged[target] = fingerprint
            if plan['path']['state'] == 'would-remove':
                staged_commands = {target for original, target in moved if original in plan['external']} | set(batch_cleanup)
                if set(plan['binary'].iterdir()) != staged_commands:
                    raise ValueError('Command directory changed during uninstall; preserving PATH')
                _path_action(plan['binary'], dry_run=False, expected=plan['path'])
        except BaseException:
            # Rename back without overwriting a file created concurrently. Keep
            # the staged original if restoration cannot be completed safely.
            failures = []
            for path, payload in batch_cleanup.items():
                try:
                    if _io_path(path).read_bytes() != payload:
                        raise ValueError('Batch cleanup file changed')
                    _io_path(path).unlink()
                except (OSError, ValueError):
                    failures.append(str(path))
            for original, target in reversed(moved):
                try:
                    if os.path.lexists(original):
                        raise ValueError('Original path was recreated')
                    os.replace(dist._storage_path(target), dist._storage_path(original))
                except (OSError, ValueError):
                    failures.append(str(target))
            try:
                backup.rmdir()
            except OSError:
                pass
            if failures:
                raise ValueError('Uninstall rollback needs manual recovery. Preserved originals: ' + ', '.join(failures))
            raise
        # PATH update is the last pre-commit operation. Subsequent cleanup never
        # restores removed command paths or overwrites edits in staged files.
        directories = {backup / path.relative_to(root) for path in plan['directories']}
        leftovers = _purge_files(staged, directories)
    try:
        root.rmdir()
    except OSError:
        leftovers.append(str(root))
    return {'state': 'uninstalled', 'cleanupRemaining': leftovers, 'batchCleanup': [str(path) for path in batch_cleanup]}


def run(data_root: Path, *, dry_run=False) -> int:
    if not dist._storage_path(data_root).exists():
        print(f'No managed Harness installation at {data_root}. Nothing was removed.')
        return 0
    plan = prepare(data_root)
    print(f"Uninstall {plan['command']} {plan['version']}")
    print(f"Tool storage: {plan['root']}")
    print('Commands: ' + ', '.join(str(path) for path in sorted(plan['external'])))
    print(f"PATH registration: {plan['path']['state']}" +
          (f" ({plan['path']['reason']})" if 'reason' in plan['path'] else ''))
    print('Project harnesses, Conda environments and other commands will be kept.')
    if dry_run:
        print('Dry run. No files or PATH entries were changed.')
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('Uninstall requires an interactive terminal. Use --dry-run to preview without deleting anything.')
    try:
        answer = input('Type yes to uninstall, or press Enter to cancel: ')
    except EOFError:
        answer = ''
    if answer != 'yes':
        print('Uninstall cancelled. Nothing was removed.')
        return 0
    result = remove(plan)
    print(f"Uninstalled {plan['command']}. Open a new terminal to refresh command lookup and PATH.")
    if result['batchCleanup']:
        print('Windows batch cleanup is pending until its launcher returns: ' + ', '.join(result['batchCleanup']))
    if result['cleanupRemaining']:
        print('Some staged files could not be cleaned up; preserved at: ' + ', '.join(result['cleanupRemaining']))
    return 0
