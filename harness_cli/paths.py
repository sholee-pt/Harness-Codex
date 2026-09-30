"""Low-level CLI path checks, independent of installers and Git update code."""
from __future__ import annotations

import os
from pathlib import Path
import stat


def is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def checked_path(value, *, error_type=ValueError,
                 message="symlinks and filesystem reparse points are not supported") -> Path:
    # Inspect each hop before resolving; resolving first would hide links/junctions.
    path = Path(os.path.abspath(os.path.expanduser(os.fspath(value))))
    for ancestor in reversed((path, *path.parents)):
        if os.path.lexists(ancestor) and is_link(ancestor):
            raise error_type(message)
    return path


def storage_location(value) -> Path:
    """Resolve external POSIX directory aliases, never the managed root itself."""
    path = Path(os.path.abspath(os.path.expanduser(os.fspath(value))))
    if os.name == 'posix':
        try:
            path = path.parent.resolve() / path.name
        except RuntimeError as exc:
            raise ValueError(f'Cannot resolve installation parent: {path.parent}') from exc
    return checked_path(path)


def user_home(value=None) -> Path:
    """The account home is an external location; managed children stay checked."""
    path = Path(value) if value is not None else Path.home()
    try:
        return checked_path(path.resolve() if os.name == 'posix' else path)
    except RuntimeError as exc:
        raise ValueError(f'Cannot resolve account home: {path}') from exc
