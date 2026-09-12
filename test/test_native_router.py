import json
import os
from pathlib import Path
import subprocess
import sys
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
        self.environment = mock.patch.dict(os.environ, {'HARNESS_ROUTER_RESUME': '0'})
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

    def test_resume_and_feedback_are_not_replaced_by_invented_task_success(self):
        with mock.patch.dict(os.environ, {'HARNESS_ROUTER_RESUME': '1'}):
            self.assertEqual(select(request())['effort'], 'high')
        value = request()
        value['context'] = {'tier': 'deep', 'model': 'gpt-6-astra', 'effort': 'high', 'failures': 2, 'active_task': True}
        self.assertEqual(select(value)['context']['failures'], 2)

    def test_real_isolated_stdio_process_returns_no_prompt_or_provider_data(self):
        command = [sys.executable, '-I', '-B', str(ROOT / 'harness_cli/native_router.py')]
        result = subprocess.run(command, input=json.dumps(request()), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['model'], 'gpt-5.6-luna')
        self.assertNotIn('README', result.stdout + result.stderr)
        result = subprocess.run(command, input='PRIVATE INVALID INPUT', capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((result.stdout, result.stderr), ('', ''))
