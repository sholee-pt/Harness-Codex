"""Router upgrades and runtime observations preserve actual task outcomes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_harness_tools import harness_apply, harness_plan_builder, harness_teamplay, minimal_plan, validate_harness
import test_runtime_receipt_v2 as receipt_fixtures

receipt2 = receipt_fixtures.receipt2


class CompactRouterTests(unittest.TestCase):
    def test_legacy_installation_validates_without_writes_and_upgrades_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            plan['artifacts'][0]['content'] = plan['artifacts'][0]['content'].replace(
                harness_teamplay.PROJECT_BLOCK, harness_teamplay.LEGACY_PROJECT_BLOCK)
            harness_apply.apply_application(harness_apply.build_application(root, plan))
            before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
            self.assertTrue(validate_harness.Validator(root).run()['valid'])
            self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})
            draft = copy.deepcopy(plan)
            draft['authoringContractVersion'] = 3
            updated = harness_plan_builder.materialize_plan(draft, root=root)
            body = updated['artifacts'][0]['content']
            self.assertIn(harness_teamplay.PROJECT_BLOCK, body)
            self.assertNotIn(harness_teamplay.LEGACY_PROJECT_BLOCK, body)
            self.assertLess(len(body.encode()), 9500)
            self.assertNotIn('Record `selected`, `receiverHandleAcknowledged`', body)
            self.assertIn('native-subagent-relay.md', body)
            harness_apply.apply_application(harness_apply.build_application(root, updated))
            after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
            repeat = harness_apply.build_application(root, updated)
            self.assertTrue(all(action['action'] == 'unchanged' for action in repeat['report']['actions']))
            harness_apply.apply_application(repeat)
            self.assertEqual(after, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in after})

    def test_reviewed_legacy_replacement_preserves_surrounding_crlf_text(self):
        before = 'User project methods.\r\n\r\n'
        after = '\r\n\r\nKeep these bytes.\r\n'
        old = before + harness_teamplay.LEGACY_PROJECT_BLOCK.replace('\n', '\r\n') + after
        actual = harness_plan_builder._materialize_contract(old,
            harness_plan_builder.PROJECT_TEAMPLAY_PLACEHOLDER, harness_teamplay.PROJECT_BLOCK, 'router')
        self.assertEqual(actual, before + harness_teamplay.PROJECT_BLOCK.replace('\n', '\r\n') + after)

    def test_mixed_or_partial_contracts_are_not_accepted(self):
        for extra in (harness_teamplay.LEGACY_PROJECT_BLOCK, harness_teamplay.PROJECT_BLOCK,
                      '<!-- harness:runtime-teamplay:v2:begin -->'):
            with self.subTest(extra=extra[:60]), self.assertRaises(harness_teamplay.TeamplayError):
                harness_teamplay.require_exactly_once(harness_teamplay.PROJECT_BLOCK + extra,
                    harness_teamplay.PROJECT_BLOCK, 'router')


class ProgressReceiptTests(unittest.TestCase):
    def setUp(self):
        self.fixture = receipt_fixtures.RuntimeReceiptV2Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.plan = self.fixture._single_agent_plan()
        self.participant = receipt_fixtures.participant_names(self.plan)[0]

    def receipt(self, **overrides):
        return self.fixture._build(plan=self.plan, control_plane=receipt_fixtures.control_plane_report(self.plan,
            agent_overrides={self.participant: overrides}))

    def test_poll_frequency_and_long_progress_do_not_negate_completion(self):
        for attempts, elapsed in ((4, 4000), (20, 300001), (100, 1800000)):
            with self.subTest(attempts=attempts, elapsed=elapsed):
                result = self.receipt(waitAttempts=attempts, waitTimeMs=elapsed)
                self.assertTrue(result['agents'][0]['completed'])
                self.assertFalse(result['agents'][0]['failed'])
                self.assertEqual(result['collaborationCompleteness'], 'complete')
                self.assertTrue(result['provesLiveSubagentExecution'])

    def test_total_budget_overrun_is_warning_not_fabricated_terminal_failure(self):
        result = self.receipt(waitAttempts=4, waitTimeMs=1800001)
        self.assertTrue(result['agents'][0]['completed'])
        self.assertFalse(result['agents'][0]['failed'])
        self.assertTrue(any('wait budget' in warning for warning in result['warnings']))
        self.assertTrue(receipt2.validate_runtime_receipt(result)['valid'])
        unfinished = self.receipt(waitAttempts=20, waitTimeMs=1800001,
            waitStatus='running', resultCollected=False)
        self.assertFalse(unfinished['agents'][0]['completed'])
        self.assertFalse(unfinished['agents'][0]['failed'])
        self.assertEqual(unfinished['collaborationCompleteness'], 'partial')

    def test_native_failure_remains_failure(self):
        result = self.receipt(waitAttempts=4, waitTimeMs=4000, waitStatus='failed', resultCollected=False)
        self.assertTrue(result['agents'][0]['failed'])
        self.assertFalse(result['agents'][0]['completed'])
        self.assertFalse(result['provesLiveSubagentExecution'])

    def test_legacy_receipt_policy_remains_readable_without_rewrite(self):
        result = self.receipt()
        result['runtime']['waitPolicy'] = dict(receipt2.LEGACY_WAIT_POLICY)
        result.pop('integrity')
        result['integrity'] = {'algorithm': 'sha256', 'canonicalSha256': receipt2.digest(result)}
        before = json.dumps(result, sort_keys=True)
        self.assertTrue(receipt2.validate_runtime_receipt(result)['valid'])
        self.assertEqual(json.dumps(result, sort_keys=True), before)


if __name__ == '__main__':
    unittest.main()
