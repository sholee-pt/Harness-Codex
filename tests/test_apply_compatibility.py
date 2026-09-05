"""Exercise the installed-contract boundary through both APIs and real CLIs."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_generated_contracts import coordinated, legacy_installation, snapshot
from test_harness_tools import minimal_plan
import test_runtime_teamplay as runtime_fixtures
import harness_apply as apply
import harness_doctor
import harness_metadata as metadata
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


def preserved_state(root):
    # Includes Git info/exclude and every journal/staging file, plus empty dirs.
    return snapshot(root), sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_dir())


class ApplyCompatibilityTests(unittest.TestCase):
    def test_known_artifact_versions_remain_valid_and_upgrade_without_rewriting_on_repeat(self):
        for version in ('8.0', metadata.HARNESS_VERSION):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = coordinated(root)
                apply.apply_application(apply.build_application(root, plan))
                manifest = set_metadata(root, version, 1)
                before = preserved_state(root)
                self.assertTrue(validate_harness.Validator(root).run()['valid'])
                self.assertTrue(harness_doctor.diagnose(root)['valid'])
                runtime = runtime_fixtures.valid_plan(root, manifest)
                self.assertTrue(validate_runtime_plan.validate_runtime_plan(root, runtime)['valid'])
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

    def test_supported_previous_release_still_preserves_user_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = coordinated(root)
            apply.apply_application(apply.build_application(root, plan))
            set_metadata(root, '8.0', 1)
            path = root / plan['topology']['agents'][0]['path']
            with path.open('a', encoding='utf-8') as handle:
                handle.write('\n# User edit\n')
            before = preserved_state(root)
            with self.assertRaisesRegex(apply.PlanError, 'managed file'):
                apply.build_application(root, plan)
            self.assertEqual(preserved_state(root), before)


if __name__ == '__main__':
    unittest.main()
