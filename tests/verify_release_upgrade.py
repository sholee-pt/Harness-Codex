"""Reproduce a real v7.6 install -> v8.0 update using two source trees.

Run with the harness Conda Python. No network or live Codex is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib


def snapshot(root):
    return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}


def instruction_sizes(root):
    values = {'.agents/skills/project-harness/SKILL.md': (root / '.agents/skills/project-harness/SKILL.md').read_text(encoding='utf-8')}
    values.update({p.relative_to(root).as_posix(): tomllib.loads(p.read_text(encoding='utf-8'))['developer_instructions'] for p in (root / '.codex/agents').glob('*.toml')})
    return {path: {'characters': len(value), 'utf8Bytes': len(value.encode('utf-8'))} for path, value in values.items()}


def worker(source, root, stage):
    sys.path[:0] = [str(source / '.agents/skills/harness/scripts'), str(source / 'tests')]
    import harness_apply
    import harness_metadata
    import harness_plan_builder
    import validate_harness
    import test_runtime_teamplay

    draft = test_runtime_teamplay.DeterministicPlanBuilderTests()._draft('coordinated-cross-contract-plan.json')
    if stage == 'baseline':
        assert harness_metadata.HARNESS_VERSION == '7.6'
        shutil.copytree(source / 'tests/fixtures/coordinated-cross-contract', root, dirs_exist_ok=True)
        plan = harness_plan_builder.materialize_plan(draft, root=root)
        harness_apply.apply_application(harness_apply.build_application(root, plan))
        report = validate_harness.Validator(root).run()
        assert report['valid'], report['errors']
        return {'generatorVersion': harness_metadata.HARNESS_VERSION, 'valid': report['valid'], 'instructionSizes': instruction_sizes(root), 'agentCount': len(plan['topology']['agents'])}
    assert harness_metadata.HARNESS_VERSION == '8.0'
    before = snapshot(root)
    legacy = validate_harness.Validator(root).run()
    assert snapshot(root) == before
    plan = harness_plan_builder.materialize_plan(draft, root=root)
    if stage == 'dirty':
        assert legacy['installationStatus'] == 'invalid', legacy
        try:
            harness_apply.build_application(root, plan)
        except harness_apply.PlanError:
            assert snapshot(root) == before
            return {'installationStatus': legacy['installationStatus'], 'updateRefused': True, 'externalEditPreserved': True}
        raise AssertionError('A modified installation must not be overwritten')
    assert legacy['installationStatus'] == 'upgrade-required' and legacy['integrityValid'], legacy
    application = harness_apply.build_application(root, plan)
    assert application['report']['valid'] and snapshot(root) == before
    applied = harness_apply.apply_application(application)
    report = validate_harness.Validator(root).run()
    assert report['valid'], report['errors']
    updated = snapshot(root)
    repeated = harness_apply.apply_application(harness_apply.build_application(root, plan))
    assert repeated['writes'] == 0 and snapshot(root) == updated
    return {'before': legacy['installationStatus'], 'after': report['installationStatus'], 'dryRunReadOnly': True, 'writes': applied['writes'], 'repeatWrites': repeated['writes'], 'noOpBytesAndMtimesPreserved': True, 'instructionSizes': instruction_sizes(root), 'agentCount': len(plan['topology']['agents'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', choices=['baseline', 'current', 'dirty'])
    parser.add_argument('--root', type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.baseline.resolve(), args.root.resolve(), args.worker)))
        return 0
    if args.output is None:
        parser.error('--output is required')
    source = Path(__file__).resolve().parents[1]
    def invoke(tree, target, stage):
        process = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--baseline', str(tree.resolve()), '--worker', stage, '--root', str(target)], capture_output=True, text=True, encoding='utf-8')
        if process.returncode:
            raise RuntimeError(process.stdout + process.stderr)
        return json.loads(process.stdout)
    with tempfile.TemporaryDirectory(prefix='harness-v80-upgrade-') as directory:
        clean = Path(directory) / 'clean'
        dirty = Path(directory) / 'dirty'
        baseline = invoke(args.baseline, clean, 'baseline')
        current = invoke(source, clean, 'current')
        invoke(args.baseline, dirty, 'baseline')
        agent = next((dirty / '.codex/agents').glob('*.toml'))
        with agent.open('a', encoding='utf-8') as handle:
            handle.write('\n# External user edit\n')
        conflict = invoke(source, dirty, 'dirty')
    delta = {path: {metric: size[metric] - baseline['instructionSizes'][path][metric] for metric in ('characters', 'utf8Bytes')} for path, size in current['instructionSizes'].items()}
    report = {'schemaVersion': 1, 'pythonVersion': sys.version.split()[0], 'baseline': baseline, 'current': current, 'conflict': conflict, 'instructionSizeDelta': delta, 'measurementScope': 'Decoded agent developer_instructions and full project-harness SKILL.md from the same coordinated fixture; static text only', 'liveCodexInvoked': False, 'loadedTokens': None, 'billingCost': None, 'valid': True}
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
