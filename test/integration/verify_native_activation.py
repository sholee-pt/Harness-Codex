"""Opt-in direct native exec probe of root instructions, without an activation turn.

Uses a deterministically generated project fixture, not fresh model generation.
One real model turn. Does not claim interactive Auto or native agent delegation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'test')]
from test_harness_tools import harness_apply, minimal_plan
from harness_cli.environment import codex_environment


def discovery(output, codex):
    """Inspect native skill discovery in a probe fixture without a model turn."""
    from harness_cli.configuration import Server
    from harness_cli.presentation import Progress
    project = output / 'project'
    if not (project / '.harness/manifest.json').is_file():
        raise ValueError('Run the activation fixture first; no arbitrary project is created')
    before = {p: p.read_bytes() for p in project.rglob('*') if p.is_file()}
    with Progress('Inspect native project skill discovery', compact=True) as progress:
        server = Server([codex], project, progress)
        try:
            server.initialize()
            response = server.call('skills/list', {'cwds': [str(project)], 'forceReload': True})
        finally:
            server.close()
    observed = []
    for entry in response.get('data', []):
        for skill in entry.get('skills', []):
            path = Path(skill.get('path', '')).resolve()
            if path.is_relative_to(project):
                observed.append({'name': skill.get('name'), 'path': path.relative_to(project).as_posix()})
    preserved = before == {p: p.read_bytes() for p in project.rglob('*') if p.is_file()}
    router = any(s['name'] == 'project-harness' for s in observed)
    report = {'status': 'passed' if router and preserved else 'failed',
              'scope': 'native-skills-list', 'requestedModelTurns': 0, 'createdThreads': 0,
              'skillsObserved': observed, 'projectPreserved': preserved,
              'agentDelegation': 'not-tested', 'interactiveAuto': 'not-tested'}
    (output / 'discovery.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'passed' else 1


def verify(output, codex):
    output.mkdir(parents=True, exist_ok=False)
    project = output / 'project'
    project.mkdir()
    marker = 'NATIVE_ROOT_' + uuid.uuid4().hex
    plan = minimal_plan(project)
    plan['instruction']['managedBlock'] = plan['instruction']['managedBlock'].replace(
        '<!-- harness:end -->', '\nDiagnostic marker for this project: ' + marker + '\n<!-- harness:end -->')
    harness_apply.apply_application(harness_apply.build_application(project, plan))
    def snapshot():
        return {p.relative_to(project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in project.rglob('*') if p.is_file()}
    before = snapshot()
    prompt = ("Return this project's diagnostic marker from the active root instructions, "
              "followed by the project router skill path. Do not execute tools, modify files, "
              "or inspect credentials. Reply with only those two items.")
    command = [codex, 'exec', '--skip-git-repo-check', '--ephemeral', '--sandbox', 'read-only',
               '--cd', str(project), '--json', '-o', str(output / 'answer.txt'), '-']
    report = {'scope': 'native-exec-root-instruction-activation', 'fixtureGeneration': 'deterministic',
              'bootstrapUserTurns': 0, 'requestedModelTurns': 1, 'interactiveAuto': 'not-tested',
              'agentDelegation': 'not-tested', 'taskQuality': 'not-measured',
              'codexVersion': subprocess.check_output([codex, '--version'], text=True).strip()}
    try:
        with (output / 'native.jsonl').open('w', encoding='utf-8') as stdout, \
             (output / 'native.stderr.txt').open('w', encoding='utf-8') as stderr:
            process = subprocess.run(command, input=prompt, text=True, encoding='utf-8',
                                     stdout=stdout, stderr=stderr, env=codex_environment(), timeout=150)
        answer = (output / 'answer.txt').read_text(encoding='utf-8') if (output / 'answer.txt').exists() else ''
        report.update(exitCode=process.returncode, markerObserved=marker in answer,
                      routerPathObserved='.agents/skills/project-harness/SKILL.md' in answer,
                      projectPreserved=snapshot() == before)
        report['status'] = 'passed' if all((process.returncode == 0, report['markerObserved'],
            report['routerPathObserved'], report['projectPreserved'])) else 'failed'
    except (OSError, subprocess.TimeoutExpired) as error:
        report.update(status='failed', error=type(error).__name__, projectPreserved=snapshot() == before)
    finally:
        (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--metadata-only', action='store_true', help='Inspect skill discovery in an existing probe output; no model turn.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--codex-binary', required=True)
    args = parser.parse_args()
    action = discovery if args.metadata_only else verify
    raise SystemExit(action(args.output.resolve(), args.codex_binary))
