"""Idempotent Bash PATH registration; never evaluate a user's startup file."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import stat

from .distribution import _path

START = '# >>> harness-codex PATH >>>'
END = '# <<< harness-codex PATH <<<'


def register_path(bin_dir: Path, *, home: Path | None = None, dry_run: bool = False) -> dict:
    home = _path(home or Path.home())
    directory = str(_path(bin_dir))
    if any(ord(c) < 32 or ord(c) == 127 for c in directory) or ':' in directory:
        raise ValueError('Bash PATH directory contains unsupported characters')
    profile = _path(home / '.bashrc')
    if profile.exists() and (not profile.is_file() or profile.stat().st_size > 1024 * 1024):
        raise ValueError('Bash startup file must be a regular file no larger than 1 MiB')
    before = profile.read_bytes() if profile.exists() else b''
    text = before.decode('utf-8')
    quoted = shlex.quote(directory)
    block = (f'{START}\ncase ":${{PATH:-}}:" in\n'
             f'  *:{quoted}:*) ;;\n  *) export PATH={quoted}"${{PATH:+:$PATH}}" ;;\nesac\n{END}\n').encode()
    if text.count(START) == 1 and text.count(END) == 1 and block.decode() in text:
        return {'profile': str(profile), 'state': 'unchanged', 'writes': 0}
    # Recognize literal exports without executing expansions, commands or the rc.
    for line in text.splitlines():
        try:
            words = shlex.split(line, comments=True)
        except ValueError:
            continue
        if len(words) != 2 or words[0] != 'export' or not words[1].startswith('PATH='):
            continue
        value = words[1][5:].replace('${HOME}', str(home)).replace('$HOME', str(home))
        if directory in value.split(':') or value.startswith(directory + '${PATH:+:$PATH}'):
            return {'profile': str(profile), 'state': 'unchanged', 'writes': 0}
    if START in text or END in text:
        raise ValueError('Existing harness-codex PATH block differs; preserve it and review .bashrc before changing the bin directory')
    after = before + (b'\n' if before and not before.endswith(b'\n') else b'') + block
    if dry_run:
        return {'profile': str(profile), 'state': 'would-update', 'writes': 0}
    # Use a sibling created exclusively; recheck bytes before atomic replacement.
    import tempfile
    fd, name = tempfile.mkstemp(prefix='.harness-codex-path-', dir=home)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        if profile.exists():
            if profile.read_bytes() != before:
                raise ValueError('Bash startup file changed during PATH registration')
            temporary.chmod(stat.S_IMODE(profile.stat().st_mode))
        elif before:
            raise ValueError('Bash startup file disappeared during PATH registration')
        _path(profile)
        os.replace(temporary, profile)
    finally:
        temporary.unlink(missing_ok=True)
    return {'profile': str(profile), 'state': 'updated', 'writes': 1,
            'currentShell': 'Open a new terminal or run: . ~/.bashrc'}
