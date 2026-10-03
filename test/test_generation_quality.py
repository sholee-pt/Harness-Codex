"""Held-out generation attempts, symmetric tasks and failed-attempt accounting."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('generation_quality_runner', REPO / 'test/integration/evaluate_generation_quality.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from test_harness_tools import harness_apply, minimal_plan


class GenerationQualityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.project = self.base / 'raw-project'
        self.project.mkdir()
        (self.project / 'pyproject.toml').write_text('[project]\nname = "held-out"\n')
        (self.project / 'app.py').write_text('VALUE = 0\n')
        (self.base / 'brief.md').write_text('Maintain a small library for project request validation.')
        (self.base / 'task.txt').write_text('Set the application VALUE to 1 and verify the result.')
        self.profile = {'schemaVersion': 1, 'id': 'held-out-check', 'kind': 'custom',
            'argv': [sys.executable, '-B', '-c', 'from pathlib import Path; assert Path("app.py").read_text() == "VALUE = 1\\n"'],
            'timeoutSeconds': 5}
        (self.base / 'check.json').write_text(json.dumps(self.profile))
        self.codex_home = self.base / 'credentials'
        self.codex_home.mkdir()
        (self.codex_home / 'auth.json').write_text('{"fixtureAuth":"private-fixture-value"}')
        self.before = runner.snapshot(self.project)
        self.captured = []

    def args(self, *extra):
        return runner.parser().parse_args(['--project', str(self.project), '--brief-file', str(self.base / 'brief.md'),
            '--task-file', str(self.base / 'task.txt'), '--verification', str(self.base / 'check.json'),
            '--codex-home', str(self.codex_home), '--model', 'fixture-model', '--reasoning-effort', 'medium', *extra])

    def capture(self, **kwargs):
        self.captured.append(kwargs)
        root = kwargs['repository']
        if '$harness Configure' in kwargs['prompt']:
            harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))
        else:
            (root / 'app.py').write_text('VALUE = 1\n')
        summary = runner.capture.CaptureSummary(True, 'completed', {'input_tokens': 15, 'output_tokens': 3},
            {'command': 1, 'subagent': 2, 'file': 1}, 0, 0, 'supported', None)
        return summary, 0, 20, True, 'fixture-version'

    def test_default_dry_run_reads_inputs_without_cloning_inference_verification_or_writes(self):
        with mock.patch.object(runner.capture, 'run_codex_jsonl') as call, mock.patch.object(runner, 'materialize') as clone, mock.patch.object(runner, 'verify') as verify:
            report = runner.run(self.args('--output', str(self.base / 'report.json')))
        self.assertTrue(report['dryRun'])
        self.assertFalse(report['liveCodexInvoked'])
        for operation in (call, clone, verify):
            operation.assert_not_called()
        self.assertFalse((self.base / 'report.json').exists())
        self.assertEqual(runner.snapshot(self.project), self.before)

    def test_report_identity_changes_with_brief_task_verification_and_guidance(self):
        first = runner.run(self.args())['experimentIdentity']
        for filename, value, key in (('brief.md', 'Maintain another contract.', 'briefSha256'),
                                     ('task.txt', 'Set VALUE to 2.', 'taskSha256')):
            (self.base / filename).write_text(value)
            changed = runner.run(self.args())['experimentIdentity']
            self.assertNotEqual(first[key], changed[key])
            first = changed
        self.profile['argv'] = [sys.executable, '-B', '-c', 'raise SystemExit(7)']
        (self.base / 'check.json').write_text(json.dumps(self.profile))
        changed = runner.run(self.args())['experimentIdentity']
        self.assertNotEqual(first['verificationSha256'], changed['verificationSha256'])
        original_snapshot = runner.snapshot
        def changed_guidance(root, **kwargs):
            result = original_snapshot(root, **kwargs)
            if root == REPO / '.agents/skills/harness':
                result['additional-guidance.md'] = (b'Changed guidance.', 0o644)
            return result
        with mock.patch.object(runner, 'snapshot', side_effect=changed_guidance):
            changed = runner.run(self.args())['experimentIdentity']
        self.assertNotEqual(first['generatorSha256'], changed['generatorSha256'])
        self.assertNotIn(str(self.project), json.dumps(changed))

    def test_explicit_evidence_retains_generated_candidates_before_task_only(self):
        evidence = self.base / 'private-evidence'
        (self.project / 'AGENTS.md').write_text('private-user-instructions\n')
        preview = runner.run(self.args('--evidence-dir', str(evidence)))
        self.assertTrue(preview['artifactRetention']['enabled'])
        self.assertFalse(evidence.exists())
        with mock.patch.object(runner.capture, 'run_codex_jsonl', side_effect=self.capture), mock.patch.object(runner.evaluation, 'VERIFICATION_QUIESCENCE_SECONDS', 0):
            report = runner.run(self.args('--live', '--evidence-dir', str(evidence)))
        retained = evidence / 'pair-1'
        self.assertEqual(report['pairs'][0]['generation']['artifactRetention']['state'], 'retained')
        self.assertTrue((retained / '.harness/manifest.json').is_file())
        self.assertTrue((retained / '.agents/skills/project-harness/SKILL.md').is_file())
        self.assertFalse((retained / 'app.py').exists())
        self.assertFalse((retained / '.agents/skills/harness').exists())
        self.assertNotIn('private-user-instructions', (retained / 'AGENTS.md').read_text())
        for path in retained.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'private-fixture-value', path.read_bytes())
                if os.name != 'nt':
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        if os.name != 'nt':
            self.assertEqual(evidence.stat().st_mode & 0o777, 0o700)
        with self.assertRaisesRegex(ValueError, 'new private evidence'):
            runner.run(self.args('--live', '--evidence-dir', str(evidence)))
        with self.assertRaisesRegex(ValueError, 'new private evidence'):
            runner.run(self.args('--live', '--evidence-dir', str(self.project / 'evidence')))
        with self.assertRaisesRegex(ValueError, 'separate from dedicated authentication'):
            runner.run(self.args('--live', '--evidence-dir', str(self.codex_home / 'evidence')))

    def test_failed_generation_candidate_is_retained_without_source_or_task_artifacts(self):
        evidence = self.base / 'failed-evidence'
        def failed(**kwargs):
            if '$harness Configure' in kwargs['prompt']:
                (kwargs['repository'] / '.harness').mkdir()
                (kwargs['repository'] / '.harness/draft.json').write_text('{"incomplete":true}')
                summary = runner.capture.CaptureSummary(True, 'failed', {}, {}, 0, 0, 'supported', None)
                return summary, 1, 20, True, 'fixture-version'
            return self.capture(**kwargs)
        with mock.patch.object(runner.capture, 'run_codex_jsonl', side_effect=failed), mock.patch.object(runner.evaluation, 'VERIFICATION_QUIESCENCE_SECONDS', 0):
            report = runner.run(self.args('--live', '--evidence-dir', str(evidence)))
        self.assertEqual(report['generationFailed'], 1)
        self.assertEqual((evidence / 'pair-1/.harness/draft.json').read_text(), '{"incomplete":true}')
        self.assertFalse((evidence / 'pair-1/app.py').exists())

    def test_authentication_setup_failure_preserves_attempts_and_denominator(self):
        with mock.patch.object(runner, 'isolated_home', side_effect=OSError('fixture setup failure')), mock.patch.object(runner.capture, 'run_codex_jsonl') as native:
            report = runner.run(self.args('--live', '--repetitions', '2'))
        native.assert_not_called()
        self.assertFalse(report['liveCodexInvoked'])
        self.assertEqual(report['codexRunAttempts'], 0)
        self.assertEqual(report['requestedPairs'], 2)
        self.assertEqual(report['generationFailed'], 2)
        self.assertEqual(report['pairs'][0]['generation']['failureKind'], 'OSError')
        self.assertEqual(report['stoppedReason'], 'process-cleanup-unverified')

    def test_invalid_manifest_cannot_retain_unrelated_modified_source(self):
        evidence = self.base / 'untrusted-evidence'
        (self.project / '.env').write_text('fixture credential before')
        def failed(**kwargs):
            if '$harness Configure' in kwargs['prompt']:
                root = kwargs['repository']
                (root / '.env').write_text('fixture credential after')
                (root / '.harness').mkdir()
                (root / '.harness/manifest.json').write_text(json.dumps({'managedFiles': [{'path': '.env', 'kind': 'file'}]}))
                summary = runner.capture.CaptureSummary(True, 'failed', {}, {}, 0, 0, 'supported', None)
                return summary, 1, 20, True, 'fixture-version'
            return self.capture(**kwargs)
        with mock.patch.object(runner.capture, 'run_codex_jsonl', side_effect=failed), mock.patch.object(runner.evaluation, 'VERIFICATION_QUIESCENCE_SECONDS', 0):
            report = runner.run(self.args('--live', '--evidence-dir', str(evidence)))
        self.assertEqual(report['generationFailed'], 1)
        self.assertFalse((evidence / 'pair-1/.env').exists())

    def test_changed_generator_excludes_pair_and_preserves_remaining_denominator(self):
        changed = False
        original_snapshot = runner.snapshot
        def observe(root, **kwargs):
            result = original_snapshot(root, **kwargs)
            if changed and root == REPO / '.agents/skills/harness':
                result['changed-guidance.md'] = (b'changed during experiment', 0o644)
            return result
        def change_guidance(**kwargs):
            nonlocal changed
            result = self.capture(**kwargs)
            changed = True
            return result
        with mock.patch.object(runner, 'snapshot', side_effect=observe), mock.patch.object(runner.capture, 'run_codex_jsonl', side_effect=change_guidance):
            report = runner.run(self.args('--live', '--repetitions', '2'))
        self.assertEqual(report['stoppedReason'], 'experiment-sources-changed')
        self.assertEqual(report['generationFailed'], 2)
        self.assertEqual(report['codexRunAttempts'], 1)
        self.assertEqual(report['baselineVerifiedPassed'], 0)
        self.assertFalse(report['experimentSourcesUnchanged'])
        self.assertEqual(report['pairs'][1]['generation']['state'], 'skipped-experiment-sources-changed')

    def test_live_generation_uses_only_brief_then_same_task_with_isolated_auth(self):
        with mock.patch.object(runner.capture, 'run_codex_jsonl', side_effect=self.capture), mock.patch.object(runner.evaluation, 'VERIFICATION_QUIESCENCE_SECONDS', 0):
            report = runner.run(self.args('--live', '--repetitions', '2'))
        self.assertEqual(report['generationPassed'], 2)
        self.assertEqual(report['endToEndHarnessPassed'], 2)
        self.assertEqual(report['baselineVerifiedPassed'], 2)
        self.assertEqual(report['codexRunAttempts'], 6)
        self.assertEqual(report['generationDenominator'], 2)
        self.assertEqual(report['orders'][0], list(reversed(report['orders'][1])))
        self.assertEqual(runner.snapshot(self.project), self.before)
        generation = [entry for entry in self.captured if '$harness Configure' in entry['prompt']]
        tasks = [entry for entry in self.captured if entry not in generation]
        self.assertEqual(len(generation), 2)
        for entry in generation:
            self.assertIn('small library', entry['prompt'])
            self.assertNotIn('VALUE to 1', entry['prompt'])
        self.assertEqual(len({entry['prompt'] for entry in tasks}), 1)
        self.assertEqual(len({entry['codex_home'] for entry in self.captured}), 6)
        for entry in self.captured:
            self.assertEqual(entry['model'], 'fixture-model')
            self.assertEqual(entry['reasoning_effort'], 'medium')
            self.assertFalse(entry['codex_home'].exists())
        self.assertEqual(report['pairs'][0]['generation']['observedSubagentEvents'], 2)
        self.assertTrue(all(pair['generation']['credentialCleanupVerified'] for pair in report['pairs']))
        serialized = json.dumps(report)
        self.assertNotIn('private-fixture-value', serialized)
        self.assertNotIn('VALUE to 1', serialized)
        self.assertNotIn(str(self.project), serialized)
        self.assertEqual(report['semanticBenefit'], 'not-measured')

    def test_generation_failure_remains_in_denominator_without_retry_or_treatment_task(self):
        generations = 0
        def fail_first(**kwargs):
            nonlocal generations
            if '$harness Configure' in kwargs['prompt']:
                generations += 1
                if generations == 1:
                    self.captured.append(kwargs)
                    summary = runner.capture.CaptureSummary(True, 'failed', {'input_tokens': 9}, {'subagent': 0}, 0, 0, 'supported', None)
                    return summary, 1, 30, True, 'fixture-version'
            return self.capture(**kwargs)
        with mock.patch.object(runner.capture, 'run_codex_jsonl', side_effect=fail_first), mock.patch.object(runner.evaluation, 'VERIFICATION_QUIESCENCE_SECONDS', 0):
            report = runner.run(self.args('--live', '--repetitions', '2'))
        self.assertEqual(report['generationDenominator'], 2)
        self.assertEqual(report['generationFailed'], 1)
        self.assertEqual(report['generationSuccessRate'], .5)
        self.assertEqual(report['endToEndHarnessSuccessRate'], .5)
        self.assertEqual(report['codexRunAttempts'], 5)
        self.assertEqual(report['pairs'][0]['generation']['reportedUsage'], {'input_tokens': 9})
        self.assertEqual(report['pairs'][0]['arms']['harness']['state'], 'skipped-generation-failed')
        self.assertEqual(generations, 2)

    def test_generation_must_not_pre_solve_task_or_modify_application_source(self):
        def premature(**kwargs):
            result = self.capture(**kwargs)
            if '$harness Configure' in kwargs['prompt']:
                (kwargs['repository'] / 'app.py').write_text('VALUE = 1\n')
            return result
        with mock.patch.object(runner.capture, 'run_codex_jsonl', side_effect=premature), mock.patch.object(runner.evaluation, 'VERIFICATION_QUIESCENCE_SECONDS', 0):
            report = runner.run(self.args('--live'))
        self.assertFalse(report['pairs'][0]['generation']['projectPreserved'])
        self.assertEqual(report['generationFailed'], 1)
        self.assertEqual(report['endToEndHarnessPassed'], 0)
        self.assertEqual(report['codexRunAttempts'], 2)

    def test_mutating_verification_is_not_counted_as_task_success(self):
        self.profile['argv'] = [sys.executable, '-B', '-c', 'from pathlib import Path; Path("app.py").write_text("modified by check")']
        (self.base / 'check.json').write_text(json.dumps(self.profile))
        with mock.patch.object(runner.capture, 'run_codex_jsonl', side_effect=self.capture), mock.patch.object(runner.evaluation, 'VERIFICATION_QUIESCENCE_SECONDS', 0):
            report = runner.run(self.args('--live'))
        self.assertEqual(report['baselineVerifiedPassed'], 0)
        self.assertEqual(report['endToEndHarnessPassed'], 0)
        self.assertFalse(report['pairs'][0]['arms']['baseline']['verification']['workspaceUnchanged'])

    def test_input_bounds_preconfigured_projects_and_dirty_codex_homes_are_rejected(self):
        for extra in (('--repetitions', '0'), ('--repetitions', '11'), ('--timeout', 'nan'), ('--timeout', '3601')):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                runner.run(self.args(*extra))
        (self.project / '.harness').mkdir()
        with self.assertRaisesRegex(ValueError, 'raw held-out'):
            runner.run(self.args())
        (self.project / '.harness').rmdir()
        (self.codex_home / 'config.toml').write_text('model = "contaminated"\n')
        with self.assertRaisesRegex(ValueError, 'comparison-changing'):
            runner.run(self.args('--live'))

    def test_generation_cannot_contaminate_the_plain_arm(self):
        def contaminate(**kwargs):
            result = self.capture(**kwargs)
            if '$harness Configure' in kwargs['prompt']:
                (kwargs['repository'].parent / 'baseline/app.py').write_text('VALUE = 9\n')
            return result
        with mock.patch.object(runner.capture, 'run_codex_jsonl', side_effect=contaminate):
            report = runner.run(self.args('--live'))
        self.assertFalse(report['pairs'][0]['isolationPreserved'])
        self.assertEqual(report['generationFailed'], 1)
        self.assertEqual(report['baselineVerifiedPassed'], 0)
        self.assertEqual(report['endToEndHarnessPassed'], 0)
        self.assertEqual(report['codexRunAttempts'], 1)

    def test_task_cannot_contaminate_a_later_peer(self):
        def contaminate(**kwargs):
            result = self.capture(**kwargs)
            if '$harness Configure' not in kwargs['prompt']:
                other = 'harness' if kwargs['repository'].name == 'baseline' else 'baseline'
                (kwargs['repository'].parent / other / 'app.py').write_text('VALUE = 9\n')
            return result
        with mock.patch.object(runner.capture, 'run_codex_jsonl', side_effect=contaminate):
            report = runner.run(self.args('--live'))
        self.assertFalse(report['pairs'][0]['isolationPreserved'])
        self.assertEqual(report['generationPassed'], 1)
        self.assertEqual(report['baselineVerifiedPassed'], 0)
        self.assertEqual(report['endToEndHarnessPassed'], 0)
        self.assertEqual(report['codexRunAttempts'], 2)

    def test_generation_preserves_existing_empty_directories(self):
        (self.project / 'empty-input').mkdir()
        def remove_directory(**kwargs):
            result = self.capture(**kwargs)
            if '$harness Configure' in kwargs['prompt']:
                (kwargs['repository'] / 'empty-input').rmdir()
            return result
        with mock.patch.object(runner.capture, 'run_codex_jsonl', side_effect=remove_directory), mock.patch.object(runner.evaluation, 'VERIFICATION_QUIESCENCE_SECONDS', 0):
            report = runner.run(self.args('--live'))
        self.assertEqual(report['generationFailed'], 1)
        self.assertFalse(report['pairs'][0]['generation']['projectPreserved'])

    def test_unverified_cleanup_stops_all_remaining_calls_and_preserves_denominators(self):
        for phase in ('generation', 'task', 'verification'):
            self.captured.clear()
            def incomplete_cleanup(**kwargs):
                result = self.capture(**kwargs)
                is_generation = '$harness Configure' in kwargs['prompt']
                if (phase == 'generation' and is_generation) or (phase == 'task' and not is_generation):
                    return (*result[:3], False, result[4])
                return result
            verifier = {'result': 'passed', 'passed': False, 'cleanupVerified': False}
            with self.subTest(phase=phase), mock.patch.object(runner.capture, 'run_codex_jsonl', side_effect=incomplete_cleanup), mock.patch.object(runner, 'verify', return_value=verifier) as check:
                report = runner.run(self.args('--live', '--repetitions', '3'))
            self.assertEqual(report['stoppedReason'], 'process-cleanup-unverified')
            self.assertEqual(report['requestedPairs'], 3)
            self.assertEqual(report['generationDenominator'], 3)
            self.assertEqual(len(report['pairs']), 3)
            self.assertEqual(report['baselineVerifiedPassed'], 0)
            self.assertEqual(report['endToEndHarnessPassed'], 0)
            self.assertEqual(report['codexRunAttempts'], 1 if phase == 'generation' else 2)
            self.assertEqual(check.call_count, 1 if phase == 'verification' else 0)
            self.assertEqual(report['pairs'][1]['generation']['state'], 'skipped-cleanup-unverified')

    def test_generation_preserves_user_instruction_newlines_exactly(self):
        original = b'\r\nUser instructions without a final newline'
        (self.project / 'AGENTS.md').write_bytes(original)
        for remove_newlines in (False, True):
            def alter_instructions(**kwargs):
                result = self.capture(**kwargs)
                if remove_newlines and '$harness Configure' in kwargs['prompt']:
                    path = kwargs['repository'] / 'AGENTS.md'
                    path.write_bytes(path.read_bytes().lstrip(b'\r\n'))
                return result
            with self.subTest(remove_newlines=remove_newlines), mock.patch.object(runner.capture, 'run_codex_jsonl', side_effect=alter_instructions), mock.patch.object(runner.evaluation, 'VERIFICATION_QUIESCENCE_SECONDS', 0):
                report = runner.run(self.args('--live'))
            self.assertEqual(report['pairs'][0]['generation']['projectPreserved'], not remove_newlines)

    def test_generated_files_have_separate_snapshot_headroom(self):
        for i in range(28):
            (self.project / f'input-{i}').write_text('')
        with mock.patch.object(runner, 'MAX_FILES', 32), mock.patch.object(runner.capture, 'run_codex_jsonl', side_effect=self.capture), mock.patch.object(runner.evaluation, 'VERIFICATION_QUIESCENCE_SECONDS', 0):
            report = runner.run(self.args('--live'))
        self.assertEqual(report['generationPassed'], 1)
        self.assertEqual(report['endToEndHarnessPassed'], 1)

    def test_output_cannot_contaminate_dedicated_authentication(self):
        with self.assertRaisesRegex(ValueError, 'outside the dedicated'):
            runner.run(self.args('--live', '--output', str(self.codex_home / 'report.json')))

    @unittest.skipIf(os.name == 'nt', 'POSIX link and file-mode checks')
    def test_external_symlinks_are_not_followed_and_copied_credentials_are_private(self):
        (self.project / 'external').symlink_to(self.codex_home, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            runner.run(self.args())
        (self.project / 'external').unlink()
        copied = runner.isolated_home(self.codex_home, self.base / 'copied-auth')
        self.assertEqual((copied / 'auth.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(copied.stat().st_mode & 0o777, 0o700)


if __name__ == '__main__':
    unittest.main()
