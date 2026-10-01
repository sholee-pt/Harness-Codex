"""Retrieval advice cannot change baseline results, permissions or project contracts."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from harness_cli import graft, graft_setup, jev, jev_client, main, project
import test_cli_project as project_fixtures

REPO = Path(__file__).resolve().parents[1]
QUESTION = 'Where is the validation of incoming requests implemented?'
CANDIDATES = [{'id': f'c{i}', 'text': f'candidate source function_{i}'} for i in range(6)]


def response(payload):
    return {'model': payload['model'], 'answers': {f'c{i}': {'type': 'noul', 'noul': p}
            for i, p in enumerate((.1, .5, .9, .4, .8, .2))}, 'usage': {'input_tokens': 611, 'output_tokens': 12}}


class JevTests(unittest.TestCase):
    def test_first_state_save_failure_can_retry_without_claiming_user_directory(self):
        args = main.build_parser(REPO).parse_args(['graft', 'enable', '--package', str(self.root), '--project', str(self.root)])
        with mock.patch.object(graft.shutil, 'which', return_value='/node'), mock.patch.object(graft, '_invoke', return_value={}):
            graft.execute(args, REPO)
        with mock.patch.object(graft.os, 'replace', side_effect=OSError('initial-save')):
            with self.assertRaisesRegex(OSError, 'initial-save'):
                self.command('enable')
        self.assertFalse(jev._path(self.root).parent.exists())
        self.assertEqual(self.command('enable')['mode'], 'shadow')

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / 'project'
        self.root.mkdir()
        patch = mock.patch.dict(os.environ, {'HARNESS_GRAFT_HOME': str(Path(directory.name) / 'local'), 'HARNESS_CREDENTIAL_HOME': str(Path(directory.name) / 'credentials'), 'TYPESAFE_API_KEY': 'fixture-key'})
        patch.start()
        self.addCleanup(patch.stop)

    def command(self, *arguments):
        args = main.build_parser(REPO).parse_args(['jev', *arguments, '--project', str(self.root), '--json'])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            jev.run(args, REPO)
        return json.loads(output.getvalue())

    def enable(self, *arguments):
        args = main.build_parser(REPO).parse_args(['graft', 'enable', '--package', str(self.root), '--project', str(self.root)])
        with mock.patch.object(graft.shutil, 'which', return_value='/node'), mock.patch.object(graft, '_invoke', return_value={}):
            graft.execute(args, REPO)
        return self.command('enable', *arguments)

    def advise(self, question=QUESTION, candidates=CANDIDATES):
        return jev.advise(self.root, question, candidates)

    def snapshot(self):
        return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.parent.rglob('*') if p.is_file()}

    def test_default_off_status_has_no_writes_or_network(self):
        with mock.patch.object(jev, '_request', side_effect=AssertionError('No API')):
            self.assertEqual(self.command('status')['mode'], 'off')
            self.assertEqual(self.advise()['state'], 'disabled')
        self.assertEqual(self.snapshot(), {})

    def test_automatic_setup_waits_for_graft_without_creating_state(self):
        with mock.patch.object(jev, '_request', side_effect=AssertionError('No API')):
            self.assertEqual(jev.automatic(self.root, REPO)['state'], 'unavailable')
        self.assertEqual(self.snapshot(), {})

    def test_automatic_enable_without_key_then_use_key_without_reenabling(self):
        args = main.build_parser(REPO).parse_args(['graft', 'enable', '--package', str(self.root), '--project', str(self.root)])
        with mock.patch.object(graft.shutil, 'which', return_value='/node'), mock.patch.object(graft, '_invoke', return_value={}):
            graft.execute(args, REPO)
        with mock.patch.dict(os.environ, {'TYPESAFE_API_KEY': ''}), mock.patch.object(jev, '_request') as request:
            result = jev.automatic(self.root, REPO)
            self.assertEqual(result['mode'], 'shadow')
            self.assertFalse(result['keyAvailable'])
            self.assertEqual(self.advise()['state'], 'key-unavailable')
            request.assert_not_called()
        with mock.patch.object(jev, '_request', side_effect=response) as request:
            self.assertEqual(self.advise()['state'], 'observed')
            request.assert_called_once()

    def test_automatic_reuse_preserves_preferences_cache_and_explicit_opt_out(self):
        self.enable('--mode', 'suggest', '--daily-calls', '7', '--model', 'jev-1.14.0')
        with mock.patch.object(jev, '_request', side_effect=response):
            self.advise()
        for action, expected in ((None, 'suggest'), ('disable', 'off'), ('clear', 'off')):
            if action:
                self.command(action, '--yes')
            before = self.snapshot()
            with mock.patch.object(jev, '_request', side_effect=AssertionError('No API')):
                result = jev.automatic(self.root, REPO)
            self.assertEqual(result['mode'], expected)
            self.assertEqual(result['dailyCallLimit'], 7)
            self.assertEqual(result['model'], 'jev-1.14.0')
            self.assertEqual(before, self.snapshot())

    def test_explicit_enable_requires_graft_and_preserves_unknown_directory(self):
        with self.assertRaisesRegex(ValueError, 'Graft'):
            self.command('enable')
        self.enable()
        path = jev._path(self.root)
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'Unowned'):
            self.command('enable')

    def test_repeat_enable_status_and_ineligible_queries_are_noops(self):
        self.enable()
        before = self.snapshot()
        with mock.patch.object(jev, '_request', side_effect=AssertionError('No API')):
            self.command('enable')
            self.command('status')
            for question, candidates in [('hi', CANDIDATES), (QUESTION, CANDIDATES[:5]),
                                         (QUESTION, [{'id': f'c{i}', 'text': 'same'} for i in range(6)])]:
                self.assertEqual(self.advise(question, candidates)['state'], 'ineligible')
        self.assertEqual(before, self.snapshot())

    def test_missing_key_never_starts_provider_or_writes_state(self):
        self.enable()
        before = self.snapshot()
        with mock.patch.dict(os.environ, {'TYPESAFE_API_KEY': ''}), mock.patch.object(jev, '_request') as request:
            self.assertEqual(self.advise()['state'], 'key-unavailable')
            request.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def test_batch_cache_and_local_privacy(self):
        self.enable()
        project_before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        with mock.patch.object(jev, '_request', side_effect=response) as request:
            first = self.advise()
            self.assertEqual(self.advise()['state'], 'cached')
            request.assert_called_once()
            self.assertEqual(len(request.call_args.args[0]['questions']), 6)
        self.assertEqual(first['suggestedOrder'], ['c2', 'c4', 'c1', 'c3', 'c0', 'c5'])
        self.assertEqual(first['judgments'], ['no', 'abstain', 'yes', 'abstain', 'yes', 'no'])
        state = jev._read(jev._path(self.root))
        self.assertEqual(state['metrics']['inputTokens'], 611)
        self.assertEqual(state['metrics']['cacheHits'], 1)
        stored = jev._path(self.root).read_text()
        for private in (QUESTION, 'candidate source', 'fixture-key', str(self.root)):
            self.assertNotIn(private, stored)
        self.assertEqual(project_before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()})

    def test_payload_model_and_source_changes_invalidate_cache(self):
        self.enable()
        with mock.patch.object(jev, '_request', side_effect=response) as request:
            self.advise()
            self.advise(QUESTION + ' Include errors.')
            self.advise(candidates=[{**v, 'text': v['text'] + ' changed'} for v in CANDIDATES])
            self.command('enable', '--model', 'jev-1.14.0')
            self.advise()
            self.assertEqual(request.call_count, 4)
        self.assertEqual(self.command('status')['cachedQueries'], 1)

    def test_expired_cache_requires_new_observation(self):
        self.enable()
        with mock.patch.object(jev, '_request', side_effect=response) as request:
            self.advise()
            state = jev._read(jev._path(self.root))
            for item in state['cache'].values():
                item['time'] -= jev.TTL
            graft._save(jev._path(self.root), state)
            self.assertEqual(self.advise()['state'], 'observed')
            self.assertEqual(request.call_count, 2)

    def test_timeout_reserves_budget_and_backs_off_without_retries(self):
        self.enable()
        with mock.patch.object(jev, '_request', side_effect=subprocess.TimeoutExpired('child', 4)) as request:
            self.assertEqual(self.advise()['state'], 'unavailable')
            self.assertEqual(self.advise()['state'], 'cooldown')
            request.assert_called_once()
        state = jev._read(jev._path(self.root))
        self.assertEqual(state['callsToday'], 1)
        self.assertEqual(state['metrics']['failures'], 1)

    def test_forced_provider_exit_releases_lock_and_preserves_reserved_budget(self):
        self.enable()
        script = ('import os, sys, json; from pathlib import Path; from harness_cli import jev; '
                  'jev._request = lambda payload: os._exit(23); '
                  'jev.advise(Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3]))')
        child = subprocess.Popen([sys.executable, '-B', '-c', script, str(self.root), QUESTION, json.dumps(CANDIDATES)], cwd=REPO)
        self.assertEqual(child.wait(timeout=10), 23)
        self.assertEqual(jev._read(jev._path(self.root))['callsToday'], 1)
        self.assertEqual(self.command('disable')['mode'], 'off')
        # A previous release's dead PID receipt is also recoverable; it is not
        # permission to take a lock from a still-running legacy process.
        legacy = jev._path(self.root).parent / '.install.lock'
        legacy.write_text(str(child.pid))
        self.assertEqual(self.command('enable')['mode'], 'shadow')
        self.assertFalse(legacy.exists())
        legacy.write_text(str(os.getpid()))
        with self.assertRaisesRegex(ValueError, 'legacy Jev request'):
            self.command('disable')
        self.assertTrue(legacy.exists())

    def test_daily_budget_and_busy_lock_fall_back(self):
        self.enable('--daily-calls', '1')
        with mock.patch.object(jev, '_request', side_effect=response) as request:
            self.advise()
            self.assertEqual(self.advise(QUESTION + ' Different task.')['state'], 'budget-exhausted')
            lock = jev._path(self.root).parent / '.install.lock'
            lock.write_text('another owner')
            before = self.snapshot()
            self.assertEqual(self.advise()['state'], 'unavailable')
            self.assertEqual(before, self.snapshot())
            request.assert_called_once()

    def test_invalid_responses_never_produce_advice(self):
        payload = jev._payload(QUESTION, CANDIDATES, jev.MODEL)
        changes = [lambda v: v.update(model='unexpected'), lambda v: v['answers'].pop('c2'),
                   lambda v: v['answers']['c0'].update(noul=float('nan')),
                   lambda v: v['answers']['c0'].update(noul=True),
                   lambda v: v['usage'].update(input_tokens=-1)]
        for change in changes:
            value = response(payload)
            change(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                jev._answers(value, payload)

    def test_corrupt_state_is_preserved_and_does_not_block_search(self):
        self.enable()
        path = jev._path(self.root)
        for data in ('{broken', json.dumps({'owner': jev.OWNER, 'policy': jev.POLICY, 'mode': []})):
            path.write_text(data)
            before = self.snapshot()
            with mock.patch.object(jev, '_request') as request:
                self.assertFalse(jev.enabled(self.root))
                self.assertEqual(self.advise()['state'], 'unavailable')
                with self.assertRaises(ValueError):
                    jev.automatic(self.root, REPO)
                request.assert_not_called()
            self.assertEqual(before, self.snapshot())

    def test_human_labels_compare_ranking_without_self_improvement(self):
        self.enable()
        with mock.patch.object(jev, '_request', side_effect=response):
            identity = self.advise()['queryId']
        report = self.command('feedback', '--query-id', identity, '--relevant', 'c2')
        self.assertAlmostEqual(report['baselineMRR'], 1 / 3)
        self.assertEqual(report['suggestedMRR'], 1)
        self.assertFalse(report['automaticImprovement'])
        self.assertEqual(report['benefit'], 'not-measured')
        report = self.command('feedback', '--query-id', identity, '--relevant', 'none')
        self.assertEqual(report['labeledQueries'], 1)
        self.assertEqual(report['suggestedMRR'], 0)
        self.command('disable')
        self.assertEqual(self.advise()['state'], 'disabled')
        with self.assertRaisesRegex(ValueError, '--yes'):
            self.command('clear')
        self.assertEqual(self.command('clear', '--yes')['cachedQueries'], 0)

    def test_shadow_and_failure_preserve_text_suggest_keeps_all_hits_and_bound(self):
        self.enable()
        args = main.build_parser(REPO).parse_args(['graft', 'query', QUESTION, '--project', str(self.root)])
        baseline = 'Original Graft result with every candidate.'
        def search(*a, **kw):
            return {'text': baseline, 'hits': 6, 'candidates': CANDIDATES}
        with mock.patch.object(graft, '_invoke', side_effect=search), mock.patch.object(jev, '_request', side_effect=response):
            result = graft.execute(args, REPO)
            self.assertEqual(result['text'], baseline)
            self.assertNotIn('candidates', result)
            self.command('enable', '--mode', 'suggest')
            result = graft.execute(args, REPO)
            self.assertTrue(result['text'].endswith(baseline))
            self.assertIn('3, 5, 2, 4, 1, 6', result['text'])
            baseline = 'x' * 512
            args.max_chars = 512
            self.assertEqual(graft.execute(args, REPO)['text'], baseline)
        with mock.patch.object(graft, '_invoke', side_effect=search), mock.patch.object(jev, 'advise', return_value={'state': 'unavailable'}):
            self.assertEqual(graft.execute(args, REPO)['text'], baseline)


class JevTransportTests(unittest.TestCase):
    def test_fixed_endpoint_no_redirect_and_bounded_read(self):
        response_stream = mock.MagicMock()
        response_stream.__enter__.return_value.read.return_value = b'{"ok": true}'
        with mock.patch.dict(os.environ, {'TYPESAFE_API_KEY': 'fixture'}), mock.patch.object(jev_client.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = response_stream
            self.assertTrue(jev_client.fetch({'state': 'bounded'})['ok'])
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, jev_client.ENDPOINT)
            self.assertEqual(request.get_header('Authorization'), 'Bearer fixture')
            response_stream.__enter__.return_value.read.assert_called_once_with(jev_client.MAX_BYTES + 1)
            self.assertEqual(opener.call_args.args, (jev_client.NoRedirect,))
        with self.assertRaises(ValueError):
            jev_client.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.invalid')

    def test_child_deadline_and_error_redaction(self):
        with mock.patch.object(jev.subprocess, 'run', return_value=mock.Mock(returncode=1, stdout='', stderr='private input')) as run:
            with self.assertRaisesRegex(ValueError, '^Jev unavailable$'):
                jev._request({})
            self.assertEqual(run.call_args.kwargs['timeout'], 4)
            self.assertNotIn('TYPESAFE_API_KEY', repr(run.call_args))
        with mock.patch.object(jev_client.sys, 'stdin', mock.Mock(buffer=io.BytesIO(b'{}'))), mock.patch.object(jev_client, 'fetch', side_effect=ValueError('private')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(jev_client.main(), 1)
            self.assertEqual(output.getvalue(), '')


class ProjectJevTests(unittest.TestCase):
    setUp = project_fixtures.ProjectCliTests.setUp
    run_cli = project_fixtures.ProjectCliTests.run_cli

    def test_fresh_and_existing_init_enable_once_without_api_or_regeneration(self):
        os.environ['FAKE_CODEX_MODE'] = 'generate'
        # The fake configuration command and global which('/node') are distinct
        # executables. Keep host identity stable in this Jev idempotence fixture.
        fingerprint = mock.patch('harness_cli.workspace_context._fingerprint', return_value='stable-fixture-runtime')
        fingerprint.start()
        self.addCleanup(fingerprint.stop)
        with mock.patch.object(graft_setup, 'prepare', return_value=(Path('/node'), self.base / 'package')):
            with mock.patch.object(graft.shutil, 'which', return_value='/node'), mock.patch.object(graft, '_invoke', return_value={}) as build:
                with mock.patch.object(jev, '_request', side_effect=AssertionError('Init cannot call Jev')):
                    code, out, err = self.run_cli('init', '--retrieval', 'auto')
                    self.assertEqual(code, 0, err)
                    self.assertTrue(jev.enabled(self.root))
                    self.assertEqual(jev._read(jev._path(self.root))['mode'], 'shadow')
                    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.base.rglob('*') if p.is_file()}
                    self.codex.reset_mock()
                    code, out, err = self.run_cli('init', '--retrieval', 'auto')
                    self.assertEqual(code, 0, err)
                    self.codex.assert_not_called()
                    build.assert_called_once()
                    self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.base.rglob('*') if p.is_file()})

    def test_preview_install_only_config_and_retrieval_opt_out_never_enable_jev(self):
        parser = main.build_parser(REPO)
        with mock.patch.object(graft, 'automatic', return_value={'state': 'disabled'}), mock.patch.object(jev, 'automatic') as activate:
            for args in (['init', '--dry-run'], ['init', '--install-only'], ['config'], ['init', '--retrieval', 'off'], ['init']):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    project._configure_retrieval(parser.parse_args(args), REPO, self.root)
            activate.assert_not_called()

    def test_jev_setup_failure_does_not_fail_valid_project_configuration(self):
        os.environ['FAKE_CODEX_MODE'] = 'generate'
        with mock.patch.object(graft, 'automatic', return_value={'state': 'enabled'}):
            with mock.patch.object(jev, 'automatic', side_effect=ValueError('Unowned state; preserved')):
                code, out, err = self.run_cli('init', '--retrieval', 'auto')
        self.assertEqual(code, 0, err)
        self.assertIn('Graft and ordinary code search remain available', err)

if __name__ == '__main__':
    unittest.main()
