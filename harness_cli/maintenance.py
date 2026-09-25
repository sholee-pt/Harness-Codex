"""CLI wiring for opt-in maintenance; never changes native hook trust."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from .environment import helper_environment
from .paths import checked_path
from . import presentation as ui

EVENTS = ('SessionStart', 'UserPromptSubmit', 'Stop', 'Interrupt', 'SessionEnd', 'SubagentStart', 'SubagentStop')


def register(commands):
    parser = commands.add_parser('maintenance', help='Configure bounded project maintenance or inspect its status.')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--mode', choices=('off', 'suggest', 'auto'))
    parser.add_argument('--install-hooks', action='store_true', help='Merge the maintenance handler into user hooks; native trust review remains required.')
    parser.add_argument('--json', action='store_true', default=False)
    parser.add_argument('--hook', action='store_true', help=__import__('argparse').SUPPRESS)
    actions = parser.add_subparsers(dest='maintenance_action', metavar='ACTION')
    clear = actions.add_parser('clear', help='Disable maintenance and reset this project\'s local observations; project files are retained.')
    clear.add_argument('--yes', action='store_true', required=True)
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
                            timeout=190 if arguments[0] == 'finish' else 10)
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


def install_hooks(source_root, *, codex_home=None, tool_home=None):
    home = checked_path(codex_home or Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    path = checked_path(home / 'hooks.json')
    receipt = checked_path(home / 'harness-maintenance-hooks.json')
    entry = checked_path(Path(tool_home or os.environ['HARNESS_TOOL_HOME']) / 'launcher.py') if (tool_home or os.environ.get('HARNESS_TOOL_HOME')) else checked_path(Path(source_root) / 'harness.py')
    arguments = [sys.executable, '-B', str(entry), '--no-update-check', 'maintenance', '--hook']
    command = subprocess.list2cmdline(arguments) if os.name == 'nt' else shlex.join(arguments)
    original = _hook_snapshot(path)
    original_receipt = _hook_snapshot(receipt)
    value = json.loads(original.decode('utf-8-sig')) if original is not None else {}
    if not isinstance(value, dict) or not isinstance(value.get('hooks', {}), dict):
        raise ValueError('Existing hooks are malformed; no settings were overwritten')
    previous = None
    if original_receipt is not None:
        saved = json.loads(original_receipt)
        if (not isinstance(saved, dict) or set(saved) != {'owner', 'command'}
                or saved['owner'] != 'harness-maintenance-v1' or not isinstance(saved['command'], str)):
            raise ValueError('Maintenance hook ownership receipt is invalid')
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
            handler = {'type': 'command', 'command': command, 'timeout': 3 if event in {'SessionEnd', 'Interrupt'} else 10}
            if event == 'UserPromptSubmit':
                handler['additionalContextLimit'] = 1024
            groups.append({'hooks': [handler]})
    changed = before != json.dumps(value, sort_keys=True)
    # Reuse the same bounded atomic writer as distribution receipts.
    from .distribution import _write_json
    home.mkdir(parents=True, exist_ok=True)
    saved = {'owner': 'harness-maintenance-v1', 'command': command}
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
        installer.install(checked_path(root), source=Path(source_root) / '.agents/skills/harness')
    report = helper(source_root, root, ['configure', '--mode', mode])
    if mode != 'off':
        hooks = install_hooks(source_root)
        if hooks['changed'] and not quiet:
            print('Maintenance hook installed. In Codex, use /hooks to review and trust it; no trust setting was changed.')
    if not quiet:
        print(f'Project maintenance: {mode}. Ordinary turns do not launch a separate review model.')
    return report


def remove_hooks(data_root, *, codex_home=None, dry_run=True):
    """Remove only this installation's exact registered handler, preserving others."""
    home = checked_path(codex_home or Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    receipt = checked_path(home / 'harness-maintenance-hooks.json')
    path = checked_path(home / 'hooks.json')
    if not receipt.is_file():
        return {'state': 'absent'}
    from .distribution import _write_json, installed_status
    original_receipt = _hook_snapshot(receipt)
    if original_receipt is None:
        return {'state': 'absent'}
    original = _hook_snapshot(path)
    saved = json.loads(original_receipt)
    if (not isinstance(saved, dict) or set(saved) != {'owner', 'command'}
            or saved['owner'] != 'harness-maintenance-v1' or not isinstance(saved['command'], str)):
        raise ValueError('Maintenance hook ownership receipt is invalid; preserve it')
    state = installed_status(data_root)
    arguments = [state['python'], '-B', str(checked_path(Path(data_root) / 'launcher.py')), '--no-update-check', 'maintenance', '--hook']
    expected = subprocess.list2cmdline(arguments) if os.name == 'nt' else shlex.join(arguments)
    if saved['command'] != expected:
        return {'state': 'another-installation; preserved'}
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
    if not dry_run:
        if _hook_snapshot(receipt) != original_receipt:
            raise ValueError('Hook ownership changed during removal; concurrent edits preserved')
        if removed:
            _write_json(path, value, expected=original)
        elif _hook_snapshot(path) != original:
            raise ValueError('Hook settings changed during removal; concurrent edits preserved')
        if _hook_snapshot(receipt) != original_receipt:
            raise ValueError('Hook ownership changed during removal; concurrent edits preserved')
        receipt.unlink()
    return {'state': 'remove', 'handlers': removed}


def run(args, source_root):
    if args.hook:
        return helper(source_root, args.project, ['hook'], capture=False)
    if args.maintenance_action:
        if args.mode is not None or args.install_hooks:
            raise ValueError('Choose a maintenance action or settings change, not both')
        arguments = [args.maintenance_action]
        if args.maintenance_action == 'clear':
            arguments += ['--yes']
        elif args.maintenance_action == 'signal':
            arguments += ['--reason', args.reason, '--evidence', args.evidence, '--observation', args.observation]
        elif args.maintenance_action == 'finish':
            arguments += ['--lease', args.lease, '--decision', args.decision]
            if args.plan is not None:
                arguments += ['--plan', str(args.plan)]
            if args.reported_tokens is not None:
                arguments += ['--reported-tokens', str(args.reported_tokens)]
        result = helper(source_root, args.project, arguments)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print('Maintenance: ' + str(result.get('status', 'signal recorded' if result.get('recorded') else result.get('reason', 'unchanged'))))
            if result.get('id'):
                print('Review lease: ' + result['id'])
        return 0
    if args.mode is not None:
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
    return 0
