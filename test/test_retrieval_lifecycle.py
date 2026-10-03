"""Host-local retrieval choices and revocation fence optional external work."""
import shutil
from unittest import mock
import unittest

from harness_cli import graft, graft_setup, graft_sources, jev, main, workspace_context
from test_cli_jev import CANDIDATES, QUESTION, response
import test_graft_sources as source_fixtures

REPO = source_fixtures.REPO


class RetrievalLifecycleTests(unittest.TestCase):
    setUp = source_fixtures.ExternalSourcesTests.setUp
    execute = source_fixtures.ExternalSourcesTests.execute

    def test_disable_during_primary_query_prevents_a_new_jev_request(self):
        parser = main.build_parser(REPO)
        jev.execute(parser.parse_args(['jev', 'enable', '--project', str(self.root)]), REPO)
        def finish(*args, **kwargs):
            self.assertFalse(self.execute('disable')['enabled'])
            return {'text': 'Original local results', 'hits': 6, 'candidates': CANDIDATES}
        with mock.patch.object(graft, '_invoke', side_effect=finish), \
             mock.patch.object(jev, 'resolve', return_value='fixture-key'), \
             mock.patch.object(jev, '_request', side_effect=response) as request:
            result = self.execute('query', QUESTION)
        request.assert_not_called()
        self.assertEqual(result['text'], 'Original local results')
        self.assertEqual(result['jev']['state'], 'preferences-changed')
        self.assertEqual(jev._read(jev._path(self.root))['callsToday'], 0)

    def test_one_project_hit_still_queries_one_selected_external_hit(self):
        self.execute('add', str(self.external / 'model.py'), '--name', 'library')
        limits = []
        def invoke(source, root, cache, settings, action, **kwargs):
            limits.append(kwargs['limit'])
            return {'text': 'project' if root == self.root else 'library/model.py:1 predict', 'hits': 1}
        with mock.patch.object(graft, '_invoke', side_effect=invoke):
            result = self.execute('query', 'predict', '--limit', '1')
        self.assertEqual(limits, [1, 1])
        self.assertEqual(result['limits']['externalHits'], 1)
        self.assertEqual(result['externalHits'], 1)
        self.assertIn(str(self.external / 'model.py'), result['text'])

    def test_new_jev_request_holds_the_disable_fence_until_completion(self):
        parser = main.build_parser(REPO)
        jev.execute(parser.parse_args(['jev', 'enable', '--project', str(self.root)]), REPO)
        settings_lock = graft._settings_lock
        def bounded_lock(folder):
            lock = settings_lock(folder)
            lock.timeout = .05
            return lock
        def reply(payload):
            with self.assertRaisesRegex(OSError, 'timed out'):
                self.execute('disable')
            self.assertTrue(self.execute('status')['enabled'])
            return response(payload)
        with mock.patch.object(graft, '_settings_lock', side_effect=bounded_lock), \
             mock.patch.object(graft, '_invoke', return_value={'text': 'local', 'hits': 6, 'candidates': CANDIDATES}), \
             mock.patch.object(jev, 'resolve', return_value='fixture-key'), \
             mock.patch.object(jev, '_request', side_effect=reply):
            self.assertEqual(self.execute('query', QUESTION)['jev']['state'], 'observed')
        self.assertFalse(self.execute('disable')['enabled'])

    def test_full_output_skips_external_reads_and_indexing(self):
        self.execute('add', str(self.external / 'model.py'), '--name', 'library')
        with mock.patch.object(graft, '_invoke', return_value={'text': 'P' * 512, 'hits': 6}) as invoke, \
             mock.patch.object(graft_sources, 'collect', side_effect=AssertionError('No hidden retrieval work')):
            result = self.execute('query', 'predict', '--max-chars', '512')
        invoke.assert_called_once()
        self.assertEqual(result['text'], 'P' * 512)
        self.assertEqual(result['externalSkipped'], 'output-budget-exhausted')
        self.assertFalse(result['externalDisplayed'])
        self.assertNotIn('externalHits', result)

    def test_shared_home_and_same_project_path_do_not_share_host_choices(self):
        with mock.patch.object(workspace_context, 'probe', return_value='not-applicable'):
            workspace_context.refresh(self.root, ['codex'])
        graft._record_skill(self.root)
        self.execute('add', str(self.external / 'model.py'), '--name', 'library')
        original = graft.storage(self.root)
        before = (original / 'settings.json').read_bytes()
        with mock.patch.object(graft, 'host_key', return_value='new-host'):
            self.assertNotEqual(graft.storage(self.root), original)
            self.assertFalse(self.execute('status')['enabled'])
            with mock.patch.object(graft.shutil, 'which', return_value='/new-node'), \
                 mock.patch.object(graft, '_invoke', return_value={}) as invoke:
                self.execute('enable', '--package', str(self.base / 'new-package'))
            settings = invoke.call_args.args[3]
            self.assertEqual(settings['node'], '/new-node')
            self.assertEqual(settings['package'], str(self.base / 'new-package'))
            self.assertNotIn('externalSources', settings)
            self.execute('disable')
            self.assertEqual(graft.automatic(self.root, REPO)['state'], 'disabled')
        self.assertEqual((original / 'settings.json').read_bytes(), before)
        self.assertTrue(self.execute('status')['enabled'])

    def test_legacy_opt_out_survives_without_importing_executables_or_sources(self):
        self.execute('add', str(self.external / 'model.py'), '--name', 'library')
        self.execute('disable')
        current = graft.storage(self.root)
        legacy = graft.legacy_storage(self.root) / 'settings.json'
        legacy.write_bytes((current / 'settings.json').read_bytes())
        before = legacy.read_bytes(), legacy.stat().st_mtime_ns
        shutil.rmtree(current)
        with mock.patch.object(graft, '_invoke', side_effect=AssertionError('No implicit enable')):
            self.assertEqual(graft.automatic(self.root, REPO)['state'], 'disabled')
        with mock.patch.object(graft.shutil, 'which', return_value='/new-node'), \
             mock.patch.object(graft, '_invoke', return_value={}) as invoke:
            self.execute('enable', '--package', str(self.base / 'new-package'))
        settings = invoke.call_args.args[3]
        self.assertNotIn('externalSources', settings)
        self.assertEqual(settings['node'], '/new-node')
        self.assertEqual((legacy.read_bytes(), legacy.stat().st_mtime_ns), before)

    def test_automatic_runtime_packages_are_prepared_separately_per_host(self):
        with mock.patch.object(workspace_context, 'probe', return_value='not-applicable'):
            workspace_context.refresh(self.root, ['codex'])
        graft._record_skill(self.root)
        homes = []
        def prepare(home, version):
            homes.append(home)
            return home / 'node', home / 'package'
        with mock.patch.object(graft_setup, 'prepare', side_effect=prepare), \
             mock.patch.object(graft.shutil, 'which', side_effect=lambda value: str(value)), \
             mock.patch.object(graft, '_invoke', return_value={}):
            for host in ('host-a', 'host-b'):
                with mock.patch.object(graft, 'host_key', return_value=host):
                    graft.automatic(self.root, REPO)
        self.assertEqual(homes, [graft.home() / 'hosts' / host for host in ('host-a', 'host-b')])
        self.assertNotEqual(homes[0], homes[1])

    def test_legacy_jev_opt_out_does_not_reenable_during_init(self):
        parser = main.build_parser(REPO)
        for action in ('enable', 'disable'):
            jev.execute(parser.parse_args(['jev', action, '--project', str(self.root)]), REPO)
        current = jev._path(self.root)
        legacy = graft.legacy_storage(self.root) / 'jev/state.json'
        legacy.parent.mkdir()
        legacy.write_bytes(current.read_bytes())
        before = legacy.read_bytes(), legacy.stat().st_mtime_ns
        shutil.rmtree(current.parent)
        with mock.patch.object(jev, '_request', side_effect=AssertionError('No API')):
            self.assertEqual(jev.automatic(self.root, REPO)['mode'], 'off')
        self.assertFalse(current.exists())
        self.assertEqual((legacy.read_bytes(), legacy.stat().st_mtime_ns), before)
        jev.execute(parser.parse_args(['jev', 'enable', '--project', str(self.root)]), REPO)
        self.assertEqual(jev._read(current)['mode'], 'shadow')


if __name__ == '__main__':
    unittest.main()
