"""Shared deterministic management operations; ordinary CLI commands remain public."""
from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

from . import dashboard, presentation as ui, project, project_preferences
from .paths import project_root


def register(commands):
    parser = commands.add_parser('switch', help='Open another project in native Codex; keep existing conversation history separate.')
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--new', action='store_true', help='Start a new conversation instead of opening the resume picker.')
    parser.add_argument('--codex-binary', default='codex')
    parser = commands.add_parser('settings', help='Inspect or change project preferences without regenerating its harness.')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--maintenance', choices=('off', 'suggest', 'auto'))
    parser.add_argument('--adaptive', choices=('on', 'off'))
    parser.add_argument('--prepare-hooks', action='store_true', help='Prepare exact owned hook trust using native Codex policy checks.')
    parser.add_argument('--codex-binary', default='codex')
    for name in ('_complete-init', '_complete-config'):
        parser = commands.add_parser(name, help=argparse.SUPPRESS)
        parser.add_argument('--project', required=True, type=Path)
        parser.add_argument('--codex-binary', required=True)
    commands._choices_actions[:] = [action for action in commands._choices_actions if not action.dest.startswith('_complete-')]


def run(args, source_root):
    root = project_root(args.project)
    if args.command == 'switch':
        import subprocess
        from .environment import codex_environment
        arguments = ['--cd', str(root)]
        if not args.new:
            arguments += ['resume']
        return subprocess.call([*project._codex_command(args.codex_binary), *arguments], env=codex_environment())
    if args.command in {'_complete-init', '_complete-config'}:
        code, report = project._report(source_root, root)
        if code or not report.get('valid'):
            ui.report(report, title='Configuration incomplete')
            return 1
        project._sync_guide(source_root, root)
        from .workspace_context import prepare
        prepare(root, [args.codex_binary])
        if args.command == '_complete-init':
            project._configure_retrieval(SimpleNamespace(command='init', retrieval='auto', json=True), source_root, root)
        args.maintenance, args.adaptive = None, None
        args.prepare_hooks = args.command == '_complete-init'
    if args.maintenance is not None or args.adaptive is not None:
        project_preferences.configure(args, source_root, root, emit=False)
    hook_report = None
    if args.prepare_hooks:
        from .hook_trust import prepare
        hook_report = prepare(source_root, root, binary=args.codex_binary)
    report = project.project_status(source_root, root, project.load_installer(source_root))
    report['features'] = dashboard.collect(source_root, root)
    if hook_report is not None:
        report['hookPreparation'] = hook_report
    from .main import version
    dashboard.display(report, root, version(source_root))
    return 0
