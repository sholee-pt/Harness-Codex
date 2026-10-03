"""Adaptive advice uses semantic catalog changes and verified supported pairs."""
import copy
import os
from pathlib import Path
import unittest
from unittest import mock

from harness_cli import auto_relay, routing_feedback
import test_adaptive_evidence as fixtures
from test_official_relay import catalog

ROOT = Path(__file__).resolve().parents[1]


class RoutingFeedbackPolicyTests(unittest.TestCase):
    setUp = fixtures.AdaptiveEvidenceTests.setUp
    group = fixtures.AdaptiveEvidenceTests.group
    populate = fixtures.AdaptiveEvidenceTests.populate

    def test_catalog_copy_changes_keep_evidence_but_capability_changes_separate_it(self):
        original = catalog()['data']
        changed = copy.deepcopy(original)
        changed.reverse()
        for entry in changed:
            entry['displayName'] = 'Updated display label'
            entry['description'] = 'Updated explanatory copy'
            entry['supportedReasoningEfforts'].reverse()
            for option in entry['supportedReasoningEfforts']:
                option['description'] = 'Updated effort explanation'
        self.assertEqual(routing_feedback.catalog_context(original), routing_feedback.catalog_context(changed))
        for update in ({'hidden': True}, {'isDefault': True}, {'upgrade': 'future-model'},
                       {'supportedReasoningEfforts': [{'reasoningEffort': 'future-effort'}]},
                       {'inputModalities': ['image']}, {'futureCapability': {'enabled': True}}):
            with self.subTest(update=update):
                candidate = copy.deepcopy(original)
                candidate[0].update(update)
                self.assertNotEqual(routing_feedback.catalog_context(original), routing_feedback.catalog_context(candidate))

    def test_observed_alternative_effort_requires_quality_and_respects_profiles(self):
        with mock.patch.dict(os.environ, {'HARNESS_STATE_HOME': str(self.store)}):
            self.manager.configure(True)
            observer = routing_feedback.Observer(ROOT, self.root, 'dynamic-runtime', clock=lambda: self.now)
            observer.managers[str(self.root)] = self.manager
            policy = auto_relay.Policy(mode='auto', observer=observer, profiles={'balanced': ['gpt-5.6-sol']})
            policy.model_list(catalog())
            policy.response({'result': {'thread': {'id': 'thread', 'cwd': str(self.root)}, 'modelProvider': 'fixture',
                                       'model': 'gpt-5.6-sol', 'reasoningEffort': 'medium'}}, 'thread/start', {})
            params = {'threadId': 'thread', 'input': [{'type': 'text', 'text': 'Implement a function.'}]}
            policy.request('turn/start', params)
            group = observer.pending.pop('thread')['context']
            self.populate('gpt-5.6-sol', 'medium', 1000, 1000, group=group)
            # Distinct work-item IDs keep both efforts as independent samples.
            references = []
            for index in range(24):
                result = self.manager.record('session', 'low-' + str(index), context=group,
                    model='gpt-5.6-sol', effort='low', milliseconds=100, tokens=100)
                references.append(result['reference'])
            self.populate('gpt-6-astra', 'low', 1, 1, group=group)
            result = policy.request('turn/start', params)
            self.assertEqual((result['model'], result['effort']), ('gpt-5.6-sol', 'medium'))
            observer.pending.clear()
            for reference in references:
                self.manager.feedback(reference, 'verified', 'verification', 'inference')
            renamed = catalog()
            renamed['data'][0]['displayName'] = 'Cosmetic catalog update'
            policy.model_list(renamed)
            result = policy.request('turn/start', params)
            self.assertEqual((result['model'], result['effort']), ('gpt-5.6-sol', 'low'))
            observer.pending.clear()
            changed = catalog()
            changed['data'][1]['futureCapability'] = True
            policy.model_list(changed)
            result = policy.request('turn/start', params)
            self.assertEqual((result['model'], result['effort']), ('gpt-5.6-sol', 'medium'))
