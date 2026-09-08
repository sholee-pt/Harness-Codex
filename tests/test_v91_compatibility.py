"""Keep previous v9 artifacts valid in v9.8 when the optional Git advisory is absent.

These are synthetic contract-equivalent old plans assembled from unchanged
contract blocks. verify_release_upgrade.py separately tests actual old sources.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

from test_apply_compatibility import preserved_state, set_metadata
import test_runtime_teamplay as runtime_fixtures
import harness_agent_contract
import harness_apply as apply
import harness_doctor
import harness_git_policy
import harness_metadata
import harness_teamplay
import validate_harness
import validate_runtime_plan


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / '.agents/skills/harness/scripts'


def previous_plan(root):
    """Build existing canonical contracts without invoking the new materializer."""
    shutil.copytree(REPO / 'tests/fixtures/coordinated-cross-contract', root, dirs_exist_ok=True)
    plan = json.loads((REPO / 'tests/fixtures/coordinated-cross-contract-plan.json').read_text(encoding='utf-8'))
    agents = {agent['path']: agent for agent in plan['topology']['agents']}
    for artifact in plan['artifacts']:
        if artifact['path'] in agents:
            source = harness_agent_contract.materialize(artifact['content'], agents[artifact['path']], plan['topology'])
            instructions = tomllib.loads(source)['developer_instructions']
            if harness_teamplay.AGENT_BLOCK not in instructions:
                instructions += '\n' + harness_teamplay.AGENT_BLOCK + '\n'
            artifact['content'] = harness_agent_contract.replace_instructions(source, instructions)
        elif artifact['path'] == '.agents/skills/project-harness/SKILL.md':
            if harness_teamplay.PROJECT_BLOCK not in artifact['content']:
                artifact['content'] += '\n' + harness_teamplay.PROJECT_BLOCK + '\n'
    return plan


class PreviousReleaseCompatibilityTests(unittest.TestCase):
    def assert_unadvised(self, plan):
        for artifact in plan['artifacts']:
            text = artifact['content']
            if artifact['path'].endswith('.toml'):
                text = tomllib.loads(text)['developer_instructions']
            self.assertNotIn(harness_git_policy.GUIDANCE, text)

    def invoke(self, script, arguments, root, expected=0, readonly=True):
        before = preserved_state(root)
        process = subprocess.run([sys.executable, '-B', str(SCRIPTS / script), *map(str, arguments)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
        report = json.loads(process.stdout)
        if readonly:
            self.assertEqual(preserved_state(root), before)
        return report

    def test_previous_and_current_manifests_accept_unadvised_artifacts_across_apis(self):
        for version in ('9.0', '9.1', '9.2', '9.3', '9.4'):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = previous_plan(root)
                self.assert_unadvised(plan)
                apply.apply_application(apply.build_application(root, plan))
                manifest = set_metadata(root, version, 2)
                before = preserved_state(root)
                self.assertEqual(validate_harness.Validator(root).run()['installationStatus'], 'valid')
                self.assertTrue(harness_doctor.diagnose(root)['valid'])
                runtime = runtime_fixtures.valid_plan(root, manifest)
                self.assertTrue(validate_runtime_plan.validate_runtime_plan(root, runtime)['valid'])
                application = apply.build_application(root, plan)
                self.assertEqual(preserved_state(root), before)
                result = apply.apply_application(application)
                self.assertEqual(result['writes'], 0 if version == harness_metadata.HARNESS_VERSION else 1)
                updated = preserved_state(root)
                self.assertEqual(apply.apply_application(apply.build_application(root, plan))['writes'], 0)
                self.assertEqual(preserved_state(root), updated)
                for artifact in plan['artifacts']:
                    self.assertEqual((root / artifact['path']).read_text(encoding='utf-8'), artifact['content'])

    def test_previous_manifest_and_plan_remain_usable_through_public_clis(self):
        for git_root in (False, True):
            if git_root and shutil.which('git') is None:
                continue
            with self.subTest(git_root=git_root), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                root = base / 'project'
                root.mkdir()
                if git_root:
                    subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
                plan = previous_plan(root)
                self.assert_unadvised(plan)
                apply.apply_application(apply.build_application(root, plan))
                manifest = set_metadata(root, '9.0', 2)
                plan_path = base / 'plan.json'
                plan_path.write_text(json.dumps(plan), encoding='utf-8')
                runtime_path = base / 'runtime.json'
                runtime_path.write_text(json.dumps(runtime_fixtures.valid_plan(root, manifest)), encoding='utf-8')
                self.assertEqual(self.invoke('validate_harness.py', [root], root)['installationStatus'], 'valid')
                self.assertEqual(self.invoke('harness_doctor.py', ['--root', root], root)['installationStatus'], 'valid')
                self.assertTrue(self.invoke('validate_runtime_plan.py', ['--root', root, '--plan', runtime_path], root)['valid'])
                args = ['--root', root, '--plan', plan_path]
                self.assertTrue(self.invoke('harness_apply.py', [*args, '--dry-run'], root)['valid'])
                self.assertEqual(self.invoke('harness_apply.py', args, root, readonly=False)['transaction']['writes'], 1)
                self.assertEqual(json.loads((root / '.harness/manifest.json').read_text(encoding='utf-8'))['generator']['version'], harness_metadata.HARNESS_VERSION)
                self.assertEqual(self.invoke('harness_apply.py', args, root)['transaction']['writes'], 0)

    def test_compatibility_does_not_overwrite_modified_previous_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'project'
            plan = previous_plan(root)
            apply.apply_application(apply.build_application(root, plan))
            set_metadata(root, '9.0', 2)
            with (root / '.codex/agents/api_producer.toml').open('a', encoding='utf-8') as handle:
                handle.write('\n# External user edit\n')
            before = preserved_state(root)
            with self.assertRaises(apply.PlanError):
                apply.build_application(root, plan)
            self.assertEqual(validate_harness.Validator(root).run()['installationStatus'], 'invalid')
            self.assertFalse(harness_doctor.diagnose(root)['valid'])
            self.assertEqual(preserved_state(root), before)
            plan_path = base / 'plan.json'
            plan_path.write_text(json.dumps(plan), encoding='utf-8')
            for extra in (['--dry-run'], []):
                report = self.invoke('harness_apply.py', ['--root', root, '--plan', plan_path, *extra], root, expected=2)
                self.assertFalse(report['valid'])

    def test_compatibility_is_explicit_not_a_future_v9_version_range(self):
        self.assertEqual(harness_metadata.ARTIFACT_COMPATIBLE_GENERATOR_VERSIONS, {'9.0', '9.1', '9.2', '9.3', '9.4', '9.5', '9.6', '9.7', '9.8'})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = previous_plan(root)
            apply.apply_application(apply.build_application(root, plan))
            set_metadata(root, '9.9', 2)
            before = preserved_state(root)
            self.assertEqual(validate_harness.Validator(root).run()['installationStatus'], 'invalid')
            with self.assertRaisesRegex(apply.PlanError, 'compatibility'):
                apply.build_application(root, plan)
            self.assertEqual(preserved_state(root), before)


if __name__ == '__main__':
    unittest.main()
