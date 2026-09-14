"""Exercise the installed-contract boundary through both APIs and real CLIs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

from test_generated_contracts import coordinated, legacy_installation, snapshot, write_and_reseal
import harness_agent_contract
from test_harness_tools import minimal_plan
import test_runtime_teamplay as runtime_fixtures
import harness_apply as apply
import harness_doctor
import harness_git_policy
import harness_teamplay
import harness_metadata as metadata
import harness_state
import validate_harness
import validate_runtime_plan

SCRIPTS = Path(__file__).resolve().parents[1] / '.agents/skills/harness/scripts'
MISSING = object()
UNSUPPORTED = [
    ('future-contract', '9.0', 99),
    ('unknown-release', '8.2', 1),
    ('current-missing', metadata.HARNESS_VERSION, MISSING),
    ('previous-missing', '8.0', MISSING),
    ('current-unknown', metadata.HARNESS_VERSION, 99),
    ('previous-unknown', '8.0', 99),
    ('null', metadata.HARNESS_VERSION, None),
    ('boolean', metadata.HARNESS_VERSION, True),
    ('float', metadata.HARNESS_VERSION, 1.0),
    ('string', metadata.HARNESS_VERSION, '1'),
    ('zero', metadata.HARNESS_VERSION, 0),
    ('array', metadata.HARNESS_VERSION, []),
    ('object', metadata.HARNESS_VERSION, {}),
    ('legacy-current-marker', '7.6', 1),
    ('legacy-null-marker', '7.6', None),
    ('unknown-legacy', '7.7', MISSING),
    ('non-string-release', [], 1),
]


def set_metadata(root, version, contract):
    path = root / '.harness/manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['generator']['version'] = version
    if contract is MISSING:
        manifest.pop('artifactContractVersion', None)
    else:
        manifest['artifactContractVersion'] = contract
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    return manifest


def previous_workspace(root, manifest):
    manifest['schemaVersion'] = 6
    manifest['workspace']['scope'] = 'local-only'
    manifest['workspace']['gitProtection'] = {'mode': 'not-applicable', 'patterns': []}
    (root / '.harness/manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def preserved_state(root):
    # Includes Git info/exclude and every journal/staging file, plus empty dirs.
    return snapshot(root), sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_dir())


class ApplyCompatibilityTests(unittest.TestCase):
    def test_old_schema_cannot_carry_unsupported_owned_paths_into_current_manifest(self):
        for schema in (4, 5):
            with self.subTest(schema=schema), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = minimal_plan(root)
                apply.apply_application(apply.build_application(root, plan))
                path = root / '.harness/manifest.json'
                manifest = json.loads(path.read_text(encoding='utf-8'))
                manifest['schemaVersion'] = schema
                unmanaged = root / 'legacy.txt'
                unmanaged.write_text('legacy', encoding='utf-8')
                manifest['managedFiles'].append({'path': 'legacy.txt', 'kind': 'file', 'mode': '0644', 'sha256': harness_state.digest_bytes(unmanaged.read_bytes())})
                path.write_text(json.dumps(manifest), encoding='utf-8')
                before = preserved_state(root)
                with self.assertRaisesRegex(apply.PlanError, 'cannot enter project artifact ownership'):
                    apply.build_application(root, plan)
                self.assertEqual(preserved_state(root), before)

    def test_output_links_cannot_redirect_writes_into_git_metadata(self):
        for relative in ('.agents', '.harness'):
            for late_change in (False, True):
                with self.subTest(path=relative, late_change=late_change), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    metadata_root = root / '.git'
                    metadata_root.mkdir()
                    (metadata_root / 'config').write_text('fixture', encoding='utf-8')
                    plan = minimal_plan(root)
                    application = apply.build_application(root, plan) if late_change else None
                    link = root / relative
                    if os.name == 'nt':
                        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
                        subprocess.run(['powershell', '-NoProfile', '-Command', f'New-Item -ItemType Junction -Path {quote(link)} -Target {quote(metadata_root)} | Out-Null'], check=True, capture_output=True)
                    else:
                        link.symlink_to(metadata_root, target_is_directory=True)
                    try:
                        before = snapshot(metadata_root)
                        with self.assertRaises((apply.PlanError, harness_state.StateError)):
                            if late_change:
                                apply.apply_application(application)
                            else:
                                apply.build_application(root, plan)
                        self.assertEqual(snapshot(metadata_root), before)
                    finally:
                        if os.name == 'nt':
                            link.rmdir()
                        else:
                            link.unlink()

    def test_malformed_workspace_metadata_is_invalid_and_never_repaired_by_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            apply.apply_application(apply.build_application(root, plan))
            path = root / '.harness/manifest.json'
            original = path.read_text(encoding='utf-8')
            for field in ('kind', 'scope', 'instructionMode'):
                for value in (None, [], {}, 'unsupported-kind'):
                    with self.subTest(field=field, value=value):
                        manifest = json.loads(original)
                        manifest['workspace'][field] = value
                        path.write_text(json.dumps(manifest), encoding='utf-8')
                        before = preserved_state(root)
                        self.assertEqual(validate_harness.Validator(root).run()['installationStatus'], 'invalid')
                        self.assertFalse(harness_doctor.diagnose(root)['valid'])
                        with self.assertRaises(apply.PlanError):
                            apply.build_application(root, plan)
                        self.assertEqual(preserved_state(root), before)

    def test_generator_and_nested_git_metadata_are_not_project_artifact_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ('.agents/skills/harness/scripts/extra.py', '.agents/skills/extra/.git/config'):
                plan = minimal_plan(root)
                plan['artifacts'].append({'path': relative, 'content': 'x', 'mode': '0644'})
                before = preserved_state(root)
                with self.assertRaisesRegex(apply.PlanError, 'supported Codex Harness target'):
                    apply.build_application(root, plan)
                self.assertEqual(preserved_state(root), before)

    def test_known_artifact_versions_remain_valid_and_upgrade_without_rewriting_on_repeat(self):
        for version in ('8.0', '8.1', metadata.HARNESS_VERSION):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = coordinated(root)
                apply.apply_application(apply.build_application(root, plan))
                manifest = set_metadata(root, version, metadata.ARTIFACT_CONTRACT_VERSION if version == metadata.HARNESS_VERSION else 1)
                if version != metadata.HARNESS_VERSION:
                    manifest = previous_workspace(root, manifest)
                before = preserved_state(root)
                report = validate_harness.Validator(root).run()
                self.assertEqual(report['installationStatus'], 'valid' if version == metadata.HARNESS_VERSION else 'upgrade-required')
                self.assertTrue(report['integrityValid'])
                self.assertEqual(harness_doctor.diagnose(root)['valid'], version == metadata.HARNESS_VERSION)
                runtime = runtime_fixtures.valid_plan(root, manifest)
                if version == metadata.HARNESS_VERSION:
                    self.assertTrue(validate_runtime_plan.validate_runtime_plan(root, runtime)['valid'])
                else:
                    with self.assertRaises(validate_runtime_plan.RuntimePlanError):
                        validate_runtime_plan.validate_runtime_plan(root, runtime)
                application = apply.build_application(root, plan)
                self.assertEqual(preserved_state(root), before)
                applied = apply.apply_application(application)
                self.assertEqual(applied['writes'], 1 if version != metadata.HARNESS_VERSION else 0)
                current = json.loads((root / '.harness/manifest.json').read_text())
                self.assertEqual(current['generator']['version'], metadata.HARNESS_VERSION)
                after = preserved_state(root)
                self.assertEqual(apply.apply_application(apply.build_application(root, plan))['writes'], 0)
                self.assertEqual(preserved_state(root), after)

    def test_unsupported_installed_versions_fail_before_application_is_created(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = coordinated(root)
            apply.apply_application(apply.build_application(root, plan))
            for label, version, marker in UNSUPPORTED:
                with self.subTest(case=label):
                    manifest = set_metadata(root, version, marker)
                    before = preserved_state(root)
                    self.assertEqual(validate_harness.Validator(root).run()['installationStatus'], 'invalid')
                    self.assertFalse(harness_doctor.diagnose(root)['valid'])
                    runtime = runtime_fixtures.valid_plan(root, manifest)
                    with self.assertRaises(validate_runtime_plan.RuntimePlanError):
                        validate_runtime_plan.validate_runtime_plan(root, runtime)
                    with self.assertRaisesRegex(apply.PlanError, 'existing manifest artifact compatibility'):
                        apply.build_application(root, plan)
                    self.assertEqual(preserved_state(root), before)

    def test_cli_dry_run_and_apply_reject_unsupported_metadata_without_side_effects(self):
        for git_workspace in (False, True):
            if git_workspace and shutil.which('git') is None:
                continue
            with self.subTest(git_workspace=git_workspace), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                root = base / 'project'
                root.mkdir()
                if git_workspace:
                    subprocess.run(['git', 'init', '-q', str(root)], check=True)
                plan = minimal_plan(root)
                apply.apply_application(apply.build_application(root, plan))
                plan_path = base / 'plan.json'
                plan_path.write_text(json.dumps(plan), encoding='utf-8')
                for label, version, marker in UNSUPPORTED[:4]:
                    set_metadata(root, version, marker)
                    before = preserved_state(root)
                    for extra in (['--dry-run'], []):
                        with self.subTest(case=label, extra=extra):
                            process = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'harness_apply.py'), '--root', str(root), '--plan', str(plan_path), *extra], capture_output=True, text=True, encoding='utf-8')
                            self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                            report = json.loads(process.stdout)
                            self.assertFalse(report['valid'])
                            self.assertIn('existing manifest artifact compatibility', report['error'])
                            self.assertEqual(preserved_state(root), before)

    def test_known_legacy_generation_versions_still_allow_reviewed_upgrade(self):
        for minor in range(7):
            with self.subTest(version=f'7.{minor}'), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = minimal_plan(root)
                legacy_installation(root, plan)
                # The artifacts are a contract-equivalent synthetic legacy fixture.
                set_metadata(root, f'7.{minor}', MISSING)
                self.assertEqual(validate_harness.Validator(root).run()['installationStatus'], 'upgrade-required')
                application = apply.build_application(root, plan)
                apply.apply_application(application)
                self.assertTrue(validate_harness.Validator(root).run()['valid'])

    def test_previous_workspace_cannot_hide_missing_agent_contract_as_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = coordinated(root)
            apply.apply_application(apply.build_application(root, plan))
            previous_workspace(root, set_metadata(root, '8.1', 1))
            agent = plan['topology']['agents'][0]
            path = agent['path']
            text = (root / path).read_text(encoding='utf-8')
            instructions = tomllib.loads(text)['developer_instructions']
            instructions = instructions.replace(harness_agent_contract.render(agent, plan['topology']), '')
            text = harness_agent_contract.replace_instructions(text, instructions)
            write_and_reseal(root, path, text)
            before = preserved_state(root)
            self.assertEqual(validate_harness.Validator(root).run()['installationStatus'], 'invalid')
            with self.assertRaisesRegex(apply.PlanError, 'agent contract'):
                apply.build_application(root, plan)
            self.assertEqual(preserved_state(root), before)

    def test_supported_previous_release_still_preserves_user_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = coordinated(root)
            apply.apply_application(apply.build_application(root, plan))
            previous_workspace(root, set_metadata(root, '8.0', 1))
            path = root / plan['topology']['agents'][0]['path']
            with path.open('a', encoding='utf-8') as handle:
                handle.write('\n# User edit\n')
            before = preserved_state(root)
            with self.assertRaisesRegex(apply.PlanError, 'managed file'):
                apply.build_application(root, plan)
            self.assertEqual(preserved_state(root), before)


def previous_plan(root):
    """Build existing canonical contracts without invoking the new materializer."""
    shutil.copytree(SCRIPTS.parents[3] / 'test/fixtures/coordinated-cross-contract', root, dirs_exist_ok=True)
    plan = json.loads((SCRIPTS.parents[3] / 'test/fixtures/coordinated-cross-contract-plan.json').read_text(encoding='utf-8'))
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
                self.assertEqual(result['writes'], 0 if version == metadata.HARNESS_VERSION else 1)
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
                self.assertEqual(json.loads((root / '.harness/manifest.json').read_text(encoding='utf-8'))['generator']['version'], metadata.HARNESS_VERSION)
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
        self.assertEqual(metadata.ARTIFACT_COMPATIBLE_GENERATOR_VERSIONS, {*(f'9.{p}' for p in range(12)), *(f'0.9.{p}-beta' for p in range(12)), '0.10.0-beta', '0.11.0-beta', '0.12.0-beta', '0.13.0-beta', '0.13.1-beta', metadata.HARNESS_VERSION})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = previous_plan(root)
            apply.apply_application(apply.build_application(root, plan))
            set_metadata(root, '9.9999', 2)
            before = preserved_state(root)
            self.assertEqual(validate_harness.Validator(root).run()['installationStatus'], 'invalid')
            with self.assertRaisesRegex(apply.PlanError, 'compatibility'):
                apply.build_application(root, plan)
            self.assertEqual(preserved_state(root), before)


if __name__ == '__main__':
    unittest.main()
