"""Adaptive decisions need attributable observations, not paid exploration or prose."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.agents/skills/harness/scripts'))
import harness_apply
import harness_maintenance as maintenance
import harness_routing_evidence as evidence
from test_harness_tools import minimal_plan
from harness_cli import auto_relay, routing_feedback
from test_official_relay import catalog


class AdaptiveEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))
        self.now = 100000.0
        self.store = self.base / 'state'
        self.manager = evidence.RoutingEvidence(self.root, self.store, clock=lambda: self.now)

    def group(self, **overrides):
        values = {'runtime': 'dynamic-runtime', 'catalog': 'catalog-revision', 'revision': 'harness-revision', 'category': 'implementation', 'tier': 'balanced'}
        values.update(overrides)
        return self.manager.context(**values)

    def populate(self, model, effort, tokens, elapsed, *, outcome='verified', count=24, group=None):
        references = []
        for index in range(count):
            record = self.manager.record('session', model + '-' + str(index), context=group or self.group(), model=model, effort=effort, milliseconds=elapsed, tokens=tokens)
            reference = record['reference']
            references.append(reference)
            if outcome != 'unknown':
                self.manager.feedback(reference, outcome, 'verification', 'inference')
        return references

    def test_disabled_observation_and_status_never_create_state(self):
        self.assertFalse(self.manager.status()['enabled'])
        self.assertFalse(self.manager.record('session', 'turn', context='a' * 64, model='future', effort='adaptive', milliseconds=10, tokens=None)['recorded'])
        self.assertFalse(self.store.exists())

    def test_known_quality_and_cost_can_change_pair_but_not_unknown_or_new_strata(self):
        self.manager.configure(True)
        base, candidate = ('original-model', 'adaptive'), ('new-model', 'future-effort')
        self.populate(*base, 1000, 1000)
        refs = self.populate(*candidate, 100, 100, outcome='unknown')
        self.assertIsNone(self.manager.recommend(self.group(), base, [base, candidate]))
        for reference in refs:
            self.manager.feedback(reference, 'verified', 'verification')
        result = self.manager.recommend(self.group(), base, [base, candidate])
        self.assertEqual(result['pair'], candidate)
        for change in ({'runtime': 'updated-runtime'}, {'catalog': 'new-catalog'}, {'revision': 'changed-harness'}, {'category': 'review'}, {'tier': 'deep'}):
            self.assertIsNone(self.manager.recommend(self.group(**change), base, [base, candidate]))
        self.assertIsNone(self.manager.recommend(self.group(), base, [base]))
        self.now += 31 * 86400
        self.assertIsNone(self.manager.recommend(self.group(), base, [base, candidate]))

    def test_corrected_quality_and_environment_failures_do_not_poison_advice(self):
        self.manager.configure(True)
        base, candidate = ('base', 'medium'), ('candidate', 'adaptive')
        self.populate(*base, 1000, 1000)
        refs = self.populate(*candidate, 100, 100)
        for reference in refs[:12]:
            self.manager.feedback(reference, 'failed', 'verification', 'environment')
        self.assertIsNone(self.manager.recommend(self.group(), base, [base, candidate]))  # Remaining evidence is insufficient.
        for reference in refs:
            self.manager.feedback(reference, 'failed', 'verification', 'inference')
        self.assertIsNone(self.manager.recommend(self.group(), base, [base, candidate]))
        self.assertEqual(self.manager.status()['samples'], 48)
        self.assertFalse(self.manager.feedback(refs[-1], 'failed', 'verification', 'inference')['recorded'])

    def test_verified_quality_recovery_can_outweigh_higher_measured_cost(self):
        self.manager.configure(True)
        base, candidate = ('failing', 'low'), ('reliable', 'adaptive')
        self.populate(*base, 100, 100, outcome='failed')
        self.populate(*candidate, 1000, 1000)
        result = self.manager.recommend(self.group(), base, [base, candidate])
        self.assertEqual(result, {'pair': candidate, 'reason': 'observed-quality-recovery'})

    def test_privacy_bad_settings_and_unknown_tokens_are_preserved(self):
        self.manager.configure(True)
        references = self.populate('private-model', 'future-effort', None, 100, count=1)
        before = self.manager.location().read_bytes()
        with self.assertRaises(ValueError):
            self.manager.configure(policy={'confidence': float('nan')})
        self.assertEqual(self.manager.location().read_bytes(), before)
        for raw in ('private-model', 'future-effort', str(self.root), 'dynamic-runtime', 'session'):
            self.assertNotIn(raw, before.decode())
        self.assertIsNone(self.manager.status()['workItems'][0]['tokens'])
        with self.assertRaises(ValueError):
            self.manager.feedback(references[0], 'verified', 'user-reported')
        self.manager.clear()
        self.assertEqual(self.manager.status()['samples'], 0)
        self.assertFalse(self.manager.status()['enabled'])

    def test_native_observer_records_usage_delta_without_assuming_task_success(self):
        with mock.patch.dict(os.environ, {'HARNESS_STATE_HOME': str(self.store)}):
            self.manager.configure(True)
            observer = routing_feedback.Observer(ROOT, self.root, 'dynamic-runtime', clock=lambda: self.now)
            policy = auto_relay.Policy(mode='auto', observer=observer)
            policy.model_list(catalog())
            policy.response({'result': {'thread': {'id': 'thread', 'cwd': str(self.root)}, 'modelProvider': 'fixture', 'serviceTier': None,
                                       'model': 'gpt-5.6-sol', 'reasoningEffort': 'medium'}}, 'thread/start', {})
            params = {'threadId': 'thread', 'input': [{'type': 'text', 'text': 'Implement a function'}]}
            policy.request('turn/start', params)
            policy.response({'result': {'turn': {'id': 'turn'}}}, 'turn/start', params)
            policy.response({'method': 'thread/tokenUsage/updated', 'params': {'threadId': 'thread', 'turnId': 'turn', 'tokenUsage': {'total': {'totalTokens': 100}, 'last': {'totalTokens': 12}}}}, None, {})
            self.now += 2
            policy.response({'method': 'turn/completed', 'params': {'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'completed'}}}, None, {})
            report = self.manager.status()
            self.assertEqual(report['samples'], 1)
            self.assertEqual(report['workItems'][0]['tokens'], 100)
            self.assertEqual(report['workItems'][0]['outcome'], 'unknown')
            self.assertEqual(report['workItems'][0]['milliseconds'], 2000)
            policy.response({'method': 'turn/completed', 'params': {'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'completed'}}}, None, {})
            self.assertEqual(self.manager.status()['samples'], 1)

    def test_changed_or_mixed_turns_are_excluded_from_performance_evidence(self):
        manifest = self.root / '.harness/manifest.json'
        original = manifest.read_bytes()
        with mock.patch.dict(os.environ, {'HARNESS_STATE_HOME': str(self.store)}):
            for scenario in ('revision', 'overlap', 'delegation', 'compaction', 'provider', 'foreign-usage'):
                with self.subTest(scenario=scenario):
                    self.manager.clear()
                    self.manager.configure(True)
                    observer = routing_feedback.Observer(ROOT, self.root, 'dynamic-runtime', clock=lambda: self.now)
                    policy = auto_relay.Policy(mode='auto', observer=observer)
                    policy.model_list(catalog())
                    settings = {'thread': {'id': 'thread', 'cwd': str(self.root)}, 'modelProvider': 'fixture', 'serviceTier': None,
                                'model': 'gpt-5.6-sol', 'reasoningEffort': 'medium'}
                    policy.response({'result': settings}, 'thread/start', {})
                    params = {'threadId': 'thread', 'input': [{'type': 'text', 'text': 'Implement a function'}]}
                    policy.request('turn/start', params)
                    if scenario == 'overlap':
                        policy.request('turn/start', params)
                    policy.response({'result': {'turn': {'id': 'turn'}}}, 'turn/start', params)
                    if scenario == 'revision':
                        value = json.loads(original)
                        value['review-fixture-change'] = True
                        manifest.write_text(json.dumps(value))
                    elif scenario in {'delegation', 'compaction'}:
                        item = 'collabAgentToolCall' if scenario == 'delegation' else 'contextCompaction'
                        policy.response({'method': 'item/started', 'params': {'threadId': 'thread', 'turnId': 'turn', 'item': {'type': item}}}, None, {})
                    elif scenario == 'provider':
                        policy.response({'method': 'thread/settings/updated', 'params': {'threadId': 'thread', 'threadSettings': {'modelProvider': 'different'}}}, None, {})
                    elif scenario == 'foreign-usage':
                        policy.response({'method': 'thread/tokenUsage/updated', 'params': {'threadId': 'thread', 'turnId': 'other', 'tokenUsage': {'total': {'totalTokens': 100}}}}, None, {})
                    policy.response({'method': 'turn/completed', 'params': {'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'completed'}}}, None, {})
                    self.assertEqual(self.manager.status()['samples'], 0)
                    self.assertIsNotNone(policy.observer)
                    manifest.write_bytes(original)

    def test_resuming_discards_stale_usage_and_missing_provider_is_not_guessed(self):
        with mock.patch.dict(os.environ, {'HARNESS_STATE_HOME': str(self.store)}):
            self.manager.configure(True)
            observer = routing_feedback.Observer(ROOT, self.root, 'dynamic-runtime', clock=lambda: self.now)
            policy = auto_relay.Policy(mode='auto', observer=observer)
            policy.model_list(catalog())
            settings = {'thread': {'id': 'thread', 'cwd': str(self.root)}, 'model': 'gpt-5.6-sol', 'reasoningEffort': 'medium'}
            policy.response({'result': settings}, 'thread/start', {})
            params = {'threadId': 'thread', 'input': [{'type': 'text', 'text': 'Implement a function'}]}
            policy.request('turn/start', params)
            self.assertEqual(observer.pending, {})
            observer.usage['thread'] = 1000
            policy.response({'result': {**settings, 'modelProvider': 'fixture'}}, 'thread/resume', params)
            policy.request('turn/start', params)
            policy.response({'result': {'turn': {'id': 'turn'}}}, 'turn/start', params)
            policy.response({'method': 'thread/tokenUsage/updated', 'params': {'threadId': 'thread', 'turnId': 'turn', 'tokenUsage': {'total': {'totalTokens': 1600}, 'last': {'totalTokens': 100}}}}, None, {})
            policy.response({'method': 'turn/completed', 'params': {'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'completed'}}}, None, {})
            self.assertIsNone(self.manager.status()['workItems'][0]['tokens'])

    def test_optional_observation_failure_cannot_change_native_task_or_permissions(self):
        observer = mock.Mock()
        observer.decision.side_effect = ValueError('invalid local evidence')
        policy = auto_relay.Policy(mode='auto', observer=observer)
        policy.model_list(catalog())
        params = {'threadId': 'thread', 'input': [{'type': 'text', 'text': 'Implement a function'}], 'approvalPolicy': 'never', 'sandboxPolicy': {'type': 'readOnly'}}
        result = policy.request('turn/start', params)
        for name in ('input', 'approvalPolicy', 'sandboxPolicy'):
            self.assertEqual(result[name], params[name])
        self.assertIsNone(policy.observer)
        self.assertEqual(len(policy.notices), 1)

    def test_request_context_overrides_wait_for_acceptance_and_one_turn_modes_are_excluded(self):
        with mock.patch.dict(os.environ, {'HARNESS_STATE_HOME': str(self.store)}):
            self.manager.configure(True)
            observer = routing_feedback.Observer(ROOT, self.root, 'dynamic-runtime', clock=lambda: self.now)
            policy = auto_relay.Policy(mode='auto', observer=observer)
            policy.model_list(catalog())
            settings = {'thread': {'id': 'thread', 'cwd': str(self.root)}, 'modelProvider': 'fixture', 'serviceTier': None,
                        'sandbox': {'type': 'readOnly'}, 'model': 'gpt-5.6-sol', 'reasoningEffort': 'medium'}
            policy.response({'result': settings}, 'thread/start', {})
            request = {'threadId': 'thread', 'input': [{'type': 'text', 'text': 'Implement a function'}]}
            for extra in ({'serviceTierForTurn': 'priority'}, {'outputSchema': {'type': 'object'}}, {'toolOutput': {'value': 'fixture'}},
                          {'cwd': str(self.root / 'different')}, {'approvalPolicy': 'never'}, {'serviceTier': 'priority'},
                          {'sandboxPolicy': {'type': 'workspaceWrite'}}):
                with self.subTest(extra=extra):
                    before = copy.deepcopy(observer.provenance)
                    result = policy.request('turn/start', {**request, **extra})
                    self.assertEqual(observer.pending, {})
                    for key, value in extra.items():
                        self.assertEqual(result[key], value)
                    policy.response({'error': {'message': 'rejected'}}, 'turn/start', {**request, **extra})
                    self.assertEqual(observer.provenance, before)
            accepted = {**request, 'serviceTier': 'priority'}
            policy.request('turn/start', accepted)
            policy.response({'result': {'turn': {'id': 'changed'}}}, 'turn/start', accepted)
            self.assertEqual(observer.provenance['thread']['serviceTier'], 'priority')
            policy.request('turn/start', request)
            self.assertIn('thread', observer.pending)
            self.assertIsNotNone(policy.observer)

    def test_steering_and_unclassified_followups_exclude_the_active_observation(self):
        with mock.patch.dict(os.environ, {'HARNESS_STATE_HOME': str(self.store)}):
            self.manager.configure(True)
            for method, followup in (('turn/steer', [{'type': 'text', 'text': 'Additional direction'}]),
                                     ('turn/start', [{'type': 'image', 'url': 'fixture'}])):
                with self.subTest(method=method):
                    observer = routing_feedback.Observer(ROOT, self.root, 'dynamic-runtime', clock=lambda: self.now)
                    policy = auto_relay.Policy(mode='auto', observer=observer)
                    policy.model_list(catalog())
                    policy.response({'result': {'thread': {'id': 'thread', 'cwd': str(self.root)}, 'modelProvider': 'fixture',
                                               'model': 'gpt-5.6-sol', 'reasoningEffort': 'medium'}}, 'thread/start', {})
                    params = {'threadId': 'thread', 'input': [{'type': 'text', 'text': 'Implement a function'}]}
                    policy.request('turn/start', params)
                    policy.response({'result': {'turn': {'id': 'turn'}}}, 'turn/start', params)
                    result = policy.request(method, {'threadId': 'thread', 'input': followup})
                    self.assertEqual(result['input'], followup)
                    self.assertTrue(observer.active['thread']['mixed'])
                    policy.response({'method': 'turn/completed', 'params': {'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'completed'}}}, None, {})
                    self.assertEqual(self.manager.status()['samples'], 0)
                    self.assertIsNotNone(policy.observer)

    def test_adaptive_maintenance_backs_off_but_respects_explicit_budget(self):
        manager = maintenance.Maintenance(self.root, self.store, clock=lambda: self.now)
        manager.configure('auto', {'reviewsPerDay': 4})
        manager.signal('scope-changed', 'pyproject.toml', 'first')
        lease = manager.begin()
        self.now += 20
        manager.finish(lease['id'], 'unchanged', tokens=100)
        manager.signal('workflow-gap', 'pyproject.toml', 'gap-one')
        manager.signal('workflow-gap', 'pyproject.toml', 'gap-two')
        self.now += 3600
        self.assertEqual(manager.begin()['status'], 'deferred')
        self.now += 3600
        second = manager.begin()
        self.assertEqual(second['status'], 'claimed')
        self.assertLess(second['deadline'] - second['started'], 180)
        manager.finish(second['id'], 'unchanged')
        manager.configure(policy={'reportedTokensPerDay': 200})
        manager.signal('user-request', 'pyproject.toml', 'explicit')
        self.now += 3600
        self.assertTrue(manager.status()['scheduling']['budgetBlocked'])
        self.assertEqual(manager.begin()['status'], 'deferred')

    def test_maintenance_schema2_migration_is_read_only_and_keeps_opt_out(self):
        manager = maintenance.Maintenance(self.root, self.store, clock=lambda: self.now)
        manager.configure('off')
        path = manager._location()
        value = json.loads(path.read_text())
        for name in ('policy', 'recentReviews', 'retired'):
            value.pop(name)
        value['schema'] = 2
        path.write_text(json.dumps(value))
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.assertEqual(manager.status()['mode'], 'off')
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
