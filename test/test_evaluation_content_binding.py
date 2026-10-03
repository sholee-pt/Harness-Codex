"""Configuration attribution groups bind actual owned component bytes, not names alone."""
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from test_harness_evaluation import (
    HASH, compare, harness_apply, harness_eval, persist_completed, propose,
    store_module, types, uuid_text,
    manual_record,
)
from test_harness_tools import minimal_plan


class EvaluationContentBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root, self.plain = self.base / 'project', self.base / 'plain'
        self.root.mkdir()
        self.plain.mkdir()
        self.store = store_module.EvaluationStore(self.base / 'state')
        self.repository_id = self.store.register_repository(self.root)
        self.args = SimpleNamespace(execution_class='direct')
        self.baseline = self.snapshot(self.plain, 'baseline')

    def snapshot(self, root=None, arm='harness'):
        return harness_eval._configuration_snapshot(self.store, self.repository_id, root or self.root, self.args, arm)

    def generate(self, *, body='Run targeted tests.', resource='Check failed assertions.'):
        plan = minimal_plan(self.root)
        skill = copy.deepcopy(plan['topology']['skills'][0])
        skill.update(name='verification-helper', path='.agents/skills/verification-helper/SKILL.md',
                     purpose='Apply repeatable project verification.', scope='boundary', boundaryRefs=['project-core'])
        plan['topology']['skills'].append(skill)
        plan['artifacts'] += [
            {'path': skill['path'], 'mode': '0644', 'content':
             '---\nname: verification-helper\ndescription: Run repeatable project checks.\n---\n\n# Verification\n\n' + body + '\n'},
            {'path': '.agents/skills/verification-helper/references/checks.md', 'mode': '0644', 'content': resource + '\n'},
        ]
        harness_apply.apply_application(harness_apply.build_application(self.root, plan))
        return self.snapshot()

    def bundle(self, snapshot):
        return snapshot['declaredConfiguration']['bundleFingerprint']

    def record(self, index, arm, configuration):
        record = manual_record(self.repository_id, uuid_text(1000 + index * 2 + (arm == 'harness')),
                               arm=arm, pair_id=uuid_text(2000 + index), output_tokens=100 if arm == 'baseline' else 10)
        record['configuration'] = copy.deepcopy(configuration)
        return types.seal_record(record)

    def plan(self, configuration):
        delta, _ = compare._configuration_delta(self.record(0, 'baseline', self.baseline),
                                                self.record(0, 'harness', configuration),
                                                {'intervention': {'expectedChangedFactors': []}})
        return {
            'schemaVersion': 2,
            'primaryOutcome': {'metric': 'output-tokens', 'direction': 'lower-is-better', 'minimumEffect': 1},
            'correctnessGate': 'no-regression', 'secondaryOutcomes': [], 'verificationProfileFingerprint': HASH,
            'intervention': {'expectedChangedFactors': [item['factor'] for item in delta['changedFactors']], 'attributionTarget': 'bundle'},
            'taskStratum': {'category': 'test', 'complexityLevel': 'unknown', 'impactLevel': 'unknown',
                            'uncertaintyLevel': 'unknown', 'scopeClass': 'single-file'},
            'patchScopeProfileFingerprint': None,
        }

    def compare(self, index, configuration, plan, *, baseline=None):
        left = self.record(index, 'baseline', baseline or self.baseline)
        right = self.record(index, 'harness', configuration)
        persist_completed(self.store, left)
        persist_completed(self.store, right)
        return compare.compare_runs(baseline=left, treatment=right, plan=plan,
                                    comparison_id=uuid_text(3000 + index), pair_id=uuid_text(2000 + index),
                                    repository_id=self.repository_id, created_at='2026-08-31T12:02:00Z')

    def eligibility(self, comparisons, plan, **kwargs):
        return harness_eval._proposal_eligibility(evaluation_store=self.store, repository_id=self.repository_id,
            comparisons=comparisons, comparison_plan=plan, task_category='test', complexity_level='unknown',
            impact_level='unknown', **kwargs)

    def test_changed_skill_body_or_managed_resource_changes_bundle_without_inventing_a_factor(self):
        first = self.generate()
        body = self.generate(body='Run full tests and inspect warnings.')
        resource = self.generate(body='Run full tests and inspect warnings.', resource='Also inspect expected exception messages.')
        self.assertEqual(len({self.bundle(snapshot)['value'] for snapshot in (first, body, resource)}), 3)
        plan = self.plan(first)
        left = self.record(0, 'baseline', {**first, 'arm': 'baseline'})
        for snapshot in (body, resource):
            delta, _ = compare._configuration_delta(left, self.record(0, 'harness', snapshot), plan)
            self.assertEqual(delta['changedFactorCount'], 0)
            self.assertEqual(delta['attributionScope'], 'none')
        serialized = json.dumps(resource)
        for text in ('verification-helper', 'Run full tests', 'expected exception', 'references/checks.md'):
            self.assertNotIn(text, serialized)

    def test_distinct_implementations_cannot_pool_strong_support_but_selected_group_keeps_its_pairs(self):
        configurations = [self.generate(), self.generate(body='Run full tests and inspect warnings.')]
        plan = self.plan(configurations[0])
        comparisons = [self.compare(index, configurations[index % 2], plan) for index in range(10)]
        strata = {item['evaluationStratumFingerprint'] for item in comparisons}
        self.assertEqual(len(strata), 2)
        with self.assertRaisesRegex(types.EvaluationError, 'multiple concrete-eligible evaluation strata'):
            self.eligibility(comparisons, plan)
        for stratum in strata:
            selected = self.eligibility(comparisons, plan, evaluation_stratum=stratum)
            self.assertEqual(len(selected.attribution_basis_ids), 5)
            self.assertFalse(selected.excluded_comparison_ids)
        common = [self.compare(10 + index, configurations[0], plan) for index in range(10)]
        eligibility = self.eligibility(common, plan)
        self.assertEqual(len(eligibility.attribution_basis_ids), 10)
        proposal = propose.proposal_from_comparisons(repository_id=self.repository_id, proposal_id=uuid_text(5000),
            created_at='2026-08-31T12:03:00Z', comparisons=common, comparison_plan=plan, eligibility=eligibility)
        self.assertEqual(proposal['proposalType'], 'bundle-proposal')
        self.assertEqual(proposal['evidence']['supportStrength'], 'strong')

    def test_manifest_metadata_order_and_mtime_do_not_split_identical_configuration(self):
        original = self.generate()
        manifest_path = self.root / '.harness/manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['generator']['version'] = '99.0.0-beta'
        manifest['generatedAt'] = '2099-01-01T00:00:00Z'
        manifest['managedFiles'].reverse()
        manifest['topology']['skills'].reverse()
        manifest_path.write_text(json.dumps(manifest, indent=4))
        for path in self.root.rglob('*'):
            if path.is_file():
                os.utime(path, ns=(1_000_000_000, 1_000_000_000))
        updated = self.snapshot()
        self.assertEqual(self.bundle(updated), self.bundle(original))
        plan = self.plan(original)
        self.assertEqual(self.compare(0, original, plan)['evaluationStratumFingerprint'],
                         self.compare(1, updated, plan)['evaluationStratumFingerprint'])

    def test_missing_modified_unreadable_or_oversized_content_is_not_an_empty_bundle(self):
        known = self.generate()
        plan = self.plan(known)
        resource = self.root / '.agents/skills/verification-helper/references/checks.md'
        original = resource.read_bytes()
        for index, failure in enumerate(('missing', 'modified', 'unreadable', 'oversized')):
            with self.subTest(failure=failure):
                resource.write_bytes(original)
                if failure == 'missing':
                    resource.unlink()
                elif failure == 'modified':
                    resource.write_bytes(b'Unreceipted edit')
                read = Path.open
                def opening(path, *args, **kwargs):
                    if failure == 'unreadable' and path == resource:
                        raise PermissionError('fixture inaccessible content')
                    return read(path, *args, **kwargs)
                with mock.patch.object(Path, 'open', opening), mock.patch.object(harness_eval, 'PAIRED_OVERLAY_MAX_BYTES', 8 if failure == 'oversized' else 64 * 1024 * 1024):
                    unknown = self.snapshot()
                self.assertEqual(self.bundle(unknown)['state'], 'unavailable')
                result = self.compare(index, unknown, plan)
                self.assertIn('treatment-configuration-content-unavailable', result['isolationGaps'])
                self.assertFalse(self.eligibility([result], plan).attribution_basis_ids)

    def test_unknown_in_both_arms_and_partial_fingerprint_stay_ineligible(self):
        known = self.generate()
        plan = self.plan(known)
        for index, changes in enumerate(({'state': 'unavailable', 'value': None, 'completeness': 'unknown', 'fidelity': 'unknown', 'source': 'none'},
                                          {'completeness': 'partial'})):
            treatment, baseline = copy.deepcopy(known), copy.deepcopy(self.baseline)
            for configuration in (treatment, baseline):
                configuration['declaredConfiguration']['bundleFingerprint'].update(changes)
            result = self.compare(index, treatment, plan, baseline=baseline)
            self.assertIn('baseline-configuration-content-unavailable', result['isolationGaps'])
            self.assertIn('treatment-configuration-content-unavailable', result['isolationGaps'])
            self.assertFalse(self.eligibility([result], plan).attribution_basis_ids)

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink and mode fixtures')
    def test_symlinks_and_dangling_manifest_ancestors_are_unknown_and_modes_are_bound(self):
        known = self.generate()
        resource = self.root / '.agents/skills/verification-helper/references/checks.md'
        resource.chmod(0o755)
        self.assertNotEqual(self.bundle(known), self.bundle(self.snapshot()))
        resource.unlink()
        resource.symlink_to(self.base / 'absent')
        self.assertEqual(self.bundle(self.snapshot())['state'], 'unavailable')
        (self.plain / '.harness').symlink_to(self.base / 'absent-directory', target_is_directory=True)
        self.assertEqual(self.bundle(self.snapshot(self.plain, 'baseline'))['state'], 'unavailable')

    def test_agent_bytes_are_bound_and_unknown_ownership_is_not_ignored(self):
        known = self.generate()
        manifest_path = self.root / '.harness/manifest.json'
        manifest = json.loads(manifest_path.read_text())
        relative = '.codex/agents/reviewer.toml'
        agent = self.root / relative
        agent.parent.mkdir(parents=True)
        manifest['topology']['agents'] = [{'name': 'reviewer', 'path': relative}]
        for content in (b'name = "reviewer"\ndeveloper_instructions = "Check tests"\n',
                        b'name = "reviewer"\ndeveloper_instructions = "Check failure modes"\n'):
            agent.write_bytes(content)
            manifest['managedFiles'] = [entry for entry in manifest['managedFiles'] if entry['path'] != relative]
            manifest['managedFiles'].append({'path': relative, 'kind': 'file', 'sha256': types.digest_bytes(content), 'mode': '0644'})
            manifest_path.write_text(json.dumps(manifest))
            updated = self.snapshot()
            self.assertEqual(self.bundle(updated)['state'], 'measured')
            self.assertNotEqual(self.bundle(known), self.bundle(updated))
            known = updated
        manifest['managedFiles'] = [entry for entry in manifest['managedFiles'] if entry['path'] != relative]
        manifest_path.write_text(json.dumps(manifest))
        self.assertEqual(self.bundle(self.snapshot())['state'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
