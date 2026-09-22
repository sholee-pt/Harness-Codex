"""User-local Jev credentials; independent of projects, shell profiles and Codex."""
from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import warnings
import webbrowser

from .distribution import _lock
from .paths import checked_path

OWNER = 'harness-typesafe-credential-v1'
KEY_URL = 'https://console.typesafe.ai/keys'
MAX_BYTES = 8192


def _supported():
    return os.name == 'posix'


def home():
    path = Path(os.environ.get('HARNESS_CREDENTIAL_HOME', str(Path.home() / '.local/share/harness-codex-credentials'))).expanduser()
    if not path.is_absolute():
        raise ValueError('HARNESS_CREDENTIAL_HOME must be an absolute user-owned path')
    return checked_path(path)


def _key(value):
    if not isinstance(value, str):
        raise ValueError('Invalid TypeSafe credential; value hidden')
    value = value.strip()
    if not value or len(value) > 4096 or any(not 33 <= ord(c) <= 126 for c in value):
        raise ValueError('Invalid TypeSafe credential; value hidden')
    return value


def _private(info, *, directory=False):
    if not _supported():
        raise ValueError('Persistent Jev login currently supports Linux; use TYPESAFE_API_KEY on this platform')
    if (info.st_uid != os.getuid() or info.st_mode & 0o077
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or (not directory and (info.st_nlink != 1 or info.st_size > MAX_BYTES))):
        raise ValueError('Unsafe Jev credential ownership or permissions; preserved')


def _read():
    root = home()
    if not root.exists():
        return None
    _private(root.stat(), directory=True)
    path = checked_path(root / 'typesafe.json')
    if not path.exists():
        return None
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        _private(os.fstat(stream.fileno()))
        try:
            value = json.loads(stream.read(MAX_BYTES + 1))
        except (ValueError, UnicodeError):
            raise ValueError('Invalid Jev credential file; preserved') from None
    if not isinstance(value, dict) or set(value) != {'owner', 'apiKey'} or value.get('owner') != OWNER:
        raise ValueError('Unowned Jev credential file; preserved')
    return _key(value['apiKey'])


def resolve():
    """Environment overrides storage; errors never expose a secret or block retrieval."""
    try:
        value = os.environ.get('TYPESAFE_API_KEY', '').strip()
        return _key(value) if value else _read()
    except (OSError, ValueError):
        return None


def save(key):
    key = _key(key)
    if not _supported():
        raise ValueError('Persistent Jev login currently supports Linux; use TYPESAFE_API_KEY on this platform')
    root = home()
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    _private(root.stat(), directory=True)
    with _lock(root):
        if _read() == key:
            return
        descriptor, name = tempfile.mkstemp(prefix='.credential-', dir=root)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
                json.dump({'owner': OWNER, 'apiKey': key}, stream)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            checked_path(root / 'typesafe.json')
            os.replace(name, root / 'typesafe.json')
        finally:
            Path(name).unlink(missing_ok=True)


def forget():
    root = home()
    if _read() is None:
        return False
    with _lock(root):
        if _read() is None:
            return False
        (root / 'typesafe.json').unlink()
    try:
        root.rmdir()
    except OSError:
        pass  # Unrelated files are never removed.
    return True


def validate(key, model):
    """One fixed, non-project probe with a hard process deadline; no secret argv."""
    try:
        result = subprocess.run([sys.executable, '-B', '-m', 'harness_cli.jev_client', '--check-key'],
            input=json.dumps({'key': _key(key), 'model': model}), capture_output=True, text=True,
            encoding='utf-8', cwd=Path(__file__).resolve().parents[1], timeout=4)
        if result.returncode == 0 and result.stdout.strip() in {'valid', 'invalid', 'unverified'}:
            return result.stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 'unverified'


def login(model, *, interactive=True, replace=False):
    if os.environ.get('TYPESAFE_API_KEY', '').strip():
        if not resolve():
            return {'state': 'invalid', 'guidance': 'TYPESAFE_API_KEY has an invalid format; unset or correct it before login.'}
        return {'state': 'environment', 'guidance': 'Using TYPESAFE_API_KEY; no credential was saved. Unset it to use a stored key.'}
    try:
        existing = _read()
        if existing and not replace:
            return {'state': 'stored', 'guidance': 'Saved TypeSafe credential reused; no authentication request.'}
        if not interactive or not sys.stdin.isatty() or not sys.stdout.isatty():
            return {'state': 'missing', 'guidance': 'Run harness-codex jev login in a terminal, or set TYPESAFE_API_KEY.'}
        if not _supported():
            return {'state': 'unavailable', 'guidance': 'Persistent Jev login currently supports Linux; use TYPESAFE_API_KEY.'}
        print('Jev uses a separate TypeSafe account: ' + KEY_URL)
        print('Sign in and create an API key. On SSH, open this link on your own computer.')
        print('One small authentication request may incur provider usage; no project data is sent.')
        print('The key is saved locally with owner-only permissions, without encryption or shell exports.')
        choice = input('Press Enter to open the page, p to paste directly, or s to skip: ').strip().lower()
        if choice not in {'', 'p'}:
            return {'state': 'skipped', 'guidance': 'Credential unchanged; ordinary code search remains available.'}
        if not choice and not os.environ.get('SSH_CONNECTION') and not os.environ.get('SSH_TTY'):
            # A browser launcher must not hold init open on a headless host.
            try:
                subprocess.run([sys.executable, '-B', '-m', 'harness_cli.jev_auth', '--open'],
                    cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=3)
            except (OSError, subprocess.SubprocessError):
                pass
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            key = getpass.getpass('Paste API key (hidden), or press Enter to skip: ')
        if not key.strip():
            return {'state': 'skipped', 'guidance': 'Credential unchanged; ordinary code search remains available.'}
        key = _key(key)
        print('Checking TypeSafe authentication...')
        result = validate(key, model)
        if result == 'invalid':
            return {'state': 'invalid', 'guidance': 'TypeSafe rejected the key. The previous credential was preserved; retry jev login.'}
        save(key)
        return {'state': 'saved', 'verification': result,
                'guidance': 'Credential saved; no source command or terminal restart is needed.' +
                    (' Network/service verification was unavailable; the key is not yet verified.' if result == 'unverified' else '')}
    except (EOFError, KeyboardInterrupt):
        print()
        return {'state': 'skipped', 'guidance': 'Credential unchanged; ordinary code search remains available.'}
    except (OSError, ValueError, getpass.GetPassWarning):
        return {'state': 'unavailable', 'guidance': 'Credential setup unavailable; existing files preserved. Check terminal and credential permissions, then retry jev login.'}


def run(args, model):
    if args.jev_action == 'login':
        result = login(model, interactive=not args.json, replace=args.replace_key)
    else:
        if not args.yes:
            if args.json or not sys.stdin.isatty() or not sys.stdout.isatty():
                raise ValueError('Use jev logout --yes to remove the saved TypeSafe credential')
            if input('Type yes to remove the saved TypeSafe key for all projects: ') != 'yes':
                print('Jev logout cancelled.')
                return 0
        removed = forget()
        result = {'state': 'removed' if removed else 'absent',
                  'guidance': 'Project settings are unchanged. Any TYPESAFE_API_KEY environment value still takes precedence.'}
    from . import presentation as ui
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        ui.report(result, title='Jev authentication')
    return 1 if result['state'] in {'invalid', 'unavailable', 'missing'} else 0


if __name__ == '__main__' and sys.argv[1:] == ['--open']:
    webbrowser.open(KEY_URL)
