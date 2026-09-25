"""Explicit checkpoint CLI; never runs on ordinary conversation turns."""
from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
import subprocess
import sys

from .environment import codex_environment
from .presentation import Progress


def register(commands):
    parser = commands.add_parser('checkpoint', help='Opt in to bounded task reuse; native Codex still owns sessions.')
    parser.add_argument('checkpoint_action', choices=('init', 'start', 'record', 'quiesce', 'resume', 'status', 'remove'))
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--store', type=Path, required=True, help='Dedicated user-local directory outside the project.')
    parser.add_argument('--plan', type=Path, help='Reviewed task contract; required except for quiesce/remove. record executes its checks.')
    parser.add_argument('--run', required=True)
    parser.add_argument('--task')
    parser.add_argument('--attempt', help='Execution attempt token returned by start; pass it to record/quiesce.')
    parser.add_argument('--previous')
    parser.add_argument('--keep-days', type=int, help='Explicit retention consent: 1-30 days for init/resume.')
    parser.add_argument('--observed', choices=('idle', 'stopped', 'closed', 'stop-requested'))
    parser.add_argument('--timeout', type=int, default=60)


def run(args, source_root):
    script = Path(source_root) / '.agents/skills/harness/scripts/harness_checkpoint.py'
    command = [sys.executable, '-B', str(script), args.checkpoint_action, '--root', str(args.project),
               '--store', str(args.store), '--run', args.run, '--timeout', str(args.timeout)]
    if args.plan:
        command.extend(['--plan', str(args.plan)])
    for name in ('task', 'previous', 'keep_days', 'observed', 'attempt'):
        value = getattr(args, name)
        if value is not None:
            command.extend(['--' + name.replace('_', '-'), str(value)])
    progress = Progress('Verifying checkpoint task') if args.checkpoint_action == 'record' and not args.json else nullcontext()
    try:
        with progress:
            result = subprocess.run(command, env=codex_environment(), capture_output=True, text=True,
                                    timeout=max(30, min(args.timeout, 300) + 30))
    except subprocess.TimeoutExpired:
        raise ValueError('Checkpoint operation timed out. Observe native agents before releasing retained ownership.') from None
    if result.returncode and not result.stdout.strip():
        raise ValueError(result.stderr.strip() or 'Checkpoint operation failed')
    report = json.loads(result.stdout)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print('Checkpoint: ' + args.checkpoint_action)
        for key, value in report.items():
            print('  ' + key + ': ' + (', '.join(value) if isinstance(value, (list, dict)) else str(value)))
    return result.returncode
