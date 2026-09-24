"""Opt-in structural retrieval; independent of generation and transaction contracts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
from types import SimpleNamespace

from .paths import checked_path
from .locking import FileLock

PACKAGE_VERSION = '0.18.0'
OWNER = 'harness-graft-v1'
SKILL_PATH = '.agents/skills/harness-retrieval/SKILL.md'
SKILL = '''---
name: harness-retrieval
description: Find relevant code with the project's explicitly enabled local Graft index when broad or repeated code navigation would otherwise require many source reads. Use ordinary source reads for small known edits.
---

Use `harness-codex graft query "QUESTION" --project PROJECT_ROOT` only when code
navigation benefits from a structural index. Read the returned relevant source
before editing. Results are navigation hints, not complete dependency or behavior
proof. Do not infer data contracts, test success or permission from a graph.
On disabled, unavailable, incomplete or failed retrieval, continue with normal
search and source reads; do not retry repeatedly or block the user's task.
Do not build on every turn, inject the full graph, add agents, run Graft init,
enable telemetry or call a summarization model. The query refreshes changed
structural inputs on demand. No task requires Graft to be available.
'''


def register(commands):
    parser = commands.add_parser('graft', help='Enable or use optional local structural code retrieval.')
    actions = parser.add_subparsers(dest='graft_action')
    parser.set_defaults(graft_action='status', project=Path.cwd())
    for name in ('enable', 'status', 'query', 'rebuild', 'disable'):
        command = actions.add_parser(name)
        command.add_argument('--project', type=Path, default=Path.cwd())
        command.add_argument('--json', action='store_true', default=False)
        if name in {'enable', 'query', 'rebuild'}:
            command.add_argument('--timeout', type=float, default=120)
        if name == 'enable':
            command.add_argument('--package', type=Path, help='Use this installed package; otherwise prepare an isolated Linux runtime automatically.')
            command.add_argument('--node', default='node')
        if name == 'query':
            command.add_argument('question')
            command.add_argument('--limit', type=int, default=6)
            command.add_argument('--max-chars', type=int, default=12000)


def _save(path, value):
    data = (json.dumps(value, indent=2) + '\n').encode()
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _load(path):
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or value.get('owner') != OWNER
            or type(value.get('enabled')) is not bool or value.get('skillHash') != hashlib.sha256(SKILL.encode()).hexdigest()
            or not all(isinstance(value.get(name), str) and (value[name] or not value['enabled']) for name in ('package', 'node'))
            or any(name in value and type(value[name]) is not bool for name in ('disabledByUser', 'skillOwned'))):
        raise ValueError('Retrieval settings are invalid or unowned; files were preserved.')
    return value


def _settings_lock(folder):
    return FileLock(checked_path(folder.parent / '.locks' / (folder.name + '.lock')), timeout=1)


def _settings_or_new(path):
    settings = _load(path)
    if settings is None:
        if path.parent.exists():
            raise ValueError('Unowned retrieval directory already exists; files were preserved.')
        settings = {'owner': OWNER, 'enabled': False, 'package': '', 'node': '',
                    'skillHash': hashlib.sha256(SKILL.encode()).hexdigest(), 'skillOwned': False,
                    'disabledByUser': False}
    return settings


def _check_skill(skill, settings):
    checked_path(skill)
    if skill.exists() and (not settings.get('skillOwned', True) or skill.read_bytes() != SKILL.encode()):
        raise ValueError('Existing retrieval skill is user-owned or modified; it was preserved.')


def home():
    return checked_path(os.environ.get('HARNESS_GRAFT_HOME', str(Path.home() / '.local/share/harness-codex-retrieval')))


def storage(root):
    # Opt-in and executable provenance belong to the current user, not a cloned
    # project's editable files. Graphs remain disposable and separate from manifests.
    base = home()
    identity = hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest()
    return checked_path(base / identity)


def automatic(root, source_root, *, disabled=False):
    """Init convenience; never scan/rebuild a previously enabled project here."""
    settings = _load(checked_path(storage(root) / 'settings.json'))
    if not disabled and settings:
        if settings.get('disabledByUser', not settings['enabled']):
            return {'state': 'disabled', 'guidance': 'Explicit Graft opt-out preserved.'}
        skill = checked_path(root / SKILL_PATH)
        if settings['enabled'] and settings.get('skillOwned', True) and skill.is_file() and skill.read_bytes() == SKILL.encode():
            return {'state': 'enabled', 'guidance': 'Existing setup reused; retrieval refreshes only when queried.'}
    args = SimpleNamespace(project=root, graft_action='disable' if disabled else 'enable',
                           package=Path(settings['package']) if settings and settings['package'] else None,
                           node=settings['node'] if settings and settings['node'] else 'node', timeout=120, json=False)
    return execute(args, source_root)


def _invoke(source_root, root, cache, settings, action, *, timeout, question='', limit=6, max_chars=12000, advice=False):
    package = Path(settings['package'])
    metadata = json.loads((package / 'package.json').read_text(encoding='utf-8'))
    if not isinstance(metadata, dict) or metadata.get('name') != '@nanonets/graft' or metadata.get('version') != PACKAGE_VERSION:
        raise ValueError(f'This adapter is reviewed for @nanonets/graft {PACKAGE_VERSION}; ordinary code search remains available.')
    # Reject cache links before passing a writable directory to an external library.
    for path in cache.rglob('*') if cache.exists() else ():
        checked_path(path)
    env = os.environ.copy()
    env.update(DO_NOT_TRACK='1', GRAFT_NO_GITIGNORE='1', GRAFT_NO_IGNORE='1', GRAFT_NO_SEED='1', GRAFT_NO_REFRESH='0')
    request = {'package': str(package), 'root': str(root), 'cache': str(cache), 'action': action,
               'question': question, 'limit': limit, 'maxChars': max_chars, 'advice': advice}
    with subprocess.Popen([settings['node'], str(source_root / 'harness_cli/graft_bridge.mjs')],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding='utf-8', env=env, cwd=source_root) as process:
        try:
            stdout, stderr = process.communicate(json.dumps(request), timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            process.kill()
            process.communicate()
            lock = checked_path(cache / '.cache/.sync.lock')
            try:
                if json.loads(lock.read_text())['pid'] == process.pid:
                    lock.unlink()
            except (OSError, ValueError, KeyError):
                pass
            raise
        if process.returncode:
            raise ValueError('Graft retrieval unavailable; use ordinary source search. ' + stderr.strip()[-1500:])
    result = json.loads(stdout)
    if not isinstance(result, dict) or result.get('adapter') != OWNER:
        raise ValueError('Unsupported Graft response; use ordinary source search.')
    return result


def execute(args, source_root):
    root = checked_path(args.project)
    if not root.is_dir() or any(part.casefold() == '.git' for part in root.parts):
        raise ValueError('--project must be an existing project directory outside Git metadata.')
    folder = storage(root)
    state_path = checked_path(folder / 'settings.json')
    cache = checked_path(folder / 'graph')
    skill = checked_path(root / SKILL_PATH)
    settings = _load(state_path)
    action = args.graft_action
    if action == 'status':
        result = {'enabled': bool(settings and settings['enabled']), 'provider': 'graft',
                  'indexed': (cache / 'harness-ready.json').is_file(), 'mode': 'local-structural',
                  'skillInstalled': bool(settings and settings.get('skillOwned', True) and skill.is_file() and skill.read_bytes() == SKILL.encode())}
    elif action == 'disable':
        with _settings_lock(folder):
            settings = _settings_or_new(state_path)
            remove_skill = settings.get('skillOwned', True) and skill.is_file() and skill.read_bytes() == SKILL.encode()
            if settings['enabled'] or not settings.get('disabledByUser'):
                settings['revision'] = uuid.uuid4().hex
            settings['enabled'] = False
            settings['disabledByUser'] = True
            if remove_skill:
                settings['skillOwned'] = False
            _save(state_path, settings)
            if remove_skill:
                skill.unlink()
        result = {'state': 'disabled', 'enabled': False, 'cache': 'preserved', 'projectFiles': 'preserved'}
    else:
        if (not 0 < args.timeout <= 240 or not 1 <= getattr(args, 'limit', 6) <= 20
                or not 512 <= getattr(args, 'max_chars', 12000) <= 64000):
            raise ValueError('Retrieval limits must be timeout 0-240s, results 1-20, characters 512-64000.')
        if action == 'enable':
            with _settings_lock(folder):
                previous = _settings_or_new(state_path)
                _check_skill(skill, previous)
                # Reserve a retryable first setup before slow external work. A
                # newer opt-out changes this receipt and cannot be overwritten.
                _save(state_path, previous)
            if args.package is None:
                from .graft_setup import prepare
                args.node, args.package = prepare(home(), PACKAGE_VERSION)
            node = shutil.which(os.path.expanduser(args.node))
            if node is None:
                raise ValueError('Node.js 20 or newer is required only for optional Graft retrieval.')
            settings = {'owner': OWNER, 'enabled': True, 'package': str(args.package.expanduser().resolve()),
                        'node': node, 'skillHash': hashlib.sha256(SKILL.encode()).hexdigest(), 'disabledByUser': False, 'skillOwned': True}
            if 'revision' in previous:
                settings['revision'] = previous['revision']
        elif not settings or not settings['enabled']:
            raise ValueError('Graft is disabled for this project; continue with ordinary source search.')
        if action == 'query' and (not args.question.strip() or len(args.question) > 8000 or '\0' in args.question):
            raise ValueError('Retrieval question must contain 1-8000 characters without NUL.')
        from . import jev
        advice = action == 'query' and jev.enabled(root)
        result = _invoke(source_root, root, cache, settings, action,
                         timeout=args.timeout, question=getattr(args, 'question', ''),
                         limit=getattr(args, 'limit', 6), max_chars=getattr(args, 'max_chars', 12000), advice=advice)
        candidates = result.pop('candidates', None)
        if advice:
            observation = jev.advise(root, args.question, candidates)
            result['jev'] = observation
            if observation.get('mode') == 'suggest':
                order = ', '.join(str(int(key[1:]) + 1) for key in observation['suggestedOrder'])
                hint = f'[Jev suggested reading order: original hits {order}. Verify source; all hits retained.]\n'
                if len(hint) + len(result['text']) <= args.max_chars:
                    result['text'] = hint + result['text']
        if action == 'enable':
            with _settings_lock(folder):
                current = _load(state_path)
                if current != previous:
                    return {'state': 'superseded', 'enabled': bool(current and current['enabled']),
                            'guidance': 'A newer retrieval preference was preserved; this build did not change it.'}
                _check_skill(skill, current)
                skill.parent.mkdir(parents=True, exist_ok=True)
                if not skill.exists():
                    with skill.open('x', encoding='utf-8', newline='\n') as stream:
                        stream.write(SKILL)
                _save(state_path, settings)
                result.update(state='enabled', enabled=True)
    return result


def run(args, source_root):
    result = execute(args, source_root)
    action = args.graft_action
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif action == 'query':
        print(result['text'])
    else:
        print('Graft: ' + action)
        for key, value in result.items():
            if key != 'adapter':
                print(f'  {key}: {value}')
    return 0
