"""Run bundled helper entrypoints with the installed interpreter, offline."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from .environment import codex_environment
from .paths import checked_path

ENTRYPOINTS = ('inventory', 'harness_state', 'harness_plan_builder', 'harness_apply', 'validate_harness',
              'harness_doctor', 'validate_runtime_plan', 'validate_coordination_packet', 'evaluate_topology',
              'harness_runtime_receipt', 'harness_relay_receipt', 'harness_eval', 'harness_ops',
              'harness_checkpoint', 'harness_maintenance', 'harness_external_skills')


def register(commands):
    parser = commands.add_parser('helper', help='Run a bundled generator/validation helper with the installed Python; no Conda activation.')
    parser.add_argument('helper_name', choices=ENTRYPOINTS)
    parser.add_argument('helper_arguments', nargs=argparse.REMAINDER)


def run(args, source_root):
    script = checked_path(Path(source_root) / '.agents/skills/harness/scripts' / (args.helper_name + '.py'))
    # The interpreter is dedicated; checks launched by helpers retain the user's
    # project PATH and environment. Do not activate Harness in the project shell.
    result = subprocess.run([sys.executable, '-B', str(script), *args.helper_arguments],
                            env=codex_environment(), check=False)
    return result.returncode if result.returncode >= 0 else 128 - result.returncode
