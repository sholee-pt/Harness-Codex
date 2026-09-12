"""Routing contract and independent task scenarios; no provider/model calls."""
from dataclasses import replace
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from harness_cli import main, model_routing as routing

ROOT = Path(__file__).resolve().parents[1]


def model(name, default=False, efforts=('low', 'medium', 'high')):
    return {'model': name, 'isDefault': default, 'defaultReasoningEffort': efforts[0],
            'supportedReasoningEfforts': [{'reasoningEffort': effort} for effort in efforts]}


CATALOG = [model('gpt-5.6-luna'), model('recommended-model', True), model('gpt-6-astra')]


class RoutingTests(unittest.TestCase):
    def test_independent_task_matrix(self):
        cases = [
            ('README 문구를 수정해줘.', 'fast'), ('Fix the spelling in the introduction.', 'fast'),
            ('문서 제목의 오타를 고쳐줘.', 'fast'), ('Correct this punctuation.', 'fast'),
            ('Read the repository and explain its responsibilities.', 'balanced'),
            ('새 기능을 구현해줘.', 'balanced'), ('Summarize the experiment results.', 'balanced'),
            ('Continue.', 'balanced'), ('고쳐줘.', 'balanced'),
            ('Fix a typo in the function and refactor its implementation.', 'balanced'),
            ('Compare two algorithms.', 'balanced'), ('README의 인증 설명을 검토해줘.', 'deep'),
            ('Find the race condition in these workers.', 'deep'), ('평가 데이터 누수를 조사해줘.', 'deep'),
            ('여러 모듈의 설계를 바꿔줘.', 'deep'), ('Plan the database migration.', 'deep'),
            ('The architecture must support distributed workers.', 'deep'),
        ]
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                decision = routing.choose(prompt, CATALOG)
                self.assertEqual(decision.tier, expected)
                self.assertEqual(decision.model, {'fast': 'gpt-5.6-luna', 'balanced': 'recommended-model', 'deep': 'gpt-6-astra'}[expected])
                self.assertEqual(decision.effort, {'fast': 'low', 'balanced': 'medium', 'deep': 'high'}[expected])

    def test_followup_does_not_downgrade_difficult_work(self):
        context = routing.Context('deep', 'gpt-6-astra', 'high', active_task=True)
        for prompt in ('계속 진행해줘.', 'yes', 'Fix the README sentence.', '한번 더 해줘.'):
            decision = routing.choose(prompt, CATALOG, context=context)
            self.assertEqual((decision.model, decision.effort), ('gpt-6-astra', 'high'))
            self.assertFalse(decision.changed)
        decision = routing.choose('Fix the README sentence.', CATALOG, context=context, new_task=True)
        self.assertEqual(decision.tier, 'fast')

    def test_verified_failures_escalate_without_retrying_or_adding_roles(self):
        context = routing.Context('fast', 'gpt-5.6-luna', 'low', 2, True)
        decision = routing.choose('다시 확인해줘.', CATALOG, context=context)
        self.assertEqual((decision.tier, decision.reason), ('deep', 'repeated-failure'))
        self.assertEqual(set(decision.turn_overrides()), {'model', 'effort'})

    def test_manual_pin_survives_complex_requests_and_failures(self):
        context = routing.Context('balanced', failures=3, active_task=True)
        decision = routing.choose('Review authentication.', CATALOG, context=context,
                                  fixed=('gpt-5.6-luna', 'medium'))
        self.assertEqual(decision.turn_overrides(), {'model': 'gpt-5.6-luna', 'effort': 'medium'})
        self.assertEqual(decision.reason, 'manual-fixed')

    def test_missing_profiles_use_available_default_without_guessing(self):
        catalog = [model('new-unknown-model', True, ('low', 'ultra'))]
        decision = routing.choose('Review concurrency.', catalog)
        self.assertEqual(decision.turn_overrides(), {'model': 'new-unknown-model', 'effort': 'low'})
        self.assertEqual(decision.selection, 'available-default')
        self.assertEqual(routing.choose('Review concurrency.', [model('not-recommended')]).turn_overrides(), {})

    def test_missing_effort_does_not_switch_model_and_inherit_invalid_effort(self):
        catalog = [{'model': 'gpt-6-astra', 'isDefault': True}]
        self.assertEqual(routing.choose('Review security.', catalog).turn_overrides(), {})
        catalog[0]['supportedReasoningEfforts'] = [{'reasoningEffort': 'low'}]
        self.assertEqual(routing.choose('Review security.', catalog).turn_overrides(), {})

    def test_hidden_models_and_removed_models_cannot_be_selected(self):
        hidden = dict(CATALOG[0], hidden=True)
        decision = routing.choose('Fix the README sentence.', [hidden, CATALOG[1]])
        self.assertEqual(decision.model, 'recommended-model')
        context = routing.Context('deep', 'removed-model', 'ultra', active_task=True)
        decision = routing.choose('Continue.', [CATALOG[1]], context=context)
        self.assertEqual(decision.model, 'recommended-model')
        self.assertIn(decision.effort, ('low', 'medium', 'high'))

    def test_explicit_profiles_never_assume_catalog_order_is_quality_order(self):
        for catalog in (CATALOG, list(reversed(CATALOG))):
            decision = routing.choose('Review concurrency.', catalog, profiles={'deep': ['recommended-model']})
            self.assertEqual(decision.model, 'recommended-model')

    def test_rejects_malformed_inputs_and_manual_combinations(self):
        for prompt in ('', ' ', 'x\0y', 'x' * (routing.MAX_PROMPT + 1)):
            with self.assertRaises(ValueError):
                routing.choose(prompt, CATALOG)
        for profiles in ({'permissions': ['all']}, {'fast': 'model'}, {'deep': [None]}):
            with self.assertRaises(ValueError):
                routing.choose('hello', CATALOG, profiles=profiles)
        for context in (routing.Context(failures=-1), routing.Context(effort='invented'), routing.Context(active_task=1)):
            with self.assertRaises(ValueError):
                routing.choose('hello', CATALOG, context=context)
        for fixed in (('unknown', 'low'), ('recommended-model', 'ultra')):
            with self.assertRaises(ValueError):
                routing.choose('hello', CATALOG, fixed=fixed)

    def test_context_contains_no_task_text_and_feedback_is_explicit(self):
        decision = routing.choose('PRIVATE TASK: investigate a bug', CATALOG)
        context = routing.advance(routing.Context(), decision, succeeded=False)
        self.assertEqual(context.failures, 1)
        self.assertNotIn('PRIVATE', repr(context))
        context = routing.advance(context, decision, succeeded=True, task_complete=True)
        self.assertEqual((context.failures, context.active_task), (0, False))
        with self.assertRaises(ValueError):
            routing.advance(context, decision, succeeded='looks good')

    def test_offline_cli_preview_is_read_only_and_never_launches_codex(self):
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Path(temporary) / 'catalog.json'
            catalog.write_text(json.dumps({'data': CATALOG, 'nextCursor': None}), encoding='utf-8')
            before = catalog.stat().st_mtime_ns
            output = io.StringIO()
            with contextlib.redirect_stdout(output), mock.patch('harness_cli.configuration.Server') as server:
                status = main.main(['routing', 'PRIVATE: Fix README wording.', '--catalog', str(catalog), '--json'], source_root=ROOT)
            self.assertEqual(status, 0)
            server.assert_not_called()
            result = json.loads(output.getvalue())
            self.assertFalse(result['applied'])
            self.assertEqual(result['modelCalls'], 0)
            self.assertNotIn('PRIVATE', output.getvalue())
            self.assertEqual(list(Path(temporary).iterdir()), [catalog])
            self.assertEqual(catalog.stat().st_mtime_ns, before)

    def test_json_catalog_rejects_partial_pages_and_duplicate_keys(self):
        from harness_cli.routing import load_catalog, read_json
        with self.assertRaises(ValueError):
            load_catalog({'data': CATALOG, 'nextCursor': 'more'})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'policy.json'
            path.write_text('{"fast": [], "fast": []}')
            with self.assertRaises(ValueError):
                read_json(path)
