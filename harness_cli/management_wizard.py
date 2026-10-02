"""Explicit project selection and briefs through native, local question controls."""
from __future__ import annotations

import os
from pathlib import Path

from .paths import project_target
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


async def configure(controls, thread, turn, root, command):
    target, arguments, stage = root, [], 'project'
    while True:
        if stage == 'project':
            choice = await controls.choose(thread, turn, 'Select the project for Harness ' + command + '.',
                [('Current project', ui.clean(root)), ('Another directory', 'Enter a path; missing folders require confirmation'), ('Back', 'Return to management')])
            if choice == 'Back':
                return 'Returned without configuring a project.'
            if choice == 'Current project':
                target = root
            else:
                value = await controls.enter(thread, turn, 'Project directory (absolute or relative to ' + ui.clean(root) + '). Enter :back to go back.')
                if value == ':back':
                    continue
                try:
                    target = project_target(root / Path(value).expanduser())
                except (OSError, ValueError) as exc:
                    await controls.text(thread, turn, ui.clean(exc))
                    continue
            stage = 'existing'
        if stage == 'existing':
            if os.path.lexists(target / '.harness/manifest.json'):
                choice = await controls.choose(thread, turn, 'A project harness already exists at ' + ui.clean(target) + '.',
                    [('Review and update', 'Preserve owned artifacts and review changes; no automatic reset'), ('Status', 'Inspect the existing project without generation'), ('Back', 'Choose the project again')])
                if choice == 'Back':
                    stage = 'project'
                    continue
                if choice == 'Status':
                    return await controls.cli(target, ['status'])
                selected_command = 'config'
            else:
                selected_command = 'init'
            stage = 'brief'
        if stage == 'brief':
            choice = await controls.choose(thread, turn, 'Project: ' + ui.clean(target) + '\nHow should the project be described?',
                [('Describe the project', 'Enter its purpose and expected work'), ('Markdown file', 'Enter a file path; its contents stay in the file'),
                 ('Use existing project evidence', 'Inspect the project and ask when its purpose is unclear'), ('Back', 'Choose the project again')])
            if choice == 'Back':
                stage = 'project'
                continue
            arguments = []
            if choice != 'Use existing project evidence':
                value = await controls.enter(thread, turn, ('Markdown path, relative to the selected project' if choice == 'Markdown file' else 'Describe the project and expected tasks') + '. Enter :back to go back.')
                if value == ':back':
                    continue
                arguments = ['--goal-file' if choice == 'Markdown file' else '--goal', value]
            try:
                _, arguments = goal_arguments(target, arguments)
            except (OSError, ValueError) as exc:
                await controls.text(thread, turn, ui.clean(exc))
                continue
            stage = 'confirm'
        if stage == 'confirm':
            moving = target != await controls.cwd(thread)
            summary = ('Project: ' + ui.clean(target) + '\nAction: ' + selected_command +
                       '\nBrief: ' + (ui.clean(arguments[1]) if arguments else 'Existing project evidence') +
                       ('\nThe missing project directory will be created after confirmation.' if not target.exists() else '') +
                       ('\nFinish current work, then /quit to open the target conversation and configure it.' if moving else
                        '\nThe current model and permissions will be used. Configuration uses conversation tokens.'))
            choice = await controls.choose(thread, turn, summary,
                [('Confirm', 'Create or review the selected project harness'), ('Back', 'Edit the project description')])
            if choice == 'Back':
                stage = 'brief'
                continue
            if project_target(target) != target:
                raise ValueError('Project location changed. Select it again before configuration.')
            if moving:
                controls.relay.after_exit = {'action': 'configure', 'root': str(target), 'command': selected_command, 'arguments': arguments}
                return 'Project configuration queued. Finish active work, then use /quit. The target opens with its own instructions and permissions; no source conversation is copied.'
            return {'configuration': (target, selected_command, arguments)}


async def tools(controls, thread, turn, root, command):
    if command == 'jev':
        choice = await controls.choose(thread, turn, 'Jev retrieval advice',
            [('Status', 'Inspect settings without an API call'), ('Enable shadow advice', 'Keep suggestions observational'), ('Disable', 'Turn off project advice'),
             ('Login', 'Open private terminal login after /quit; never enter keys in chat'), ('Logout', 'Remove the saved key through terminal confirmation after /quit'), ('Back', 'Return')])
        if choice in {'Login', 'Logout'}:
            controls.relay.after_exit = {'action': 'jev', 'operation': choice.lower(), 'root': str(root)}
            return 'Private Jev ' + choice.lower() + ' queued. Use /quit when ready; Harness will open its terminal flow automatically. Never paste credentials in chat.'
        if choice == 'Back':
            return 'No Jev changes.'
        return await controls.cli(root, ['jev', {'Status': 'status', 'Enable shadow advice': 'enable', 'Disable': 'disable'}[choice]])
    if command == 'graft':
        choice = await controls.choose(thread, turn, 'Project code retrieval',
            [('Status', 'Inspect local graph settings'), ('Enable', 'Prepare project retrieval'), ('Disable', 'Preserve the graph but stop using it'),
             ('Add external source', 'Attach only an explicitly selected file or directory'), ('Back', 'Return')])
        if choice == 'Back':
            return 'No retrieval changes.'
        arguments = ['graft', {'Status': 'status', 'Enable': 'enable', 'Disable': 'disable', 'Add external source': 'add'}[choice]]
        if choice == 'Add external source':
            path = await controls.enter(thread, turn, 'External file or directory path. Enter :back to return.')
            if path == ':back':
                return 'No source attached.'
            name = await controls.enter(thread, turn, 'Source label. Enter :back to return.')
            if name == ':back':
                return 'No source attached.'
            arguments += [str(root / Path(path).expanduser()), '--name', name]
        return await controls.cli(root, arguments, timeout=180)
    choice = await controls.choose(thread, turn, 'Harness tool management',
        [('Check updates', 'Read the published version'), ('Update', 'Offer an update after leaving Codex'),
         ('Uninstall', 'Queue terminal confirmation; project harnesses are retained'), ('Back', 'Return')])
    if choice == 'Uninstall':
        controls.relay.after_exit = {'action': 'uninstall'}
        return 'Tool uninstall queued. Use /quit when ready. The terminal will show the removal scope and request confirmation; project harnesses are retained.'
    if choice == 'Back':
        return 'No tool changes.'
    return await controls.execute(thread, turn, root, 'update', ['--check'] if choice == 'Check updates' else [])
