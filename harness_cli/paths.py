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
            raise error_type(f'{message}: {ancestor}')
    return path


def storage_location(value) -> Path:
    """Resolve external POSIX directory aliases, never the managed root itself."""
    return external_location(value) if os.name == 'posix' else checked_path(value)


def external_location(value) -> Path:
    """Bind a selected input/output parent while keeping its final entry unlinked."""
    path = Path(value).expanduser()
    try:
        return checked_path(path.parent.resolve() / path.name)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f'Cannot resolve path parent: {path.parent}') from exc


def project_root(value, *, error_type=ValueError) -> Path:
    """Canonicalize an explicitly selected workspace, not its managed children."""
    path = Path(value).expanduser()
    if any(part.rstrip(' .').casefold() == '.git' for part in path.parts):
        raise error_type('Project must not be inside Git metadata')
    try:
        root = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise error_type(f'Project must name an existing directory with a resolvable path: {path}') from exc
    if not root.is_dir():
        raise error_type(f'Project must name an existing directory: {path}')
    if any(part.rstrip(' .').casefold() == '.git' for part in root.parts):
        raise error_type('Project must not resolve inside Git metadata')
    return root


def user_home(value=None) -> Path:
    """The account home is an external location; managed children stay checked."""
    path = Path(value) if value is not None else Path.home()
    try:
        return checked_path(path.resolve() if os.name == 'posix' else path)
    except RuntimeError as exc:
        raise ValueError(f'Cannot resolve account home: {path}') from exc
