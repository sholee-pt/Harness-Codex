"""CLI wiring for opt-in maintenance; init separately prepares owned hook trust."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from .environment import helper_environment
from .paths import checked_path, storage_location, user_home
from . import presentation as ui

EVENTS = ('SessionStart', 'UserPromptSubmit', 'Stop', 'Interrupt', 'SessionEnd', 'SubagentStart', 'SubagentStop')


def register(commands):
    parser = commands.add_parser('maintenance', help='Configure bounded project maintenance or inspect its status.')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--mode', choices=('off', 'suggest', 'auto'))
    parser.add_argument('--schedule', choices=('adaptive', 'fixed'), help='Advanced review interval policy; new policies default to adaptive. Omit to preserve the current setting.')
    parser.add_argument('--max-reviews-per-day', type=int)
    parser.add_argument('--min-interval-seconds', type=int)
    parser.add_argument('--max-interval-seconds', type=int)
    parser.add_argument('--max-review-seconds', type=int)
    parser.add_argument('--reported-token-budget', type=int, help='Pause after unmeasured reviews or reported daily spend; 0 clears this optional limit.')
    parser.add_argument('--install-hooks', action='store_true', help='Merge the maintenance handler into user hooks; native trust review remains required.')
    parser.add_argument('--json', action='store_true', default=False)
    parser.add_argument('--hook', action='store_true', help=__import__('argparse').SUPPRESS)
    actions = parser.add_subparsers(dest='maintenance_action', metavar='ACTION')
    observe = actions.add_parser('observe', help='Record a related outcome without claiming measured benefit.')
    for name in ('change', 'observation', 'revision', 'outcome', 'source'):
        observe.add_argument('--' + name, required=True)
    for name in ('model', 'effort', 'category', 'runtime'):
        observe.add_argument('--' + name)
    resolve = actions.add_parser('resolve', help='Review a change or roll back with a verified prior skill plan.')
    resolve.add_argument('--change', required=True)
    resolve.add_argument('--decision', choices=('keep', 'rollback'), required=True)
    resolve.add_argument('--plan', type=Path)
    clear = actions.add_parser('clear', help='Disable maintenance and reset this project\'s local observations; project files are retained.')
    clear.add_argument('--yes', action='store_true')
    recover = actions.add_parser('recover-session', help='Release a stale activity marker after confirming the native session and its children stopped.')
    recover.add_argument('--session-ref', required=True, help='Opaque ref from maintenance status; all requires confirming every project session and child stopped.')
    recover.add_argument('--yes', action='store_true')
    signal = actions.add_parser('signal', help='Record a specifically identified recurring concern without launching a review.')
    signal.add_argument('--reason', choices=('scope-changed', 'workflow-gap', 'routing-mismatch', 'verification-gap', 'user-request'), required=True)
    signal.add_argument('--evidence', required=True)
    signal.add_argument('--observation', required=True)
    actions.add_parser('begin', help='Reserve one eligible bounded review batch.')
    finish = actions.add_parser('finish', help='Finish a reserved review; automatic apply enforces its existing-skill scope.')
    finish.add_argument('--lease', required=True)
    finish.add_argument('--decision', choices=('unchanged', 'proposed', 'deferred', 'apply'), required=True)
    finish.add_argument('--plan', type=Path)
    finish.add_argument('--reported-tokens', type=int)


def helper(source_root, root, arguments, *, capture=True):
    script = Path(source_root) / '.agents/skills/harness/scripts/harness_maintenance.py'
    result = subprocess.run([sys.executable, '-B', str(script), '--root', str(root), *arguments],
                            env=helper_environment(), capture_output=capture, text=True,
                            timeout=190 if arguments[0] in {'finish', 'resolve'} else 10)
    if not capture:
        return result.returncode
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'Maintenance helper failed')
    return json.loads(result.stdout)


def _hook_snapshot(path):
    checked_path(path)
    if not path.exists():
        return None
    with path.open('rb') as stream:
        content = stream.read(256 * 1024 + 1)
    if len(content) > 256 * 1024:
        raise ValueError('Existing hook configuration is too large; preserve it for manual review')
    return content


def hook_definition(event, command):
    handler = {'type': 'command', 'command': command, 'timeout': 3 if event in {'SessionEnd', 'Interrupt'} else 10}
    if event == 'UserPromptSubmit':
        handler['additionalContextLimit'] = 1024
    return handler


def hook_command(source_root, tool_home=None):
    entry = checked_path(Path(tool_home or os.environ['HARNESS_TOOL_HOME']) / 'launcher.py') if (tool_home or os.environ.get('HARNESS_TOOL_HOME')) else checked_path(Path(source_root) / 'harness.py')
    # Match the install receipt, which resolves Conda's bin/python symlink.
    arguments = [str(Path(sys.executable).resolve()), '-B', str(entry), '--no-update-check', 'maintenance', '--hook']
    return _hook_command(arguments, portable=bool(tool_home or os.environ.get('HARNESS_TOOL_HOME')))


def _hook_command(arguments, *, portable):
    if os.name == 'nt':
        return subprocess.list2cmdline(arguments)
    if not portable:
        return shlex.join(arguments)
    from .installation_paths import home_expression
    home = user_home()
    command = 'exec ' + home_expression(arguments[0], home) + ' -B ' + home_expression(arguments[2], home)
    return shlex.join(['/bin/sh', '-c', command + ' ' + shlex.join(arguments[3:])])


def probe_hook(command, root):
    """Exercise the real entrypoint with a no-write payload before native trust."""
    import signal
    import tempfile
    # File-backed output stays bounded in memory even if an entrypoint is broken.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command if os.name == 'nt' else ['/bin/sh', '-c', command], cwd=root,
                                   stdin=subprocess.PIPE, stdout=output, stderr=errors, start_new_session=os.name != 'nt')
        try:
            process.communicate(b'{"hook_event_name":"HarnessProbe"}', timeout=3)
        except BaseException:
            if os.name == 'nt':
                try:
                    subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32/taskkill.exe'), '/PID', str(process.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
                except (OSError, subprocess.SubprocessError):
                    pass
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            process.wait()
            raise
        output.seek(0)
        data = output.read(1025)
        if process.returncode or len(data) > 1024:
            raise ValueError('Harness hook entrypoint failed its execution check; rerun the current installer on this server')
        try:
            valid = json.loads(data) == {'harnessHookProbe': 1}
        except (ValueError, UnicodeError):
            valid = False
        if not valid:
            raise ValueError('Harness hook execution check returned an unsupported response; update the managed tool before trusting hooks')


def _legacy_posix_hook(command, arguments):
    try:
        parsed = shlex.split(command)
        if not parsed or parsed[1:] != arguments[1:] or shlex.join(parsed) != command:
            return False
        executable = Path(parsed[0])
        return executable.is_absolute() and executable.is_file() and str(executable.resolve()) == arguments[0]
    except (OSError, ValueError, RuntimeError):
        return False


def install_hooks(source_root, *, codex_home=None, tool_home=None):
    home = storage_location(codex_home or Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    path = checked_path(home / 'hooks.json')
    receipt = checked_path(home / 'harness-maintenance-hooks.json')
    command = hook_command(source_root, tool_home)
    original = _hook_snapshot(path)
    original_receipt = _hook_snapshot(receipt)
    value = json.loads(original.decode('utf-8-sig')) if original is not None else {}
    if not isinstance(value, dict) or not isinstance(value.get('hooks', {}), dict):
        raise ValueError('Existing hooks are malformed; no settings were overwritten')
    previous = None
    if original_receipt is not None:
        from .hook_state import receipt as read_receipt
        saved = read_receipt(original_receipt)
        previous = saved['command']
    before = json.dumps(value, sort_keys=True)
    hooks = value.setdefault('hooks', {})
    for event in EVENTS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list) or any(not isinstance(group, dict) or not isinstance(group.get('hooks'), list) for group in groups):
            raise ValueError('Existing hook event configuration is malformed')
        found = False
        for group in groups:
            for handler in group['hooks']:
                if isinstance(handler, dict) and handler.get('command') and handler.get('command') in {command, previous} and handler.get('type') == 'command':
                    handler['command'] = command
                    found = True
        if not found:
            groups.append({'hooks': [hook_definition(event, command)]})
    changed = before != json.dumps(value, sort_keys=True)
    # Reuse the same bounded atomic writer as distribution receipts.
    from .distribution import _write_json
    home.mkdir(parents=True, exist_ok=True)
    trust = saved.get('trust') if original_receipt is not None else None
    saved = {'owner': 'harness-maintenance-v1', 'command': command}
    if trust is not None:
        saved['trust'] = trust
    receipt_changed = original_receipt is None or json.loads(original_receipt) != saved
    changes = ([(path, value, original)] if changed else []) + ([(receipt, saved, original_receipt)] if receipt_changed else [])
    try:
        if _hook_snapshot(receipt) != original_receipt:
            raise ValueError('Hook ownership changed during installation; concurrent edits preserved')
        if _hook_snapshot(path) != original:
            raise ValueError('Hook settings changed during installation; concurrent edits preserved')
        # Publish handlers before replacing their receipt. If the process dies,
        # retry can recognize the exact new command while retaining old ownership.
        for target, content, before_bytes in changes:
            _write_json(target, content, expected=before_bytes)
    except BaseException:
        for target, content, before_bytes in reversed(changes):
            written = (json.dumps(content, indent=2, sort_keys=True) + '\n').encode('utf-8')
            if _hook_snapshot(target) == written:
                if before_bytes is None:
                    target.unlink()
                else:
                    from .shell import _replace_profile
                    _replace_profile(target, written, before_bytes)
        raise
    return {'changed': changed, 'trust': 'native-review-required', 'path': str(path)}


def enable(source_root, root, mode, *, quiet=False):
    if mode != 'off':
        from .project_installer import load_installer
        installer = load_installer(source_root)
        installer.install(root, source=Path(source_root) / '.agents/skills/harness')
    report = helper(source_root, root, ['configure', '--mode', mode])
    if mode != 'off':
        hooks = install_hooks(source_root)
        if hooks['changed'] and not quiet:
            print('Maintenance hook installed. In Codex, use /hooks to review and trust it; no trust setting was changed.')
    if not quiet:
        print(f'Project maintenance: {mode}. Ordinary turns do not launch a separate review model.')
    return report


def removal_plan(data_root, *, codex_home=None, installed=None):
    """Snapshot only owned hook changes for the tool uninstall transaction."""
    home = storage_location(codex_home or Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    receipt = checked_path(home / 'harness-maintenance-hooks.json')
    path = checked_path(home / 'hooks.json')
    if not receipt.is_file():
        return {'state': 'absent'}
    from .distribution import installed_status
    from .hook_state import encoded, receipt as read_receipt, restore_trust
    original_receipt = _hook_snapshot(receipt)
    if original_receipt is None:
        return {'state': 'absent'}
    original = _hook_snapshot(path)
    saved = read_receipt(original_receipt)
    state = installed if installed is not None else installed_status(data_root)
    arguments = [str(Path(state['python']).resolve()), '-B', str(checked_path(Path(data_root) / 'launcher.py')), '--no-update-check', 'maintenance', '--hook']
    expected = subprocess.list2cmdline(arguments) if os.name == 'nt' else shlex.join(arguments)
    portable = _hook_command(arguments, portable=True)
    if saved['command'] == portable:
        expected = portable
    elif saved['command'] != expected:
        from .installation_paths import binding
        legacy = list(arguments)
        if (Path(data_root) / 'active.json').is_file():
            bound = binding(data_root)
            legacy[0], legacy[2] = bound.path(arguments[0], reverse=True), bound.path(arguments[2], reverse=True)
        if os.name == 'nt' or (saved['command'] != shlex.join(legacy) and not _legacy_posix_hook(saved['command'], arguments)):
            return {'state': 'another-installation; preserved'}
        expected = saved['command']
    value = json.loads(original.decode('utf-8-sig')) if original is not None else {}
    if not isinstance(value, dict) or not isinstance(value.get('hooks', {}), dict):
        raise ValueError('Existing hooks are malformed; preserve them')
    removed = 0
    for event, groups in value.get('hooks', {}).items():
        if not isinstance(groups, list):
            raise ValueError('Existing hook groups are malformed')
        for group in list(groups):
            if not isinstance(group, dict) or not isinstance(group.get('hooks'), list):
                raise ValueError('Existing hook handlers are malformed')
            before = group['hooks']
            group['hooks'] = [handler for handler in before if not
                              (isinstance(handler, dict) and handler.get('type') == 'command' and handler.get('command') == expected)]
            removed += len(before) - len(group['hooks'])
            if before and not group['hooks']:
                groups.remove(group)
    changes = [(path, original, encoded(value) if removed else original)]
    warnings = []
    if saved.get('trust'):
        config = checked_path(home / 'config.toml')
        before = _hook_snapshot(config)
        after, warnings = restore_trust(before, saved['trust'])
        changes.append((config, before, after))
    else:
        warnings.append('No recorded automatic trust changes; existing native trust settings are preserved.')
    changes.append((receipt, original_receipt, None))
    return {'state': 'remove', 'handlers': removed, 'changes': changes, 'warnings': warnings}


def remove_hooks(data_root, *, codex_home=None, dry_run=True):
    """Standalone hook removal uses the same reversible edits as tool uninstall."""
    plan = removal_plan(data_root, codex_home=codex_home)
    if not dry_run and plan['state'] == 'remove':
        from .hook_state import apply_changes, rollback_changes
        written = []
        try:
            apply_changes(plan['changes'], written)
        except BaseException:
            import tempfile
            backup = Path(tempfile.mkdtemp(prefix='harness-hook-recovery-'))
            failures = rollback_changes(written, backup)
            if failures:
                raise ValueError('Hook rollback needs manual recovery: ' + ', '.join(failures))
            backup.rmdir()
            raise
    return {key: value for key, value in plan.items() if key != 'changes'}


def run(args, source_root):
    if args.hook:
        return helper(source_root, args.project, ['hook'], capture=False)
    fields = {'schedule': 'schedule', 'max_reviews_per_day': 'reviewsPerDay', 'min_interval_seconds': 'minIntervalSeconds',
              'max_interval_seconds': 'maxIntervalSeconds', 'max_review_seconds': 'reviewSeconds', 'reported_token_budget': 'reportedTokensPerDay'}
    policy = {target: getattr(args, name) for name, target in fields.items() if getattr(args, name, None) is not None}
    if policy.get('reportedTokensPerDay') == 0:
        policy['reportedTokensPerDay'] = None
    if args.maintenance_action:
        if args.mode is not None or args.install_hooks or policy:
            raise ValueError('Choose a maintenance action or settings change, not both')
        arguments = [args.maintenance_action]
        if args.maintenance_action in {'clear', 'recover-session'}:
            question = ('Disable maintenance and clear local observations for this project?' if args.maintenance_action == 'clear' else
                        'Have ALL native sessions and child agents for this project stopped? Reset their tracking only?' if args.session_ref == 'all' else
                        'Have this session and all its child agents stopped? Release its activity marker?')
            if not args.yes:
                if args.json or not sys.stdin.isatty() or not sys.stdout.isatty():
                    raise ValueError('Use --yes after reviewing the selected maintenance action')
                if not ui.confirm(question):
                    print('Maintenance action cancelled. Nothing was changed.')
                    return 0
            arguments += ['--yes']
            if args.maintenance_action == 'recover-session':
                arguments += ['--session-ref', args.session_ref]
        elif args.maintenance_action == 'signal':
            arguments += ['--reason', args.reason, '--evidence', args.evidence, '--observation', args.observation]
        elif args.maintenance_action == 'finish':
            arguments += ['--lease', args.lease, '--decision', args.decision]
            if args.plan is not None:
                arguments += ['--plan', str(args.plan)]
            if args.reported_tokens is not None:
                arguments += ['--reported-tokens', str(args.reported_tokens)]
        elif args.maintenance_action in {'observe', 'resolve'}:
            names = ('change', 'decision', 'plan') if args.maintenance_action == 'resolve' else (
                'change', 'observation', 'revision', 'outcome', 'source', 'model', 'effort', 'category', 'runtime')
            for name in names:
                value = getattr(args, name, None)
                if value is not None:
                    arguments += ['--' + name, str(value)]
        result = helper(source_root, args.project, arguments)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print('Maintenance: ' + str(result.get('status', 'signal recorded' if result.get('recorded') else result.get('reason', 'unchanged'))))
            if result.get('id'):
                print('Review lease: ' + result['id'])
            if result.get('changeId'):
                print('Change: ' + result['changeId'] + ' | Instructions updated; effect under observation.')
        return 0
    if policy:
        arguments = ['configure', '--policy-json', json.dumps(policy)]
        if args.mode is not None:
            arguments += ['--mode', args.mode]
        result = helper(source_root, args.project, arguments)
        if args.mode is not None and args.mode != 'off':
            result = enable(source_root, args.project, args.mode, quiet=args.json)
    elif args.mode is not None:
        result = enable(source_root, args.project, args.mode, quiet=args.json)
    else:
        result = helper(source_root, args.project, ['status'])
    if args.install_hooks and args.mode is None:
        result['hooks'] = install_hooks(source_root)
    if args.json:
        ui.report(result, title='Project maintenance')
    else:
        print(f'Maintenance: {result["mode"]}; eligible concerns: {result["pending"]}; reviews: {result["metrics"]["reviews"]}.')
        print('Automatic changes: existing skills only. Quality benefit is unmeasured; token counts are not a billing total.')
        print('Automatic changes paused: ' + ('yes' if result.get('automaticChangesPaused') else 'no'))
        if result.get('trackingIncomplete'):
            print('Session tracking reached capacity. After confirming every native session and child for this project stopped, use maintenance recover-session --session-ref all. Observations and project files are retained.')
        for session in result.get('blockingSessions', []):
            print(f"  Active session marker: {session['ref']} | active: {session['active']} | children: {session['children']}")
        if result.get('blockingSessions'):
            print('If a marked session and all its children have stopped, use maintenance --project PATH recover-session --session-ref REF.')
        if result.get('scheduling'):
            timing = result['scheduling']
            print(f"Schedule: {timing['schedule']}; current interval: {timing['intervalSeconds']}s; application window: {timing['applicationSeconds']}s.")
        for change in result.get('changes', []):
            print(f"  {change['id']}: {change['status']} | observations: {change['observations']} | effect: not established")
    return 0
