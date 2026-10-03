"""Selection probes distinguish measured quality from interrupted execution."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.agents/skills/harness/scripts'))
import harness_eval


class EvaluationProbeTests(unittest.TestCase):
    def run_suite(self, kind, captures):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'cases.json'
            expected = {'selection': 'direct', 'requiredBehaviors': ['verify'], 'forbiddenBehaviors': []}
            path.write_text(json.dumps({'schemaVersion': 1, 'candidates': ['direct', 'delegate'],
                'behaviorTags': ['verify'], 'cases': [{'caseId': str(index), 'prompt': 'fixture',
                'expected': expected} for index in range(len(captures))]}))
            args = SimpleNamespace(cases=str(path), validate_only=False, root=str(root), timeout=1,
                codex_binary='unused', codex_home=None, model=None, reasoning_effort='unknown')
            output = io.StringIO()
            with mock.patch.object(harness_eval.capture, 'run_codex_jsonl', side_effect=captures), \
                    contextlib.redirect_stdout(output):
                status = harness_eval._probe_suite(args, kind=kind)
            return status, json.loads(output.getvalue())

    def capture(self, *, exit_code=0, cleanup=True, completion='completed', terminal=True,
                compatibility='supported', selection='direct'):
        summary = SimpleNamespace(final_message=json.dumps({'selection': selection, 'behaviors': ['verify']}),
            completion=completion, terminal_event_observed=terminal, parser_compatibility=compatibility)
        return summary, exit_code, 10, cleanup, 'fixture'

    def test_all_probe_types_preserve_unmeasured_cases_in_the_denominator(self):
        for kind in ('skill', 'route', 'change-discipline'):
            with self.subTest(kind=kind):
                status, result = self.run_suite(kind, [self.capture(), self.capture(exit_code=1),
                    self.capture(completion='failed'), self.capture(completion='interrupted'),
                    self.capture(terminal=False), self.capture(compatibility='partial'),
                    self.capture(compatibility='unsupported'), self.capture(cleanup=False)])
                self.assertEqual(status, 1)
                self.assertEqual((result['caseCount'], result['matchedCount'], result['measuredCaseCount']), (8, 1, 1))
                self.assertEqual(result['accuracy'], 1 / 8)
                self.assertEqual(result['unmeasuredCaseCount'], 7)
                self.assertEqual(result['results'][0]['caseOutcome'], 'matched')
                for case in result['results'][1:]:
                    self.assertFalse(case['qualityMeasured'])
                    self.assertFalse(case['matched'])
                    self.assertIn(case['caseOutcome'], {'execution-failed', 'unconfirmed'})
                    if kind == 'change-discipline':
                        self.assertIsNone(case['behaviorsMatched'])

    def test_complete_correct_and_incorrect_answers_are_measured_quality(self):
        status, result = self.run_suite('route', [self.capture(), self.capture(selection='delegate')])
        self.assertEqual(status, 0)
        self.assertEqual(result['accuracy'], .5)
        self.assertEqual(result['unmeasuredCaseCount'], 0)
        self.assertEqual([item['caseOutcome'] for item in result['results']], ['matched', 'mismatched'])
        self.assertTrue(all(item['qualityMeasured'] for item in result['results']))


if __name__ == '__main__':
    unittest.main()
