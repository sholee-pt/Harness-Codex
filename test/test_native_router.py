import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from harness_cli.native_router import select

ROOT = Path(__file__).resolve().parents[1]


def request(prompt='Fix README wording.'):
    return {'prompt': prompt, 'context': None, 'model': 'gpt-6-astra', 'effort': 'high', 'hasImages': False,
            'catalog': [{'model': model, 'show_in_picker': True, 'is_default': model == 'gpt-6-astra',
                         'default_reasoning_effort': 'medium', 'input_modalities': modalities,
                         'supported_reasoning_efforts': [{'effort': x} for x in ['low', 'medium', 'high']]}
                        for model, modalities in [('gpt-5.6-luna', ['text']), ('gpt-6-astra', ['text', 'image'])]]}


class NativeRouterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        profiles = Path(temporary.name) / 'profiles.json'
        profiles.write_text(json.dumps({'fast': ['gpt-5.6-luna'], 'balanced': ['gpt-6-astra'], 'deep': ['gpt-6-astra']}))
        self.environment = mock.patch.dict(os.environ, {'HARNESS_ROUTER_RESUME': '0', 'HARNESS_ROUTER_PROFILES': str(profiles)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_two_requests_choose_supported_pairs_and_continuation_retains_depth(self):
        value = request()
        first = select(value)
        self.assertEqual((first['model'], first['effort']), ('gpt-5.6-luna', 'low'))
        value.update(prompt='Review the security architecture.', context=first['context'])
        second = select(value)
        self.assertEqual((second['model'], second['effort']), ('gpt-6-astra', 'high'))
        value.update(prompt='계속 진행해줘.', context=second['context'])
        self.assertEqual(select(value), second)

    def test_images_and_hidden_models_cannot_use_ineligible_preferences(self):
        value = request()
        value['hasImages'] = True
        self.assertEqual(select(value)['model'], 'gpt-6-astra')
        value['hasImages'] = False
        value['catalog'][0]['show_in_picker'] = False
        self.assertEqual(select(value)['model'], 'gpt-6-astra')

    def test_lighter_requests_confirm_downgrade_but_continuations_interrupt_it(self):
        value = request('Review the security architecture.')
        deep = select(value)
        value.update(context=deep['context'], prompt='Fix README wording.')
        pending = select(value)
        self.assertEqual((pending['model'], pending['effort']), ('gpt-6-astra', 'high'))
        self.assertEqual(pending['context']['lighter_requests'], 1)
        value.update(context=pending['context'], prompt='계속 진행해줘.')
        continued = select(value)
        self.assertEqual(continued['context']['lighter_requests'], 0)
        value.update(context=continued['context'], prompt='문서 제목의 오타를 고쳐줘.')
        value['context'] = select(value)['context']
        value['prompt'] = 'Correct the spelling in README.'
        fast = select(value)
        self.assertEqual((fast['model'], fast['effort']), ('gpt-5.6-luna', 'low'))
        value.update(context=fast['context'], prompt='함수를 구현해줘.')
        balanced = select(value)
        self.assertEqual((balanced['model'], balanced['effort']), ('gpt-6-astra', 'medium'))
        value.update(context=balanced['context'], prompt='Find a race condition in the workers.')
        self.assertEqual(select(value)['effort'], 'high')

    def test_explicit_new_task_and_legacy_context_allow_immediate_downgrade(self):
        for prompt in ('New task: fix README wording.', '다음 작업: 문서 제목의 오타를 고쳐줘.'):
            with self.subTest(prompt=prompt):
                value = request(prompt)
                value['context'] = {'tier': 'deep', 'model': 'gpt-6-astra', 'effort': 'high', 'failures': 2, 'active_task': True}
                result = select(value)
                self.assertEqual((result['model'], result['effort']), ('gpt-5.6-luna', 'low'))
                self.assertEqual(result['context']['failures'], 0)

    def test_same_tier_and_manual_catalog_preference_do_not_oscillate(self):
        value = request('Implement the endpoint.')
        first = select(value)
        for prompt in ('Refactor the function.', 'Add a test for the function.', '계속 진행해줘.'):
            value.update(context=first['context'], prompt=prompt)
            self.assertEqual(select(value), first)

    def test_invalid_lighter_request_count_is_rejected(self):
        value = request()
        value['context'] = select(value)['context']
        for count in (-1, 2, True, '1'):
            with self.subTest(count=count), self.assertRaises(ValueError):
                select({**value, 'context': {**value['context'], 'lighter_requests': count}})

    def test_resume_and_feedback_are_not_replaced_by_invented_task_success(self):
        value = request()
        value['context'] = {'tier': 'deep', 'model': 'gpt-6-astra', 'effort': 'high', 'failures': 2, 'active_task': True}
        self.assertEqual(select(value)['context']['failures'], 2)
        value['context']['failures'] = 0
        self.assertEqual(select(value)['effort'], 'high')

    def test_real_isolated_stdio_process_returns_no_prompt_or_provider_data(self):
        command = [sys.executable, '-I', '-B', str(ROOT / 'harness_cli/native_router.py')]
        result = subprocess.run(command, input=json.dumps(request()), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['model'], 'gpt-5.6-luna')
        self.assertNotIn('README', result.stdout + result.stderr)
        result = subprocess.run(command, input='PRIVATE INVALID INPUT', capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((result.stdout, result.stderr), ('', ''))

    def test_obsolete_launcher_environment_cannot_rewrite_the_users_task(self):
        value = request('Read the security architecture instructions and wait.')
        with mock.patch.dict(os.environ, {'HARNESS_ROUTER_INITIAL_PROMPT_SHA256': hashlib.sha256(value['prompt'].encode()).hexdigest()}):
            result = select(value)
        self.assertTrue(result['context']['active_task'])
        self.assertEqual(result['model'], 'gpt-6-astra')
        # Explicit Auto reselection supplies a fresh context, native resume a retained one.
        value.update(prompt='Fix README wording.', context=None)
        self.assertEqual(select(value)['model'], 'gpt-5.6-luna')
