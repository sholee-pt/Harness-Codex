"""Portable root observations and bounded, host-specific sandbox diagnostics.

This receipt supplies advice, never permissions or executable configuration.
Project-owned metadata is not a source of executable paths or shell commands.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import socket
import subprocess
import tempfile
import time

from .environment import codex_environment
from .locking import FileLock
from .paths import checked_path, project_root

PATH = '.harness/context.json'
OWNER = 'harness-workspace-context-v1'
STATES = {'available', 'unavailable', 'unknown', 'not-applicable'}
GUIDANCE = ('Use project-relative paths and the current workspace root; old absolute paths in conversation history '
            'may belong to another mount/server. Read harness-codex context once when entering a different host or '
            'resuming a moved project. A recorded sandbox failure is host-specific: do not repeat the same failed '
            'sandbox command; use native approval only when allowed, or ask for host repair. Never silently relax '
            'permissions or treat this diagnostic as authorization.')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read(root):
    path = checked_path(root / PATH)
    if not path.exists():
        return None
    if path.stat().st_size > 65536:
        raise ValueError('Workspace context is too large; existing content was preserved.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Unowned workspace context was preserved.')
    seal = value.pop('sha256', None)
    if (value.get('owner') != OWNER or seal != _digest(value)
            or not isinstance(value.get('roots'), list) or len(value['roots']) > 16
            or not all(isinstance(p, str) and 0 < len(p) <= 4096 and '\0' not in p for p in value['roots'])
            or not isinstance(value.get('hosts'), dict) or len(value['hosts']) > 16):
        raise ValueError('Unowned or modified workspace context was preserved.')
    for record in value['hosts'].values():
        if (not isinstance(record, dict) or record.get('status') not in STATES
                or type(record.get('time')) not in (float, int) or not isinstance(record.get('fingerprint'), str)):
            raise ValueError('Invalid host context was preserved.')
    return value


def owned(root):
    return read(root) is not None


def retrieval_owned(root, digest):
    """A portable static-file receipt conveys no opt-in or executable provenance."""
    try:
        return (read(root) or {}).get('retrievalSkillHash') == digest
    except (OSError, ValueError):
        return False


def record_retrieval(root, digest):
    from .graft import _save
    if read(root) is None:
        return
    with FileLock(checked_path(root / '.harness/context.lock'), timeout=1):
        value = read(root)
        if value is not None:
            value['retrievalSkillHash'] = digest
            _save(checked_path(root / PATH), {**value, 'sha256': _digest(value)})


def host_key():
    identity = [platform.system(), socket.gethostname(), str(getattr(os, 'getuid', lambda: '')())]
    if platform.system() == 'Linux':
        for name in ('/etc/machine-id', '/proc/sys/kernel/random/boot_id'):
            try:
                identity.append(Path(name).read_text().strip())
            except OSError:
                pass
        for name in ('/proc/self/ns/user', '/proc/self/ns/mnt', '/proc/self/ns/net'):
            try:
                identity.append(os.readlink(name))
            except OSError:
                pass
    return _digest(identity)


def _fingerprint(command):
    files = []
    for name in [*command, shutil.which('bwrap') or '']:
        try:
            info = Path(name).stat()
            files.append([str(Path(name).resolve()), info.st_size, info.st_mtime_ns])
        except (OSError, ValueError):
            files.append(str(name))
    controls = []
    for name in ('/proc/sys/kernel/unprivileged_userns_clone', '/proc/sys/user/max_user_namespaces',
                 '/proc/sys/kernel/apparmor_restrict_unprivileged_userns'):
        try:
            controls.append(Path(name).read_text().strip())
        except OSError:
            controls.append(None)
    return _digest([files, controls, platform.release(), os.environ.get('PATH', ''), os.environ.get('CODEX_HOME', '')])


def _run(command, root):
    # File-backed output is bounded on reading; no model call, network or user command.
    with tempfile.TemporaryFile() as output:
        with subprocess.Popen(command, cwd=root, env=codex_environment(), stdin=subprocess.DEVNULL,
                              stdout=output, stderr=output, start_new_session=True) as process:
            try:
                status = process.wait(timeout=5)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                if isinstance(exc, KeyboardInterrupt):
                    raise
                return None, ''
            output.seek(0)
            return status, output.read(8192).decode('utf-8', errors='replace')


def probe(command, root):
    if platform.system() != 'Linux':
        return 'not-applicable'
    try:
        status, help_text = _run([*command, 'sandbox', 'linux', '--help'], root)
        if status != 0 or 'COMMAND' not in help_text:
            return 'unknown'
        # PATH bwrap absence is inconclusive: official Codex can use a bundled helper.
        binary = '/usr/bin/true' if Path('/usr/bin/true').is_file() else '/bin/true'
        status, message = _run([*command, 'sandbox', 'linux', '--', binary], root)
        if status == 0:
            return 'available'
        if any(word in message.casefold() for word in ('bwrap', 'bubblewrap', 'namespace', 'rtm_newaddr', 'sandbox setup')):
            return 'unavailable'
    except (OSError, ValueError):
        pass
    return 'unknown'


def refresh(root, command, *, force=False, previous_root=None):
    from .graft import _save
    root = project_root(root)
    path = checked_path(root / PATH)
    with FileLock(checked_path(root / '.harness/context.lock'), timeout=1):
        value = read(root) or {'owner': OWNER, 'roots': [], 'hosts': {}}
        key, fingerprint = host_key(), _digest([_fingerprint(command), str(root)])
        record = value['hosts'].get(key)
        now = time.time()
        if force or not record or record['fingerprint'] != fingerprint or not 0 <= now - record['time'] < 86400:
            record = {'status': probe(command, root), 'fingerprint': fingerprint, 'time': now}
            value['hosts'].pop(key, None)
            value['hosts'][key] = record
            value['hosts'] = dict(list(value['hosts'].items())[-16:])
        if str(root) not in value['roots']:
            value['roots'] = [*value['roots'], str(root)][-16:]
        if previous_root is not None and previous_root not in value['roots']:
            value['roots'] = [*value['roots'][-14:], previous_root, str(root)]
            value['roots'] = list(dict.fromkeys(value['roots']))
        _save(path, {**value, 'sha256': _digest(value)})
    return record['status']


def report(root):
    value = read(root)
    record = (value or {}).get('hosts', {}).get(host_key())
    status = record['status'] if record and 0 <= time.time() - record['time'] < 86400 else 'not-tested'
    return {'projectRoot': str(root), 'sandbox': status, 'hostSpecific': True,
            'previousRoots': [p for p in (value or {}).get('roots', []) if p != str(root)],
            'guidance': GUIDANCE}


def resolve(root, value):
    """Translate only a recorded project-root prefix, never an external path or traversal."""
    from pathlib import PurePosixPath, PureWindowsPath
    raw = str(value)
    incoming = PureWindowsPath(raw) if PureWindowsPath(raw).drive else PurePosixPath(raw)
    if '..' in incoming.parts:
        raise ValueError('Parent traversal is not a portable project reference.')
    roots = [str(root), *(read(root) or {}).get('roots', [])]
    if not incoming.is_absolute():
        relative = incoming
    else:
        relative = None
        for name in sorted(roots, key=len, reverse=True):
            old = type(incoming)(name)
            if incoming.is_relative_to(old):
                relative = incoming.relative_to(old)
                break
        if relative is None:
            raise ValueError('This absolute path is not inside a recorded project root; select the external source explicitly.')
    target = checked_path(root.joinpath(*relative.parts))
    if not target.is_relative_to(root) or not target.exists():
        raise ValueError('The corresponding project path is absent or outside the selected project.')
    return target


def prepare(root, command):
    try:
        state = refresh(root, command)
        return GUIDANCE + '\nCurrent host sandbox probe: ' + state + ' (a harmless command, not task/permission verification).'
    except (OSError, ValueError) as exc:
        from .presentation import clean
        return GUIDANCE + '\nHost context unavailable: ' + clean(exc)


def register(commands):
    parser = commands.add_parser('context', help='Inspect this host and resolve project paths after a mount change.')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--refresh', action='store_true', help='Repeat the bounded local sandbox probe; no permission changes.')
    parser.add_argument('--resolve', metavar='PATH', help='Resolve a relative path or a previously recorded project-root prefix.')
    parser.add_argument('--remember-root', metavar='OLD_ROOT', help='Explicitly bind a legacy absolute project prefix to this project.')


def run(args, source_root):
    root = project_root(args.project)
    if args.remember_root is not None:
        from pathlib import PurePosixPath, PureWindowsPath
        old = PureWindowsPath(args.remember_root) if PureWindowsPath(args.remember_root).drive else PurePosixPath(args.remember_root)
        if not old.is_absolute() or len(old.parts) < 3 or '..' in old.parts or '\0' in args.remember_root or len(args.remember_root) > 4096:
            raise ValueError('Select a specific absolute old project root, not a filesystem root or parent traversal.')
    if args.refresh or args.remember_root is not None:
        from .project import _codex_command
        refresh(root, _codex_command('codex'), force=args.refresh, previous_root=args.remember_root)
    result = report(root)
    if args.resolve is not None:
        result['resolvedPath'] = str(resolve(root, args.resolve))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print('Project: ' + result['projectRoot'])
        print('Current host sandbox: ' + result['sandbox'])
        if 'resolvedPath' in result:
            print('Resolved path: ' + result['resolvedPath'])
        print(result['guidance'])
    return 0
