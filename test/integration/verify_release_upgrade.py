"""Reproduce only the previous version install -> current beta update.

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
    tests_root = source / ("test" if (source / "test").is_dir() else "tests")
    sys.path[:0] = [str(source / '.agents/skills/harness/scripts'), str(tests_root)]
    import harness_apply
    import harness_doctor
    import harness_metadata
    import harness_plan_builder
    import validate_harness
    import test_runtime_teamplay
    import validate_runtime_plan

    draft = test_runtime_teamplay.DeterministicPlanBuilderTests()._draft('coordinated-cross-contract-plan.json')
    if stage == 'baseline':
        assert harness_metadata.HARNESS_VERSION == '0.29.0-beta'
        shutil.copytree(tests_root / 'fixtures/coordinated-cross-contract', root, dirs_exist_ok=True)
        plan = harness_plan_builder.materialize_plan(draft, root=root)
        harness_apply.apply_application(harness_apply.build_application(root, plan))
        report = validate_harness.Validator(root).run()
        assert report['valid'], report['errors']
        (root.parent / (root.name + '-baseline-plan.json')).write_text(json.dumps(plan), encoding='utf-8')
        return {'generatorVersion': harness_metadata.HARNESS_VERSION, 'valid': report['valid'], 'instructionSizes': instruction_sizes(root), 'agentCount': len(plan['topology']['agents'])}
    assert harness_metadata.HARNESS_VERSION == '0.29.1-beta'
    before = snapshot(root)
    legacy = validate_harness.Validator(root).run()
    doctor = harness_doctor.diagnose(root)
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
    original_manifest = json.loads((root / '.harness/manifest.json').read_text(encoding='utf-8'))
    original_version = original_manifest['generator']['version']
    assert original_version == '0.29.0-beta'
    expected_status = 'valid'
    assert legacy['installationStatus'] == expected_status and legacy['integrityValid'], legacy
    assert doctor['installationStatus'] == expected_status, doctor
    previous_plan_accepted = None
    runtime_compatible = None
    if original_version == '0.29.0-beta':
        # The unchanged plan was produced by the actual old source subprocess.
        # The new advisory is optional, so its absence cannot invalidate it.
        import harness_git_policy
        previous_plan = json.loads((root.parent / (root.name + '-baseline-plan.json')).read_text(encoding='utf-8'))
        for artifact in previous_plan['artifacts']:
            content = artifact['content']
            if artifact['path'].endswith('.toml'):
                content = tomllib.loads(content)['developer_instructions']
            if artifact['path'].endswith('.toml') or artifact['path'] == '.agents/skills/project-harness/SKILL.md':
                assert harness_git_policy.GUIDANCE in content
        previous_plan_accepted = harness_apply.build_application(root, previous_plan)['report']['valid']
        assert previous_plan_accepted and snapshot(root) == before
        runtime = test_runtime_teamplay.valid_plan(root, original_manifest)
        runtime_compatible = validate_runtime_plan.validate_runtime_plan(root, runtime)['valid']
        assert runtime_compatible and snapshot(root) == before
    application = harness_apply.build_application(root, plan)
    assert application['report']['valid'] and snapshot(root) == before
    applied = harness_apply.apply_application(application)
    report = validate_harness.Validator(root).run()
    assert report['valid'], report['errors']
    assert json.loads((root / '.harness/manifest.json').read_text(encoding='utf-8'))['generator']['version'] == harness_metadata.HARNESS_VERSION
    updated = snapshot(root)
    repeated = harness_apply.apply_application(harness_apply.build_application(root, plan))
    assert repeated['writes'] == 0 and snapshot(root) == updated
    return {'beforeGeneratorVersion': original_version, 'before': legacy['installationStatus'], 'doctorBefore': doctor['installationStatus'], 'after': report['installationStatus'], 'previousPlanAccepted': previous_plan_accepted, 'previousPlanWithoutAdvisoryAccepted': previous_plan_accepted if original_version == '9.0' else None, 'previousRuntimePlanCompatible': runtime_compatible, 'dryRunReadOnly': True, 'writes': applied['writes'], 'repeatWrites': repeated['writes'], 'noOpBytesAndMtimesPreserved': True, 'instructionSizes': instruction_sizes(root), 'agentCount': len(plan['topology']['agents'])}


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
    source = Path(__file__).resolve().parents[2]
    def invoke(tree, target, stage):
        process = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--baseline', str(tree.resolve()), '--worker', stage, '--root', str(target)], capture_output=True, text=True, encoding='utf-8')
        if process.returncode:
            raise RuntimeError(process.stdout + process.stderr)
        return json.loads(process.stdout)
    with tempfile.TemporaryDirectory(prefix='harness-release-upgrade-') as directory:
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
