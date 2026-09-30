"""Explicit reuse/reset choices for tool installation, separate from projects."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import stat

from . import distribution as dist
from .paths import user_home


def _pause_installer(paused: bool) -> None:
    """Pause the installer's timer while its child asks on the real terminal."""
    name = os.environ.get('HARNESS_INSTALL_PAUSE_FILE')
    if not name:
        return
    path = Path(name)
    if not path.name.startswith('harness-codex-progress-') or path.is_symlink():
        return
    try:
        with path.open('r+', encoding='utf-8', newline='\n') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return
            if stream.read(128) not in {'Harness installation progress\nrunning\n', 'Harness installation progress\npaused\n'}:
                return
            stream.seek(0)
            stream.write('Harness installation progress\n' + ('paused\n' if paused else 'running\n'))
            stream.truncate()
    except OSError:
        pass


def choose(data_root: Path, bin_dir: Path, selection: str) -> tuple[str, dict | None]:
    root, binary = dist._storage_path(data_root), dist._storage_path(bin_dir)
    existing = dist.installed_status(root) if root.exists() and any(root.iterdir()) else None
    traces = existing is not None or any(os.path.lexists(binary / name) for name in ('harness-codex', 'harness-codex.cmd'))
    if os.name != 'nt':
        from .shell import START
        profile = dist._storage_path(user_home() / '.bashrc')
        if profile.is_file() and profile.stat().st_size <= 1024 * 1024:
            traces = traces or START.encode() in profile.read_bytes()
    else:
        from .windows_path import register_path
        traces = traces or register_path(binary, dry_run=True)['state'] == 'unchanged'
    if not traces:
        return 'fresh', None
    if selection != 'ask':
        return selection, existing
    message = ('\nAn existing Harness installation or PATH registration was found.\n'
               '  reuse  Keep its update preferences and verified installation.\n'
               '  reset  Reset Harness update preferences, check cache and managed PATH registration.\n'
               '         Project harnesses and unrelated shell settings are preserved.\n'
               'Choose reuse/reset, or press Enter to cancel: ')
    try:
        _pause_installer(True)
        if sys.stdin.isatty() and sys.stdout.isatty():
            answer = input(message)
        else:
            # A curl | sh bootstrap reads its program from a pipe. Ask through
            # the controlling terminal; never interpret piped script bytes as approval.
            with open('CONIN$' if os.name == 'nt' else '/dev/tty', 'r') as reader, \
                 open('CONOUT$' if os.name == 'nt' else '/dev/tty', 'w') as writer:
                if not reader.isatty() or not writer.isatty():
                    raise OSError('No controlling terminal')
                writer.write(message)
                writer.flush()
                answer = reader.readline().rstrip('\r\n')
    except (OSError, EOFError) as exc:
        raise ValueError('Existing installation needs a choice. Run in a terminal, or specify --existing reuse/reset.') from exc
    finally:
        _pause_installer(False)
    if answer not in {'reuse', 'reset'}:
        raise ValueError('Installation cancelled. Existing tool settings were preserved.')
    return answer, existing


def reset_check_cache(root: Path) -> None:
    root = dist._storage_path(root)
    with dist._lock(root):
        dist.installed_status(root)
        cache = dist._storage_path(root / 'last-check.json')
        if cache.exists():
            dist.check_due(root)
            cache.unlink()


def path_registration(bin_dir: Path, *, reset=False, dry_run=False) -> dict:
    if os.name == 'nt':
        from .windows_path import register_path, unregister_path
        if reset:
            unregister_path(bin_dir, dry_run=dry_run)
        return register_path(bin_dir, dry_run=dry_run)
    from .shell import register_path, reset_path
    return reset_path(bin_dir, dry_run=dry_run) if reset else register_path(bin_dir, dry_run=dry_run)
