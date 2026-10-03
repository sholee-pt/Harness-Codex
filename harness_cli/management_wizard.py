"""Explicit project selection and briefs through native, local question controls."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .paths import project_root, project_target
from . import presentation as ui


def goal_arguments(root, arguments):
    from .main import build_parser
    from .project import _goal_input, load_installer
    source = Path(__file__).resolve().parents[1]
    options = [arguments[0] + '=' + arguments[1]] if arguments else []
    args = build_parser(source).parse_args(['init', '--project', str(root), *options])
    if args.goal_file is not None:
        args.goal_file = root / args.goal_file.expanduser()
    goal = _goal_input(args, load_installer(source))
    return goal, (['--goal-file', str(args.goal_file)] if args.goal_file is not None else arguments)


def context(controls, root):
    return 'Project: ' + ui.clean(root) + '\n' + controls.queued_action()


async def retained_input(controls, thread, turn, question, previous=None):
    if previous is not None:
        choice = await controls.choose(thread, turn, question + '\nEntered: ' + ui.clean(previous),
            [('Keep entered value', 'Continue with the displayed value'), ('Edit value', 'Enter a replacement'), ('Back', 'Return to the previous step')])
        if choice == 'Back':
            return None
        if choice == 'Keep entered value':
            return previous
    value = await controls.enter(thread, turn, question + '. Enter :back to go back.')
    return None if value == ':back' else value


async def menu(controls, thread, turn, root):
    groups = {
        'Project': [('Init', 'Choose a project and purpose'), ('Config', 'Review existing generated artifacts'),
                    ('Switch', 'Open another project after exit'), ('Remove', 'Preview owned file removal'), ('Reset', 'Remove before a new design')],
        'Settings': [('Preferences', 'Current maintenance, adaptive Auto and hook trust'), ('Jev', 'Advice settings and private login'), ('Graft', 'Local code retrieval and selected external sources')],
        'Diagnostics': [('Status', 'Project and integration readiness'), ('Doctor', 'Validate project files'),
                        ('Maintenance', 'Observations and an explicit review'), ('Routing', 'Recorded adaptive Auto evidence')],
    }
    group = None
    while True:
        if group is None:
            group = await controls.choose(thread, turn, context(controls, root) + '\nHarness management. Selection and local queries do not call a model.',
                [('Project', 'Init, config, switch, remove and reset'), ('Settings', 'Preferences, Jev and Graft'),
                 ('Diagnostics', 'Status, doctor, maintenance and routing'), ('Tools', 'Updates, uninstall and queued action'),
                 ('Help', 'Qualified command names'), ('Back', 'Return to the conversation')])
            if group == 'Back':
                return 'Returned to the conversation.\n' + controls.queued_action()
            if group == 'Help':
                from .management_relay import COMMANDS
                return '\n'.join('/harness/' + name for name in COMMANDS) + '\nUse init/config --goal "DESCRIPTION" or --goal-file "PATH".\nMaintenance review uses the current model; status commands are local.\nSettings change preferences; config reviews generated artifacts.'
        if group == 'Tools':
            result = await tools(controls, thread, turn, root, 'tool')
            if result is not None:
                return result
            group = None
            continue
        choice = await controls.choose(thread, turn, context(controls, root) + '\n' + group,
            groups[group] + [('Back', 'Return to management groups')])
        if choice == 'Back':
            group = None
            continue
        if choice in {'Jev', 'Graft'}:
            result = await tools(controls, thread, turn, root, choice.lower())
        elif choice == 'Maintenance':
            result = await maintenance(controls, thread, turn, root)
        else:
            result = await controls.execute(thread, turn, root, 'settings' if choice == 'Preferences' else choice.lower(), [], from_menu=True)
        if result is not None:
            return result


async def settings(controls, thread, turn, root):
    report = json.loads(await controls.cli(root, ['settings', '--json']))
    features = report.get('features', {})
    maintenance_state = features.get('maintenance', {}).get('mode', 'unavailable')
    adaptive = features.get('routing', {}).get('enabled')
    values = {'Maintenance': maintenance_state, 'Adaptive Auto': 'on' if adaptive is True else 'off' if adaptive is False else 'unavailable'}
    hooks = features.get('hooks', {})
    summary = (context(controls, root) + '\nMaintenance: ' + str(values['Maintenance']) + '\nAdaptive Auto: ' + values['Adaptive Auto'] +
               '\nHook registration: ' + str(hooks.get('state', 'unavailable')) + '; recorded trust matches: ' + str(hooks.get('recordedTrustMatches', 'unknown')))
    while True:
        selected = await controls.choose(thread, turn, summary,
            [('Keep current', 'Close without changing preferences'), ('Maintenance', 'Off, suggest, or bounded automatic changes'),
             ('Adaptive Auto', 'Use recorded quality/cost observations'), ('Hook trust', 'Prepare exact Harness hooks through native policy'), ('Back', 'Return to the parent menu')])
        if selected == 'Back':
            return None
        if selected == 'Keep current':
            return 'Current preferences retained.\n' + summary
        if selected == 'Hook trust':
            choice = await controls.choose(thread, turn, summary + '\nPrepare native trust for only the exact Harness hook definitions?',
                [('Keep current', 'Leave hook trust unchanged'), ('Prepare hooks', 'Use native policy checks for the owned definitions'), ('Back', 'Return to preferences')])
            if choice == 'Back':
                continue
            if choice == 'Keep current':
                return 'Hook trust unchanged.\n' + summary
            return await controls.cli(root, ['settings', '--prepare-hooks', '--codex-binary', controls.relay.binary])
        while True:
            choices = ('off', 'suggest', 'auto') if selected == 'Maintenance' else ('off', 'on')
            choice = await controls.choose(thread, turn, context(controls, root) + '\n' + selected + ': current = ' + values[selected],
                [('Keep current', 'Retain ' + values[selected])] + [(name, 'Select ' + name) for name in choices] + [('Back', 'Return to preferences')])
            if choice == 'Back':
                break
            if choice == 'Keep current' or choice == values[selected]:
                return selected + ' unchanged: ' + values[selected] + '.'
            confirmation = await controls.choose(thread, turn, context(controls, root) + '\n' + selected + ': ' + values[selected] + ' → ' + choice,
                [('Keep current', 'Do not apply this change'), ('Apply change', 'Apply only the displayed preference'), ('Back', 'Choose the value again')])
            if confirmation == 'Back':
                continue
            if confirmation == 'Keep current':
                return selected + ' unchanged: ' + values[selected] + '.'
            result = await controls.cli(root, ['settings', '--maintenance' if selected == 'Maintenance' else '--adaptive', choice])
            return selected + ': ' + values[selected] + ' → ' + choice + '\n' + result


async def maintenance(controls, thread, turn, root):
    while True:
        choice = await controls.choose(thread, turn, context(controls, root) + '\nMaintenance',
            [('Status', 'Inspect observations without a model request'), ('Settings', 'Inspect current preferences'),
             ('Review', 'Request a model review under current policy; uses conversation tokens'), ('Back', 'Return to diagnostics')])
        if choice == 'Back':
            return None
        if choice == 'Review':
            return {'review': True}
        if choice == 'Status':
            return await controls.execute(thread, turn, root, 'maintenance', [])
        result = await settings(controls, thread, turn, root)
        if result is not None:
            return result


async def configure(controls, thread, turn, root, command):
    target, stage, origin = root, 'project', 'project'
    path_value, selected, briefs = None, False, {}
    while True:
        if stage == 'project':
            options = ([('Keep selected project', ui.clean(target))] if selected else [])
            choice = await controls.choose(thread, turn, context(controls, root) + '\nSelect the project for Harness ' + command + '.',
                options + [('Current project', ui.clean(root)), ('Another directory', 'Enter a path; missing folders require confirmation'), ('Back', 'Return to the parent menu')])
            if choice == 'Back':
                return None
            if choice == 'Another directory':
                stage = 'path'
                continue
            if choice == 'Current project':
                target = root
            selected, origin, stage = True, 'project', 'existing'
        if stage == 'path':
            value = await retained_input(controls, thread, turn, 'Project directory (absolute or relative to ' + ui.clean(root) + ')', path_value)
            if value is None:
                stage = 'project'
                continue
            path_value = value
            try:
                target = project_target(root / Path(value).expanduser())
            except (OSError, ValueError) as exc:
                await controls.text(thread, turn, ui.clean(exc))
                continue
            selected, origin, stage = True, 'path', 'existing'
        if stage == 'existing':
            existing = os.path.lexists(target / '.harness/manifest.json')
            if existing:
                choice = await controls.choose(thread, turn, 'A project harness already exists at ' + ui.clean(target) + '.',
                    [('Review and update', 'Preserve owned artifacts and review changes; no automatic reset'), ('Status', 'Inspect without generation'), ('Back', 'Return to project selection')])
                if choice == 'Back':
                    stage = origin
                    continue
                if choice == 'Status':
                    return await controls.cli(target, ['status'])
            selected_command = 'config' if existing else 'init'
            stage = 'brief'
        if stage == 'brief':
            saved = briefs.get(str(target))
            options = [('Keep entered brief', ui.clean(saved[1]) if saved else 'Existing project evidence')] if str(target) in briefs else []
            choice = await controls.choose(thread, turn, 'Project: ' + ui.clean(target) + '\nHow should the project be described?',
                options + [('Describe the project', 'Enter its purpose and expected work'), ('Markdown file', 'Enter a file path; its contents stay in the file'),
                 ('Use existing project evidence', 'Inspect the project and ask when its purpose is unclear'), ('Back', 'Return to the previous project step')])
            if choice == 'Back':
                stage = 'existing' if existing else origin
                continue
            if choice == 'Keep entered brief':
                raw_arguments = list(saved)
                stage = 'confirm'
            elif choice == 'Use existing project evidence':
                raw_arguments = briefs[str(target)] = []
                stage = 'confirm'
            else:
                brief_kind = '--goal-file' if choice == 'Markdown file' else '--goal'
                stage = 'description'
        if stage == 'description':
            saved = briefs.get(str(target))
            previous = saved[1] if saved and saved[0] == brief_kind else None
            value = await retained_input(controls, thread, turn,
                'Markdown path, relative to ' + ui.clean(target) if brief_kind == '--goal-file' else 'Describe the project and expected tasks', previous)
            if value is None:
                stage = 'brief'
                continue
            raw_arguments = briefs[str(target)] = [brief_kind, value]
            stage = 'confirm'
        if stage == 'confirm':
            try:
                _, arguments = goal_arguments(target, raw_arguments)
            except (OSError, ValueError) as exc:
                await controls.text(thread, turn, ui.clean(exc))
                brief_kind = raw_arguments[0] if raw_arguments else '--goal'
                stage = 'description' if raw_arguments else 'brief'
                continue
            moving = target != await controls.cwd(thread)
            summary = ('Project: ' + ui.clean(target) + '\nAction: ' + selected_command +
                       '\nBrief: ' + (ui.clean(arguments[1]) if arguments else 'Existing project evidence') +
                       ('\nThe missing project directory will be created after confirmation.' if not target.exists() else '') +
                       ('\nFinish current work, then /quit to open the target conversation and configure it.' if moving else
                        '\nThe current model and permissions will be used. Configuration uses conversation tokens.'))
            choice = await controls.choose(thread, turn, summary,
                [('Confirm', 'Create or review the selected project harness'), ('Back', 'Return to the entered brief')])
            if choice == 'Back':
                brief_kind = raw_arguments[0] if raw_arguments else '--goal'
                stage = 'description' if raw_arguments else 'brief'
                continue
            if project_target(target) != target:
                raise ValueError('Project location changed. Select it again before configuration.')
            if moving:
                action = {'action': 'configure', 'root': str(target), 'command': selected_command, 'arguments': arguments}
                if not await controls.queue(thread, turn, action):
                    return 'Existing reservation retained.\n' + controls.queued_action()
                return 'Project configuration queued. Finish active work, then use /quit. The target opens with its own instructions and permissions; no source conversation is copied.'
            return {'configuration': (target, selected_command, arguments)}


async def tools(controls, thread, turn, root, command):
    path, name, stage = None, None, 'menu'
    while True:
        if command == 'jev':
            choice = await controls.choose(thread, turn, context(controls, root) + '\nJev retrieval advice',
                [('Status', 'Inspect settings without an API call'), ('Enable shadow advice', 'Keep suggestions observational'), ('Disable', 'Turn off project advice'),
                 ('Login', 'Open private terminal login after /quit; never enter keys in chat'), ('Logout', 'Remove the saved key through terminal confirmation after /quit'), ('Back', 'Return to the parent menu')])
            if choice == 'Back':
                return None
            if choice in {'Login', 'Logout'}:
                if not await controls.queue(thread, turn, {'action': 'jev', 'operation': choice.lower(), 'root': str(root)}):
                    return 'Existing reservation retained.\n' + controls.queued_action()
                return 'Private Jev ' + choice.lower() + ' queued. Use /quit when ready; Harness will open its terminal flow automatically. Never paste credentials in chat.'
            return await controls.cli(root, ['jev', {'Status': 'status', 'Enable shadow advice': 'enable', 'Disable': 'disable'}[choice]])
        if command == 'graft':
            if stage == 'menu':
                choice = await controls.choose(thread, turn, context(controls, root) + '\nProject code retrieval',
                    [('Status', 'Inspect local graph settings'), ('Enable', 'Prepare project retrieval'), ('Disable', 'Preserve the graph but stop using it'),
                     ('Add external source', 'Attach only an explicitly selected file or directory'), ('Back', 'Return to the parent menu')])
                if choice == 'Back':
                    return None
                if choice != 'Add external source':
                    return await controls.cli(root, ['graft', choice.lower()], timeout=180)
                stage = 'path'
            if stage == 'path':
                value = await retained_input(controls, thread, turn, 'External file or directory path, relative to ' + ui.clean(root), path)
                if value is None:
                    stage = 'menu'
                    continue
                path, stage = value, 'name'
            if stage == 'name':
                value = await retained_input(controls, thread, turn, 'Source label (lowercase letters, digits and hyphens)', name)
                if value is None:
                    stage = 'path'
                    continue
                name = value
                return await controls.cli(root, ['graft', 'add', str(root / Path(path).expanduser()), '--name', name], timeout=180)
        choice = await controls.choose(thread, turn, context(controls, root) + '\nHarness tools',
            [('Check updates', 'Read the published version'), ('Update', 'Offer an update after leaving Codex'),
             ('Uninstall', 'Queue terminal confirmation; project harnesses are retained'), ('Queued action', 'Review or cancel the after-exit reservation'), ('Back', 'Return to management groups')])
        if choice == 'Back':
            return None
        if choice == 'Queued action':
            current = controls.relay.after_exit
            if not current:
                return controls.queued_action()
            selected = await controls.choose(thread, turn, controls.queued_action(),
                [('Keep queued action', 'Leave the displayed reservation unchanged'), ('Cancel queued action', 'Cancel only this displayed reservation'), ('Back', 'Return to tools')])
            if selected == 'Back':
                continue
            if selected == 'Cancel queued action' and controls.relay.after_exit == current:
                return controls.cancel_queued(current['action'])
            return 'Existing reservation retained.\n' + controls.queued_action()
        if choice == 'Uninstall':
            if not await controls.queue(thread, turn, {'action': 'uninstall'}):
                return 'Existing reservation retained.\n' + controls.queued_action()
            return 'Tool uninstall queued. Use /quit when ready. The terminal will show the removal scope and request confirmation; project harnesses are retained.'
        return await controls.execute(thread, turn, root, 'update', ['--check'] if choice == 'Check updates' else [])


async def switch(controls, thread, turn, root, arguments):
    if len(arguments) > 1:
        raise ValueError('Use /harness/switch "PROJECT_PATH", or omit the path to choose a recent project.')
    path, stage = None, 'confirm' if arguments else 'project'
    if arguments:
        target = project_root(root / Path(arguments[0]).expanduser())
    else:
        result = await controls.call('thread/list', {'limit': 50, 'archived': False})
        paths = {}
        for item in result.get('data', []):
            try:
                location = project_root(item['cwd'])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if location != root:
                paths[str(location)] = location
    while True:
        if stage == 'project':
            choice = await controls.choose(thread, turn, context(controls, root) + '\nSelect a reachable project. Each project keeps its own conversation and instructions.',
                [('Another directory', 'Enter a project path')] + [(name, 'Open this project after normal exit') for name in list(paths)[:12]] + [('Back', 'Return to the parent menu')])
            if choice == 'Back':
                return None
            if choice == 'Another directory':
                stage = 'path'
                continue
            target, stage = paths[choice], 'confirm'
        if stage == 'path':
            value = await retained_input(controls, thread, turn, 'Existing project path, relative to ' + ui.clean(root), path)
            if value is None:
                stage = 'project'
                continue
            path = value
            try:
                target = project_root(root / Path(path).expanduser())
            except (OSError, ValueError) as exc:
                await controls.text(thread, turn, ui.clean(exc))
                continue
            stage = 'confirm'
        if target == root:
            return 'This project is already selected. Describe the new task normally; another agent or regeneration is not required.'
        choice = await controls.choose(thread, turn, 'Open ' + ui.clean(target) + ' after this screen closes?',
            [('Resume picker', 'Choose a saved conversation in the target project'), ('New conversation', 'Start with the target project instructions'), ('Back', 'Return to project selection')])
        if choice == 'Back':
            if arguments:
                return None
            stage = 'path' if path is not None else 'project'
            continue
        if not await controls.queue(thread, turn, {'action': 'switch', 'root': str(target), 'resume': choice == 'Resume picker'}):
            return 'Existing reservation retained.\n' + controls.queued_action()
        configured = (target / '.harness/manifest.json').is_file()
        return ('Project switch queued. Finish any active agents or background work, then use /quit. '
                'Codex will open the selected project in this terminal; this conversation remains saved. '
                'No transcript or permission overrides are copied.\n' +
                ('The target harness will be loaded by its native conversation.' if configured else
                 'No target harness is confirmed. In the new conversation, use /harness/init to generate one, or continue with ordinary Codex.'))
