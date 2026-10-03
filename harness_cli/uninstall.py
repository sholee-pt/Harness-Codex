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


def _fingerprint(path: Path, *, max_bytes=dist.MAX_FILE_BYTES) -> tuple:
    path = _io_path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
        raise ValueError(f'Expected a bounded regular file: {path}')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    if (info.st_size, info.st_mtime_ns, info.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('Installation changed while preparing removal')
    return digest, info.st_size, info.st_mtime_ns, stat.S_IMODE(info.st_mode)


def _path_action(bin_dir: Path, *, dry_run=True, expected=None, previous=None) -> dict:
    if os.name == 'nt':
        from .windows_path import unregister_path
    else:
        from .shell import unregister_path
    return unregister_path(bin_dir, dry_run=dry_run, expected=expected, **({'previous': previous} if os.name != 'nt' else {}))


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
    runtime = None
    if (root / 'runtime.json').exists():
        from .footprint import inspect
        runtime = inspect(dist._read_json(root / 'runtime.json'), root)
        verified[root / 'runtime.json'] = _fingerprint(root / 'runtime.json')[0]
        expected.add(root / 'runtime.json')
    from .native_ui import removal_files
    from . import codex_integration, integration_path
    integration = codex_integration.read(root)
    native_files = removal_files(root)
    expected.update(native_files)
    verified.update({path: entry['sha256'] for path, entry in native_files.items()})
    directories = {root, root / 'releases', root / 'receipts'}
    for path in expected:
        directories.update(parent for parent in path.parents if parent == root or root in parent.parents)
    # Unknown entries stay in place. Pending control records still require
    # recovery; never traverse an unowned directory or a redirected entry.
    seen, retained = set(), []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in list(dirs) + files:
            path = Path(directory) / name
            if locked and path == root / '.install.lock':
                continue
            if path not in expected and path not in directories:
                if path.parent == root / 'receipts' or path.name in {'.install.lock', '.launcher-migration.json', '.entrypoint-migration.json'}:
                    raise ValueError(f'Unrecognized control record requires recovery: {path}')
                retained.append(str(path))
                if name in dirs:
                    dirs.remove(name)
                continue
            dist._storage_path(path)
            seen.add(path)
    if not expected.issubset(seen):
        raise ValueError('Managed files disappeared during uninstall inspection')
    external = {dist._storage_path(path) for path in state['launchers'] if Path(path).parent == binary}
    fingerprints = {path: _fingerprint(path, max_bytes=max(dist.MAX_FILE_BYTES, native_files.get(path, {}).get('size', 0)))
                    for path in sorted(expected | external)}
    if any(value[0] != verified[path] for path, value in fingerprints.items()):
        raise ValueError('Managed files changed during uninstall inspection')
    shared = any(path not in external for path in binary.iterdir())
    from .installation_paths import binding
    bound = binding(root)
    binary_alias = bound.path(str(binary), reverse=True)
    if shared:
        path_change = {'state': 'preserved', 'reason': 'shared command directory'}
    else:
        try:
            path_change = _path_action(binary, previous=binary_alias)
        except (OSError, ValueError) as exc:
            path_change = {'state': 'preserved', 'reason': str(exc)}
    integration_change = None
    if integration:
        integration_change = integration_path.plan(previous=integration['directory'],
            remove_tool=binary if path_change['state'] == 'would-remove' else None,
            previous_alias=bound.path(integration['directory'], reverse=True), tool_alias=binary_alias)
    from .maintenance import removal_plan
    hooks = removal_plan(root, installed=state)
    return {'root': root, 'binary': binary, 'version': state['version'], 'command': state.get('command', 'harness'),
            'files': fingerprints, 'directories': directories, 'external': external, 'path': path_change,
            'integrationPath': integration_change, 'runtime': runtime, 'hooks': hooks, 'binaryAlias': binary_alias,
            'retained': sorted(retained)}


def _purge_files(files: dict[Path, tuple], directories: set[Path]) -> list[str]:
    """Never recursively delete a directory that could acquire unrelated files."""
    leftovers = []
    for path, expected in files.items():
        try:
            if _fingerprint(path, max_bytes=max(dist.MAX_FILE_BYTES, expected[1])) != expected:
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
    hook_changes = []
    batch_parent = _windows_batch_parent()
    with dist._lock(root):
        if prepare(root, locked=True) != plan:
            raise ValueError('Installation or PATH changed after the preview; run uninstall again')
        backup = Path(tempfile.mkdtemp(prefix='.harness-uninstall-', dir=root.parent))
        staging_directories = {backup}
        try:
            from .hook_state import apply_changes, rollback_changes
            apply_changes(plan['hooks'].get('changes', []), hook_changes)
            for path in sorted(set(plan['files']) - plan['external']):
                target = backup / path.relative_to(root)
                staging_directories.update(parent for parent in target.parents if parent == backup or backup in parent.parents)
                _io_path(target.parent).mkdir(parents=True, exist_ok=True)
                os.replace(_io_path(path), _io_path(target))
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
                if _fingerprint(target, max_bytes=max(dist.MAX_FILE_BYTES, fingerprint[1])) != fingerprint:
                    raise ValueError('Installation changed during uninstall staging')
                staged[target] = fingerprint
            if plan['path']['state'] == 'would-remove':
                staged_commands = {target for original, target in moved if original in plan['external']} | set(batch_cleanup)
                if set(plan['binary'].iterdir()) != staged_commands:
                    raise ValueError('Command directory changed during uninstall; preserving PATH')
                if plan['integrationPath'] is None:
                    _path_action(plan['binary'], dry_run=False, expected=plan['path'], previous=plan['binaryAlias'])
            if plan['integrationPath'] is not None:
                from .integration_path import apply
                apply(plan['integrationPath'])
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
            failures.extend(rollback_changes(hook_changes, backup))
            for directory in sorted(staging_directories - {backup}, key=lambda p: len(p.parts), reverse=True):
                try:
                    _io_path(directory).rmdir()
                except (OSError, ValueError):
                    pass
            try:
                backup.rmdir()
            except OSError:
                pass
            if failures:
                raise ValueError('Uninstall rollback needs manual recovery. Preserved originals: ' + ', '.join(failures))
            raise
        # PATH update is the last pre-commit operation. Subsequent cleanup never
        # restores removed command paths or overwrites edits in staged files.
        leftovers = _purge_files(staged, staging_directories)
        for directory in sorted(plan['directories'] - {root}, key=lambda p: len(p.parts), reverse=True):
            try:
                _io_path(directory).rmdir()
            except (OSError, ValueError):
                pass  # Remaining user files and concurrent additions stay in place.
    try:
        root.rmdir()
    except OSError:
        leftovers.append(str(root))
    return {'state': 'uninstalled', 'cleanupRemaining': leftovers, 'batchCleanup': [str(path) for path in batch_cleanup],
            'retained': plan['retained']}


def run(data_root: Path, *, dry_run=False) -> int:
    from . import presentation as ui
    display = ui.Progress('', stream=sys.stdout)
    if not dist._storage_path(data_root).exists():
        display.line('\nHarness is not installed at ' + str(data_root) + '. Nothing was removed.\n', style='muted')
        return 0
    plan = prepare(data_root)
    display.line(f"\nUninstall {plan['command']} {plan['version']}", style='heading')
    display.line('\nWill remove', style='heading')
    display.line(f"  Tool storage: {plan['root']}")
    for path in sorted(plan['external']):
        display.line('  Command: ' + str(path))
    display.line('  Owned hook registrations and the saved TypeSafe key, when ownership is valid.')
    if plan['runtime']:
        display.line('  Unchanged installer-owned runtime files: ' + plan['runtime']['root'])
    display.line('\nWill keep', style='heading')
    display.line('  Project harnesses, reused Conda environments and other commands.')
    display.line('  User-added/modified runtime files and shell environment values.')
    for path in plan['retained']:
        display.line('  Unowned installation entry: ' + path)
    display.line('\nPATH: ' + ('remove the owned registration' if plan['path']['state'] == 'would-remove' else 'preserve existing settings'), style='muted')
    if 'reason' in plan['path']:
        display.line('  ' + plan['path']['reason'], style='muted')
    for warning in plan['hooks'].get('warnings', []):
        display.line('  ' + warning, style='warning')
    display.line('')
    if dry_run:
        print('Dry run. No files or PATH entries were changed.')
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('Uninstall requires an interactive terminal. Use --dry-run to preview without deleting anything.')
    if not ui.confirm('Uninstall these Harness components?', progress=display):
        display.line('\nUninstall cancelled. Nothing was removed.\n', style='muted')
        return 0
    cleanup_source = None
    if plan['runtime'] and os.name == 'nt':
        cleanup_source = Path(__file__).with_name('runtime_cleanup.ps1').read_bytes()
    from .jev_auth import forget, home as credential_home
    with ui.Progress('Removing owned Harness files and settings', stream=sys.stdout, compact=True) as progress:
        result = remove(plan)
        try:
            forget()
        except (OSError, ValueError, RuntimeError):
            progress.line('The tool removal step completed. TypeSafe credential cleanup could not be verified; the configured storage was preserved.', style='warning')
            try:
                location = str(credential_home() / 'typesafe.json')
                progress.line('Credential file to inspect: ' + location, style='warning')
            except (OSError, ValueError, RuntimeError):
                configured = os.environ.get('HARNESS_CREDENTIAL_HOME', '~/.local/share/harness-codex-credentials')
                progress.line('Configured credential directory (not resolved): ' + configured, style='warning')
            progress.line('Inspect the preserved location and its ownership/permissions. Reinstall Harness before using harness-codex jev logout for removal.', style='warning')
        if plan['runtime']:
            from . import footprint
            progress.phase('Cleaning the installer-owned runtime')
            if os.name == 'nt':
                location = footprint.defer_windows_cleanup(plan['runtime'], cleanup_source)
                progress.line('Runtime cleanup will finish after this process exits. Pending cleanup: ' + location, style='muted')
            else:
                remaining = footprint.cleanup(plan['runtime'])
                if remaining:
                    progress.line('Added, modified or busy runtime files were preserved: ' + ', '.join(remaining), style='warning')
    display.line(f"\nUninstalled {plan['command']}.", style='success')
    display.line('Open a new terminal to refresh command lookup and PATH.\n', style='muted')
    if result['batchCleanup']:
        display.line('Windows batch cleanup is pending until its launcher returns: ' + ', '.join(result['batchCleanup']), style='muted')
    if result['cleanupRemaining']:
        display.line('Remaining installation directories or staged files were preserved at: ' + ', '.join(result['cleanupRemaining']), style='warning')
    return 0
