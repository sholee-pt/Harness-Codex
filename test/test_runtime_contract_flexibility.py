"""Runtime contracts preserve scope safety without rejecting legitimate tasks."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import test_runtime_teamplay as fixtures
import test_runtime_receipt_v2 as receipts
from test_harness_tools import harness_apply, harness_plan_builder, minimal_plan, validate_harness

plan_tools = fixtures.runtime_plan
teamplay = fixtures.harness_teamplay
receipt_tools = receipts.receipt2
relay = fixtures.harness_relay_receipt


class RuntimeContractFlexibilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.plan = fixtures.valid_plan(self.root, fixtures.write_manifest(self.root))

    def receipt(self, plan=None, **overrides):
        plan = plan or self.plan
        arguments = dict(plan=plan, lines=receipts.public_core_lines(),
                         public_profile_id=receipt_tools.PUBLIC_CORE_PROFILE,
                         control_plane=receipts.control_plane_report(plan), observation_bindings=None,
                         codex_cli_version='test-native', execution_mode='ephemeral',
                         repository_id='repo-' + 'a' * 16, harness_commit='b' * 40,
                         salt=b'bounded-test-salt')
        arguments.update(overrides)
        return receipt_tools.build_runtime_receipt(**arguments)

    def test_runtime_api_names_are_ordinary_project_subjects(self):
        self.plan['task']['summary'] = 'Review spawn_agent and TeamCreate API implementations.'
        self.plan['tasks'][0]['verification'] = ['Check collaboration.send_message behavior.']
        self.assertTrue(plan_tools.validate_runtime_plan(self.root, self.plan)['valid'])
        self.plan['execution']['adapter'] = 'spawn_agent'
        with self.assertRaisesRegex(plan_tools.RuntimePlanError, 'runtime-specific'):
            plan_tools.validate_runtime_plan(self.root, self.plan)

    def test_scout_cannot_acquire_write_scopes(self):
        self.plan['participants'][0]['runtimeRole'] = 'scout'
        with self.assertRaisesRegex(plan_tools.RuntimePlanError, 'read-only'):
            plan_tools.validate_runtime_plan(self.root, self.plan)

    def shared_plan(self):
        self.plan['execution'].update(evidenceStatus='provisional', persistenceAllowed=False)
        self.plan['execution']['sharedWorkspace'] = {
            'explicitSelection': True, 'writePolicy': 'disjoint-scopes',
            'sharedStateOwner': 'primary', 'verification': 'after-writers-quiescent',
        }
        other = self.plan['participants'][1]
        other.pop('agent')
        other.update(runtimeParticipantId='second-writer', runtimeRole='producer',
                     readScopes=['contracts/storage.schema'], writeScopes=['contracts/storage.schema'])
        for participant in self.plan['participants']:
            participant['isolation'] = 'shared-workspace'
        self.plan['tasks'][1].update(owner='second-writer', dependsOn=[], inputs=['contracts/storage.schema'])
        return self.plan

    def test_explicit_shared_writers_require_disjoint_scope_and_stable_inputs(self):
        plan = self.shared_plan()
        self.assertTrue(plan_tools.validate_runtime_plan(self.root, plan)['valid'])
        for mutation in ('missing-contract', 'overlap', 'cross-read', 'false-selection', 'numeric-selection'):
            candidate = copy.deepcopy(plan)
            if mutation == 'missing-contract':
                candidate['execution'].pop('sharedWorkspace')
            elif mutation == 'overlap':
                candidate['participants'][1]['writeScopes'] = ['contracts/api.schema']
            elif mutation == 'cross-read':
                candidate['participants'][1]['readScopes'].append('contracts/api.schema')
            else:
                candidate['execution']['sharedWorkspace']['explicitSelection'] = False if mutation == 'false-selection' else 1
            with self.subTest(mutation=mutation), self.assertRaises(plan_tools.RuntimePlanError):
                plan_tools.validate_runtime_plan(self.root, candidate)

    def test_serial_shared_input_is_allowed_after_dependency(self):
        plan = self.shared_plan()
        plan['participants'][1]['readScopes'].append('contracts/api.schema')
        plan['tasks'][1]['dependsOn'] = ['prepare-change']
        self.assertTrue(plan_tools.validate_runtime_plan(self.root, plan)['valid'])

    def test_past_receipt_release_is_provenance_not_a_validation_gate(self):
        receipt = self.receipt()
        receipt['harness']['version'] = '0.32.4-beta'
        receipt['runtime']['waitPolicy'] = dict(receipt_tools.LEGACY_WAIT_POLICY)
        receipt.pop('integrity')
        receipt['integrity'] = {'algorithm': 'sha256', 'canonicalSha256': receipt_tools.digest(receipt)}
        before = json.dumps(receipt, sort_keys=True)
        self.assertTrue(receipt_tools.validate_runtime_receipt(receipt)['valid'])
        self.assertEqual(json.dumps(receipt, sort_keys=True), before)
        receipt['parser']['schemaVersion'] = 99
        with self.assertRaisesRegex(receipt_tools.RuntimeReceiptError, 'parser metadata'):
            receipt_tools.validate_runtime_receipt(receipt)

    def test_provisional_native_role_mapping_preserves_real_binding_conflicts(self):
        self.plan['execution'].update(evidenceStatus='provisional', persistenceAllowed=False)
        self.plan['participants'][0].pop('agent')
        self.plan['participants'][0].update(runtimeParticipantId='temporary-producer', nativeAgentRole='default')
        self.plan['tasks'][0]['owner'] = 'temporary-producer'
        self.assertTrue(plan_tools.validate_runtime_plan(self.root, self.plan)['valid'])
        control = receipts.control_plane_report(self.plan)
        bindings = receipts.local_bindings(self.plan, control, role_overrides={'temporary-producer': 'default'})
        result = self.receipt(control_plane=control, observation_bindings=bindings)
        self.assertTrue(result['agents'][0]['sessionBound'])
        self.assertFalse(result['agents'][0]['failed'])
        for field, value in (('agentRole', 'other-role'), ('parentThreadId', 'other-parent'),
                             ('spawnInstanceId', 'other-spawn')):
            wrong = copy.deepcopy(bindings)
            wrong['children'][0][field] = value
            result = self.receipt(control_plane=control, observation_bindings=wrong)
            self.assertIn('binding-conflict', result['agents'][0]['failureCodes'])
        self.plan['participants'][0].pop('nativeAgentRole')
        result = self.receipt(control_plane=control, observation_bindings=bindings,
                              local_lines=receipts.local_activity_lines(self.plan),
                              local_profile_id=receipt_tools.LOCAL_SUBAGENT_PROFILE)
        self.assertFalse(result['agents'][0]['sessionBound'])
        self.assertTrue(result['agents'][0]['completed'])
        self.assertFalse(result['agents'][0]['failed'])

    def test_optional_surface_extension_does_not_fabricate_terminal_failure(self):
        result = self.receipt(lines=receipts.public_collab_lines(self.plan))
        self.assertEqual(result['eventProfiles'][0]['compatibility'], 'degraded')
        self.assertTrue(result['provesLiveSubagentExecution'])
        self.assertTrue(all(agent['completed'] and not agent['failed'] for agent in result['agents']))

    def test_unregistered_profile_cannot_invent_binding_or_terminal_conflicts(self):
        lines = [json.dumps({'type': 'thread.started', 'thread_id': 'other-parent'}),
                 json.dumps({'type': 'turn.failed'}), json.dumps({'type': 'turn.completed'})]
        control = receipts.control_plane_report(self.plan)
        result = self.receipt(lines=lines, public_profile_id='unknown-profile',
                              observation_bindings=receipts.local_bindings(self.plan, control))
        self.assertEqual(result['eventProfiles'][0]['compatibility'], 'unsupported')
        self.assertFalse(result['runtime']['conflictDetected'])
        self.assertTrue(all(agent['completed'] and not agent['failed'] for agent in result['agents']))

    def lineage_fixture(self):
        plan = self.plan
        plan['execution'].update(evidenceStatus='provisional', persistenceAllowed=False)
        plan['participants'].append({'runtimeParticipantId': 'other-reviewer', 'runtimeRole': 'reviewer',
                                     'boundaryRefs': [], 'readScopes': ['contracts/storage.schema'],
                                     'writeScopes': [], 'isolation': 'read-only'})
        plan['tasks'].append({'id': 'other-review', 'owner': 'other-reviewer', 'dependsOn': [],
                              'inputs': ['contracts/storage.schema'], 'outputs': ['other-findings'],
                              'required': True, 'verification': ['storage-review']})
        self.assertTrue(plan_tools.validate_runtime_plan(self.root, plan)['valid'])
        envelope = fixtures.valid_relay_receipt(plan)
        envelope.pop('integrity')
        envelope['packetRevisions'][1]['affectedAgents'].append('api_producer')
        envelope['reruns'][0]['agents'].append('api_producer')
        envelope['reviews'].append({'reviewId': 'other-r0', 'taskId': 'other-review',
                                    'participant': 'other-reviewer', 'revision': 0,
                                    'inputPacketSha256': 'a' * 64, 'reviewSha256': 'e' * 64, 'status': 'accepted'})
        envelope['integration']['reviewIds'].append('other-r0')
        entries = {}
        by_owner = {participant.get('agent', participant.get('runtimeParticipantId')): participant
                    for participant in plan['participants']}
        for task in plan['tasks']:
            entries[task['id']] = {key: {item: '1' * 64 for item in names} for key, names in
                                  (('inputs', task['inputs']), ('outputs', task['outputs']),
                                   ('readScopes', by_owner[task['owner']]['readScopes']))}
        changed = copy.deepcopy(entries)
        changed['prepare-change']['outputs']['change-proposal'] = '2' * 64
        changed['review-change']['inputs']['change-proposal'] = '2' * 64
        envelope['inputLineage'] = {'contract': 'scoped-inputs-v1', 'revisions': [
            {'revision': 0, 'tasks': entries}, {'revision': 1, 'tasks': changed}]}
        return plan, envelope

    def test_complete_scoped_lineage_reuses_only_unaffected_review(self):
        plan, envelope = self.lineage_fixture()
        self.assertTrue(relay.validate_relay_receipt(relay.seal_relay_receipt(envelope), plan=plan)['valid'])
        envelope.pop('inputLineage')
        with self.assertRaisesRegex(relay.RelayReceiptError, 'stale'):
            relay.validate_relay_receipt(relay.seal_relay_receipt(envelope), plan=plan)

    def test_scoped_lineage_refuses_missing_or_changed_inputs_and_dependencies(self):
        plan, envelope = self.lineage_fixture()
        for mutation in ('missing-task', 'missing-read', 'dependency-mismatch', 'changed-unaffected',
                         'changed-review-output', 'omitted-producer', 'explicitly-affected'):
            candidate = copy.deepcopy(envelope)
            tasks = candidate['inputLineage']['revisions'][1]['tasks']
            if mutation == 'missing-task':
                tasks.pop('other-review')
            elif mutation == 'missing-read':
                tasks['other-review']['readScopes'] = {}
            elif mutation == 'dependency-mismatch':
                tasks['review-change']['inputs']['change-proposal'] = '3' * 64
            elif mutation == 'changed-unaffected':
                tasks['other-review']['inputs']['contracts/storage.schema'] = '3' * 64
                tasks['other-review']['readScopes']['contracts/storage.schema'] = '3' * 64
            elif mutation == 'changed-review-output':
                tasks['other-review']['outputs']['other-findings'] = '3' * 64
            elif mutation == 'omitted-producer':
                candidate['packetRevisions'][1]['affectedAgents'].remove('api_producer')
                candidate['reruns'][0]['agents'].remove('api_producer')
            else:
                candidate['packetRevisions'][1]['affectedAgents'].append('other-reviewer')
                candidate['reruns'][0]['agents'].append('other-reviewer')
            with self.subTest(mutation=mutation), self.assertRaises(relay.RelayReceiptError):
                relay.validate_relay_receipt(relay.seal_relay_receipt(candidate), plan=plan)


class CanonicalCompatibilityTests(unittest.TestCase):
    def test_both_legacy_project_contracts_upgrade_without_losing_user_text(self):
        for previous in (teamplay.LEGACY_PROJECT_BLOCK, teamplay.LEGACY_PROJECT_BLOCK_V3):
            actual = harness_plan_builder._materialize_contract(
                'before\r\n' + previous.replace('\n', '\r\n') + '\r\nafter',
                harness_plan_builder.PROJECT_TEAMPLAY_PLACEHOLDER, teamplay.PROJECT_BLOCK, 'router')
            self.assertEqual(actual, 'before\r\n' + teamplay.PROJECT_BLOCK.replace('\n', '\r\n') + '\r\nafter')
            teamplay.require_exactly_once(previous, teamplay.PROJECT_BLOCK, 'router')
        teamplay.require_exactly_once(teamplay.LEGACY_AGENT_BLOCK, teamplay.AGENT_BLOCK, 'agent')
        with self.assertRaises(teamplay.TeamplayError):
            teamplay.require_exactly_once(teamplay.LEGACY_AGENT_BLOCK + teamplay.AGENT_BLOCK, teamplay.AGENT_BLOCK, 'agent')

    def test_reviewed_router_compaction_preserves_mandatory_permission_and_ownership_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft = minimal_plan(root)
            draft['authoringContractVersion'] = 3
            draft['artifacts'][0]['content'] += '\n\n' + teamplay.PROVISIONAL_GUIDANCE
            plan = harness_plan_builder.materialize_plan(draft, root=root)
            content = plan['artifacts'][0]['content']
            self.assertLess(len(content.encode()), 7600)
            self.assertNotIn(teamplay.PROVISIONAL_GUIDANCE, content)
            self.assertIn('Git authorization', content)
            self.assertIn('권한', content)
            self.assertIn('writer가 정지', content)
            harness_apply.apply_application(harness_apply.build_application(root, plan))
            self.assertTrue(validate_harness.Validator(root).run()['valid'])
            draft = copy.deepcopy(plan); draft['authoringContractVersion'] = 3
            self.assertEqual(harness_plan_builder.materialize_plan(draft, root=root), plan)


if __name__ == '__main__':
    unittest.main()
