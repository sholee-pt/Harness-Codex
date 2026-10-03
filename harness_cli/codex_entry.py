"""Prelaunch release choices, followed by the unchanged official Codex terminal."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from . import distribution as dist, official_codex, release_updates
from .presentation import Progress, clean
from .terminal_menu import choose


def interactive(args):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    # Help, automation, login and explicit remote connections remain native/offline.
    from .auto_relay import native_arguments
    first = True
    for option, value in native_arguments(args):
        if option in {'--help', '-h', '--version', '-V', '--remote'}:
            return False
        if option is None and first:
            if value in {'exec', 'e', 'review', 'login', 'logout', 'mcp', 'mcp-server', 'app-server', 'completion',
                         'sandbox', 'debug', 'apply', 'cloud', 'features', 'update', 'agents', 'queue', 'archive',
                         'delete', 'unarchive', 'exec-server', 'help'}:
                return False
            first = False
    return True


def update_choices(root):
    state = dist.installed_status(root)
    if state['auto_update'] == 'off' or os.environ.get('HARNESS_NO_UPDATE_CHECK') == '1':
        return False
    findings = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        channels = [('Codex', official_codex.check)]
        if not state.get('branch'):
            channels.append(('Harness', release_updates.check))
        pending = {name: executor.submit(check, root, timeout=5) for name, check in channels}
        for name, future in pending.items():
            try:
                value = future.result()
                if value['updateAvailable']:
                    findings[name] = value
            except (OSError, ValueError, TimeoutError):
                print(name + ' update check unavailable; continuing with installed files.', file=sys.stderr)
    if not findings:
        return False
    progress = Progress('Updates available')
    for name, result in findings.items():
        progress.line(f"{name}: {result['currentVersion']} -> {result['availableVersion']}")
    options = [('Skip this time', ())]
    if len(findings) == 2:
        options.append(('Update both', ('Harness', 'Codex')))
    options.extend(('Update ' + name + ' only', (name,)) for name in findings)
    selected = options[choose(progress, 'Update before starting Codex?', [item[0] for item in options])][1]
    changed = False
    for name in selected:
        try:
            with Progress('Updating ' + name) as progress:
                if name == 'Codex':
                    official_codex.install(root, selected=findings[name],
                        native_fallback=lambda version, error: choose_native_install(version, error, progress=progress))
                else:
                    result = release_updates.update(root, selected=findings[name])
                    changed = result['updated']
        except (OSError, ValueError, TimeoutError, subprocess.SubprocessError) as error:
            print(name + ' update was not applied: ' + clean(error), file=sys.stderr)
    return changed


def choose_native_install(version, error, *, progress=None):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    progress = progress or Progress('Official Codex is available without the Harness adapter')
    progress.line('Auto compatibility check failed: ' + clean(error))
    progress.line('Native mode preserves Codex permissions and history. Harness Auto and /harness/ controls remain disabled until codex update --auto succeeds.')
    return choose(progress, 'Install official Codex ' + version + ' in native mode?', [
        'Keep the current installation', 'Install this version in native mode']) == 1


def sessions(root):
    path = dist._storage_path(root / 'relay-sessions.json')
    if not path.exists():
        return {}
    value = dist._read_json(path)
    if (set(value) != {'schema', 'threads'} or value['schema'] != 1 or not isinstance(value['threads'], dict)
            or len(value['threads']) > 512 or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', key)
                or type(mode) is not bool for key, mode in value['threads'].items())):
        raise ValueError('Invalid Auto session preferences; preserve and review relay-sessions.json')
    return value['threads']


def remember(root, thread, enabled):
    if not isinstance(thread, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', thread):
        return
    with dist._lock(root):
        modes = sessions(root)
        if modes.get(thread) is enabled:
            return
        modes.pop(thread, None)
        if len(modes) >= 512:
            modes.pop(next(iter(modes)))
        modes[thread] = enabled
        dist._write_json(root / 'relay-sessions.json', {'schema': 1, 'threads': modes})


def compatible(binary, args):
    """Probe available operations, not a numeric Codex version allowlist."""
    from .auto_relay import dependency, server_arguments, working_directory, Policy
    from .configuration import Server
    dependency()
    result = subprocess.run([str(binary), '--help'], capture_output=True, text=True, timeout=10, check=True)
    if '--remote' not in result.stdout or '--remote-auth-token-env' not in result.stdout:
        raise ValueError('This Codex does not advertise an authenticated remote app-server connection')
    server = Server([str(binary), *server_arguments(args)], working_directory(args), Progress('Checking Auto compatibility', compact=True))
    try:
        server.initialize(timeout=10)
        from .session_settings import model_catalog
        policy = Policy()
        policy.model_list({'data': model_catalog(server, time.monotonic() + 10), 'nextCursor': None})
        if not policy.catalog:
            raise ValueError('No visible Codex models are available')
    finally:
        server.close()


def main(args):
    from .main import default_data_root
    from . import codex_integration
    from .environment import codex_environment
    from .auto_relay import Policy, run, profile_requested, native_arguments
    root = default_data_root()
    integration = codex_integration.read(root)
    if not integration or integration['schema'] != 2:
        raise ValueError('Run harness-codex config to register the official Codex entry point')
    if args in (['update'], ['update', '--auto']):
        with Progress('Updating official Codex') as progress:
            official_codex.install(root, prefer_auto='--auto' in args,
                native_fallback=lambda version, error: choose_native_install(version, error, progress=progress))
        return 0
    if interactive(args) and update_choices(root):
        # Load new Python source only between conversations, once per launch.
        state = dist.installed_status(root)
        env = {**os.environ, 'HARNESS_NO_UPDATE_CHECK': '1'}
        os.execve(state['python'], [state['python'], '-B', str(root / 'launcher.py'), '_codex', *args], env)
    binary = official_codex.binary(root)
    env = codex_environment()
    if interactive(args):
        from .auto_relay import working_directory
        from .workspace_context import PATH as context_path, prepare
        location = Path(working_directory(args)).resolve()
        for project in (location, *location.parents):
            if (project / context_path).is_file():
                prepare(project, [str(binary)])
                break
    if not interactive(args) or os.environ.get('HARNESS_CODEX_NATIVE') == '1':
        os.execve(str(binary), [str(binary), *args], env)
    if profile_requested(args):
        print('Using native Codex to preserve the selected profile. Harness Auto is unavailable for this launch.', file=sys.stderr)
        os.execve(str(binary), [str(binary), *args], env)
    if (official_codex.read(root) or {}).get('mode') == 'native':
        print('Using the selected native Codex mode. Run codex update --auto to check and re-enable the Harness adapter.', file=sys.stderr)
        os.execve(str(binary), [str(binary), *args], env)
    # Harness owns this package's update transaction; avoid a second native prompt.
    args = ['-c', 'check_for_update_on_startup=false', *args]
    try:
        compatible(binary, args)
    except (OSError, ValueError, ImportError, TimeoutError, subprocess.SubprocessError) as error:
        progress = Progress('Auto unavailable')
        progress.line('Auto compatibility check failed: ' + clean(error))
        if choose(progress, 'Continue with official Codex?', ['Use native Codex without Harness Auto', 'Exit']) == 1:
            return 1
        os.execve(str(binary), [str(binary), *args], env)
    settings = dist._read_json(root / 'codex-relay.json')
    profiles = None
    if settings.get('profiles'):
        from .routing import read_json
        profiles = read_json(dist._storage_path(settings['profiles']))
    modes = sessions(root)
    explicit_model = any(option in {'-m', '--model'} for option, _ in native_arguments(args))
    from .routing_feedback import Observer
    from .auto_relay import working_directory
    observer = Observer(Path(__file__).resolve().parents[1], working_directory(args), (official_codex.read(root) or {}).get('version'))
    policy = Policy(mode='manual' if explicit_model else settings['mode'], profiles=profiles, session_modes={} if explicit_model else modes,
                    remember=lambda thread, enabled: remember(root, thread, enabled), observer=observer)
    return asyncio.run(run(binary, args, env, policy))
