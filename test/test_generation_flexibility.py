"""Allow supported project layouts and ordered work without weakening ownership."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from test_harness_tools import (
    harness_apply, harness_state, harness_topology, harness_transaction,
    minimal_plan, validate_harness,
)
from test_runtime_teamplay import valid_plan, write_manifest, runtime_plan

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harness_cli import lifecycle


class InstructionOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fallback(self):
        (self.root / '.codex').mkdir()
        (self.root / '.codex/config.toml').write_text('project_doc_fallback_filenames = ["PROJECT_GUIDE.md"]\n', encoding='utf-8')
        path = self.root / 'PROJECT_GUIDE.md'
        path.write_bytes(b'# User instructions\r\nPreserve these bytes.')
        return path

    def instruction_plan(self, filename):
        plan = minimal_plan(self.root)
        entry = plan['project']['evidence'][0]
        content = (self.root / filename).read_bytes()
        entry.update(path=filename, sha256=harness_state.digest_bytes(content))
        entry['lines'] = {'start': 1, 'end': 2}
        plan['topology']['boundaries'][0]['readScopes'] = [filename]
        return plan

    def test_fallback_apply_validate_update_and_remove_preserve_user_bytes(self):
        path = self.fallback()
        original = path.read_bytes()
        plan = self.instruction_plan(path.name)
        app = harness_apply.build_application(self.root, plan)
        self.assertTrue(app['report']['valid'])
        self.assertEqual(app['instructionRelative'], path.name)
        harness_apply.apply_application(app)
        self.assertTrue(validate_harness.Validator(self.root).run()['valid'])
        self.assertEqual(harness_apply.apply_application(harness_apply.build_application(self.root, plan))['writes'], 0)
        plan['artifacts'][0]['content'] += '\nA reviewed routing clarification.\n'
        harness_apply.apply_application(harness_apply.build_application(self.root, plan))
        self.assertTrue(validate_harness.Validator(self.root).run()['valid'])
        result = lifecycle.remove_project(self.root, source_root=REPO, dry_run=False)
        self.assertEqual(result['state'], 'removed')
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue((self.root / '.codex/config.toml').is_file())

    def test_fallback_transaction_rollback_preserves_original_instruction(self):
        path = self.fallback()
        original = path.read_bytes()
        app = harness_apply.build_application(self.root, minimal_plan(self.root))
        write = harness_state.atomic_write_bytes
        def interrupt(target, content, **kwargs):
            if target == self.root / '.harness/manifest.json':
                raise OSError('injected manifest write interruption')
            return write(target, content, **kwargs)
        with mock.patch.object(harness_state, 'atomic_write_bytes', side_effect=interrupt):
            with self.assertRaisesRegex(harness_transaction.TransactionError, 'rolled back'):
                harness_apply.apply_application(app)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.root / '.harness/transaction.json').exists())

    def test_fallback_removal_recovery_retains_user_instruction(self):
        path = self.fallback()
        original = path.read_bytes()
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))
        with mock.patch.object(lifecycle, '_cleanup', side_effect=OSError('injected cleanup interruption')):
            result = lifecycle.remove_project(self.root, source_root=REPO, dry_run=False)
        self.assertEqual(result['state'], 'removed-cleanup-required')
        lifecycle.recover_removal(self.root, source_root=REPO, dry_run=False)
        self.assertEqual(path.read_bytes(), original)

    def test_instruction_evidence_survives_pointer_changes_but_detects_user_edits(self):
        path = self.root / 'AGENTS.md'
        original = b'# User policy\r\nRun project tests.'
        path.write_bytes(original)
        plan = self.instruction_plan(path.name)
        harness_apply.apply_application(harness_apply.build_application(self.root, plan))
        report = validate_harness.Validator(self.root).run()
        self.assertTrue(report['valid'], report['errors'])
        captured = harness_state.evidence_data(self.root, [path.name])['evidence'][0]
        self.assertEqual(captured['contentScope'], 'instruction-user-content')
        self.assertEqual(captured['sha256'], harness_state.digest_bytes(original))
        self.assertEqual(harness_apply.apply_application(harness_apply.build_application(self.root, plan))['writes'], 0)
        path.write_bytes(path.read_bytes().replace(b'Run project tests.', b'Run reviewed project tests.'))
        report = validate_harness.Validator(self.root).run()
        self.assertEqual(report['validationLayers']['evidenceFreshness']['status'], 'failed')
        self.assertTrue(report['managedIntegrityValid'])
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            harness_apply.build_application(self.root, plan)

    def test_scoped_evidence_does_not_allow_other_files_or_empty_user_content(self):
        plan = minimal_plan(self.root)
        plan['project']['evidence'][0]['contentScope'] = 'instruction-user-content'
        with self.assertRaisesRegex(ValueError, 'configured root instruction'):
            harness_apply.build_application(self.root, plan)
        plan['project']['evidence'][0]['contentScope'] = None
        with self.assertRaisesRegex(ValueError, 'unsupported evidence contentScope'):
            harness_apply.build_application(self.root, plan)
        (self.root / 'AGENTS.md').write_text('<!-- harness:begin --><!-- harness:end -->\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'nonempty user content'):
            harness_state.evidence_data(self.root, ['AGENTS.md'])

    def test_unconfigured_root_file_and_whole_fallback_ownership_are_refused(self):
        self.assertFalse(harness_transaction.is_allowed_target('README.md', root=self.root))
        path = self.fallback()
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))
        manifest_path = self.root / '.harness/manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        entry = next(item for item in manifest['managedFiles'] if item['path'] == path.name)
        entry.update(kind='file', sha256=harness_state.digest_bytes(path.read_bytes()), mode='0644')
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'managed-block ownership'):
            harness_apply.existing_manifest_state(self.root)
        self.assertFalse(validate_harness.Validator(self.root).run()['valid'])


    def test_paired_snapshot_preserves_scoped_instruction_evidence_in_both_arms(self):
        from test_harness_evaluation import PairedIsolationTests, harness_eval
        parent = self.root / 'evaluation'
        source, commit = PairedIsolationTests._local_only_repository(parent)
        path = source / 'AGENTS.md'
        original = b'# User policy\r\nRun the existing project checks.'
        path.write_bytes(original + path.read_bytes().rstrip(b'\n'))
        plan = minimal_plan(source)
        plan['project']['evidence'][0].update(harness_state.evidence_data(source, ['AGENTS.md'])['evidence'][0])
        plan['topology']['boundaries'][0]['readScopes'] = ['AGENTS.md']
        harness_apply.apply_application(harness_apply.build_application(source, plan))
        snapshot = harness_eval._capture_local_harness_snapshot(source, commit)
        self.assertNotIn('AGENTS.md', {item['path'] for item in snapshot['evidenceFiles']})
        baseline, treatment = parent / 'baseline', parent / 'treatment'
        harness_eval._clone_local_evaluation_arm(source, baseline, commit)
        harness_eval._clone_local_evaluation_arm(source, treatment, commit)
        harness_eval._materialize_paired_arms(baseline, treatment, snapshot)
        self.assertEqual((baseline / 'AGENTS.md').read_bytes(), original)
        self.assertEqual(harness_state.instruction_user_content((treatment / 'AGENTS.md').read_bytes()), original)
        self.assertTrue(validate_harness.Validator(treatment).run()['valid'])


class OrderedWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = write_manifest(self.root)

    def chain(self):
        plan = valid_plan(self.root, self.manifest)
        plan['execution'].update({'class': 'delegated', 'pattern': 'pipeline', 'evidenceStatus': 'provisional', 'persistenceAllowed': False})
        plan['participants'] = [{'runtimeParticipantId': f'writer-{letter}', 'runtimeRole': 'producer', 'boundaryRefs': [],
            'readScopes': ['shared/**'], 'writeScopes': ['shared/**']} for letter in 'abc']
        plan['tasks'] = [{'id': f'task-{letter}', 'owner': f'writer-{letter}',
            'dependsOn': [] if index == 0 else [f'task-{"abc"[index-1]}'], 'inputs': ['shared/**'],
            'outputs': [f'output-{letter}'], 'required': True, 'verification': ['Verify current content.']}
            for index, letter in enumerate('abc')]
        plan['handoffs'] = [{'fromTask': f'task-{source}', 'toTask': f'task-{target}', 'scope': 'shared/**',
            'frozenSha256': letter * 64, 'verification': 'Verify the current frozen content.'}
            for source, target, letter in [('a', 'b', 'a'), ('b', 'c', 'b')]]
        return plan

    def test_single_direct_writer_and_ordered_chain_need_no_isolation_labels(self):
        plan = valid_plan(self.root, self.manifest)
        plan['execution'].update({'class': 'direct', 'pattern': None})
        plan['participants'] = plan['participants'][:1]
        plan['participants'][0].pop('isolation')
        plan['tasks'] = plan['tasks'][:1]
        self.assertTrue(runtime_plan.validate_runtime_plan(self.root, plan)['valid'])
        self.assertTrue(runtime_plan.validate_runtime_plan(self.root, self.chain())['valid'])

    def test_handoff_chain_requires_all_links_and_complete_shared_scope(self):
        plan = self.chain()
        plan['handoffs'].pop()
        with self.assertRaisesRegex(ValueError, 'complete verified handoff'):
            runtime_plan.validate_runtime_plan(self.root, plan)
        plan = self.chain()
        plan['handoffs'][1]['scope'] = 'shared/narrow/**'
        with self.assertRaisesRegex(ValueError, 'complete verified handoff'):
            runtime_plan.validate_runtime_plan(self.root, plan)

    def test_parallel_disjoint_writers_still_require_isolation(self):
        plan = self.chain()
        plan['handoffs'] = []
        for index, task in enumerate(plan['tasks']):
            task['dependsOn'] = []
            task['inputs'] = [f'part-{index}/**']
            plan['participants'][index]['readScopes'] = [f'part-{index}/**']
            plan['participants'][index]['writeScopes'] = [f'part-{index}/**']
        with self.assertRaisesRegex(ValueError, 'parallel runtime writers require an isolated worktree'):
            runtime_plan.validate_runtime_plan(self.root, plan)
        for participant in plan['participants']:
            participant['isolation'] = 'equivalent'
        self.assertTrue(runtime_plan.validate_runtime_plan(self.root, plan)['valid'])
        plan['participants'][1]['writeScopes'] = plan['participants'][0]['writeScopes']
        with self.assertRaisesRegex(ValueError, 'concurrent runtime writers'):
            runtime_plan.validate_runtime_plan(self.root, plan)

    def test_persistent_handoff_chain_accepts_adjacent_transfers_only(self):
        plan = minimal_plan(self.root)
        topology = plan['topology']
        topology['boundaries'][0]['writeScopes'] = ['shared/**']
        topology['executionPhases'] = [{'id': f'phase-{letter}', 'order': index,
            'concurrencyGroups': [{'id': 'single', 'order': 0}]} for index, letter in enumerate('abc')]
        topology['agents'] = [{'name': f'writer_{letter}', 'scope': 'boundary', 'boundaryRefs': ['project-core'],
            'fileAccess': [{'scope': 'shared/**', 'mode': 'write', 'phase': f'phase-{letter}', 'concurrencyGroup': 'single'}]}
            for letter in 'abc']
        topology['handoffs'] = [{'fromAgent': f'writer_{source}', 'toAgent': f'writer_{target}', 'scope': 'shared/**',
            'fromPhase': f'phase-{source}', 'fromConcurrencyGroup': 'single', 'toPhase': f'phase-{target}',
            'toConcurrencyGroup': 'single', 'precondition': 'The previous writer has stopped.',
            'verification': 'Verify current frozen content.'} for source, target in [('a', 'b'), ('b', 'c')]]
        self.assertEqual(harness_topology.validate_contract(topology, plan['capabilityPolicies']), [])
        topology['handoffs'][1]['scope'] = 'shared/narrow/**'
        with self.assertRaisesRegex(ValueError, 'complete overlapping scope'):
            harness_topology.validate_contract(topology, plan['capabilityPolicies'])


if __name__ == '__main__':
    unittest.main()
