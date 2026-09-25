"""Explicit offline import and discovery of external project skills."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from . import presentation as ui


def register(commands):
    parser = commands.add_parser('skills', help='List project skills or import a reviewed local external skill; no downloads.')
    parser.add_argument('skills_action', choices=('list', 'add', 'verify'), nargs='?', default='list')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--source', type=Path, help='Original local skill directory containing SKILL.md.')
    parser.add_argument('--upstream', help='Declared GitHub repository URL; requires --revision.')
    parser.add_argument('--revision', help='Declared full upstream commit SHA; no network lookup.')
    parser.add_argument('--license-file', type=Path, help='Copy the upstream root license alongside the selected skill.')
    parser.add_argument('--name', help='Installed external skill name for verify.')
    parser.add_argument('--dry-run', action='store_true', help='Preview add without writing any files.')


def run(args, source_root):
    scripts = Path(source_root) / '.agents/skills/harness/scripts'
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location('harness_external_skills', scripts / 'harness_external_skills.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    if args.skills_action == 'add':
        if args.source is None or args.name is not None:
            raise ValueError('skills add requires --source and keeps the original name')
        result = module.add(args.project, args.source, upstream=args.upstream, revision=args.revision,
                            license_file=args.license_file, dry_run=args.dry_run)
    else:
        if args.source or args.upstream or args.revision or args.license_file or args.dry_run:
            raise ValueError('Import options are only valid with skills add')
        if args.skills_action == 'verify':
            if args.name is None:
                raise ValueError('skills verify requires --name')
            result = module.verify(args.project, args.name)
        else:
            if args.name is not None:
                raise ValueError('--name is only valid with skills verify')
            result = module.inventory(args.project)
    if args.json:
        ui.report(result, title='Project skills')
    elif args.skills_action == 'list':
        print('Project skills (metadata only):')
        for entry in result['skills']:
            print('  ' + ui.clean(entry['path']) + ': ' + ui.clean(entry.get('description', entry.get('error'))))
        if not result['skills']:
            print('  No project-local skills found.')
        if result['truncated']:
            print('  Inventory limit reached; additional skills were not inspected.')
    else:
        print('External skill: ' + ui.clean(result['status']))
        print('  ' + ui.clean(result.get('path', result.get('skill'))))
        for path in result.get('changedFiles', []):
            print('  Changed: ' + ui.clean(path))
        if args.skills_action == 'add':
            print('  Original metadata retained. Native discovery is not tested; review with config when needed.')
    return 1 if result.get('status') == 'changed' else 0
