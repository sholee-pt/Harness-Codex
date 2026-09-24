"""Optional retrieval cannot take ownership of existing project instructions."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from harness_cli import graft, graft_setup, jev, main, project
import test_cli_project as project_fixtures

REPO = Path(__file__).resolve().parents[1]


class GraftTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / 'project'
        self.root.mkdir()
        environment = mock.patch.dict(os.environ, {'HARNESS_GRAFT_HOME': str(Path(directory.name) / 'storage')})
        environment.start()
        self.addCleanup(environment.stop)

    def run_command(self, *arguments):
        args = main.build_parser(REPO).parse_args(['graft', *arguments, '--project', str(self.root), '--json'])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            graft.run(args, REPO)
        return json.loads(output.getvalue())

    def enable(self):
        with mock.patch.object(graft.shutil, 'which', return_value='/node'), mock.patch.object(graft, '_invoke', return_value={'adapter': graft.OWNER}):
            return self.run_command('enable', '--package', str(self.root / 'dependency'))

    def test_status_and_disabled_query_never_spawn_or_write(self):
        with mock.patch.object(graft.subprocess, 'Popen', side_effect=AssertionError('Must stay offline')):
            self.assertFalse(self.run_command('status')['enabled'])
            with self.assertRaisesRegex(ValueError, 'disabled'):
                self.run_command('query', 'where is routing')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_bare_command_reports_status_without_starting_dependency(self):
        args = main.build_parser(REPO).parse_args(['graft'])
        args.project = self.root
        with mock.patch.object(graft.subprocess, 'Popen', side_effect=AssertionError('Must stay offline')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(graft.run(args, REPO), 0)
        self.assertIn('Graft: status', output.getvalue())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_limits_do_not_create_opt_in_receipt(self):
        for timeout in ('0', '241', 'nan'):
            with self.assertRaisesRegex(ValueError, 'limits'):
                self.run_command('enable', '--package', str(self.root), '--timeout', timeout)
        self.assertFalse(graft.storage(self.root).exists())

    def test_timeout_kills_child_and_removes_only_its_lock(self):
        package = self.root / 'package'
        package.mkdir()
        (package / 'package.json').write_text(json.dumps({'name': '@nanonets/graft', 'version': graft.PACKAGE_VERSION}))
        cache = graft.storage(self.root) / 'graph'
        lock = cache / '.cache/.sync.lock'
        lock.parent.mkdir(parents=True)
        for owner in (1234, 5678):
            with self.subTest(owner=owner):
                lock.write_text(json.dumps({'pid': owner}))
                process = mock.MagicMock(pid=1234)
                process.communicate.side_effect = [graft.subprocess.TimeoutExpired('node', 1), ('', '')]
                with mock.patch.object(graft.subprocess, 'Popen') as start:
                    start.return_value.__enter__.return_value = process
                    with self.assertRaises(graft.subprocess.TimeoutExpired):
                        graft._invoke(REPO, self.root, cache, {'package': str(package), 'node': 'node'}, 'query', timeout=1)
                process.kill.assert_called_once()
                self.assertEqual(process.communicate.call_count, 2)
                self.assertEqual(lock.exists(), owner != 1234)

    def test_enable_disable_preserve_harness_and_modified_skill(self):
        (self.root / 'AGENTS.md').write_bytes(b'User instructions\r\n')
        self.enable()
        self.assertTrue(self.run_command('status')['skillInstalled'])
        skill = self.root / graft.SKILL_PATH
        skill.write_bytes(b'User changed retrieval skill')
        with self.assertRaisesRegex(ValueError, 'modified'):
            self.enable()
        self.run_command('disable')
        self.assertEqual(skill.read_bytes(), b'User changed retrieval skill')
        self.assertEqual((self.root / 'AGENTS.md').read_bytes(), b'User instructions\r\n')

    def test_opt_in_does_not_change_existing_harness_contract(self):
        from test_harness_tools import harness_apply, minimal_plan, validate_harness
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        self.enable()
        report = validate_harness.Validator(self.root).run()
        self.assertTrue(report['valid'], report['errors'])
        self.run_command('disable')
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_unowned_skill_is_never_adopted_even_if_identical(self):
        skill = self.root / graft.SKILL_PATH
        skill.parent.mkdir(parents=True)
        skill.write_text(graft.SKILL, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'user-owned'):
            self.enable()
        self.run_command('disable')
        self.assertTrue(skill.is_file())
        with self.assertRaisesRegex(ValueError, 'user-owned'):
            self.enable()
        self.assertFalse((self.root / '.harness').exists())

    def test_repeat_enable_is_noop_for_settings_and_skill(self):
        self.enable()
        files = [self.root / graft.SKILL_PATH, graft.storage(self.root) / 'settings.json']
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in files]
        self.enable()
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in files])
        self.run_command('disable')
        self.assertFalse(files[0].exists())

    def test_disable_during_build_wins_and_does_not_install_skill(self):
        def build(*args, **kwargs):
            self.run_command('disable')
            return {}
        with mock.patch.object(graft.shutil, 'which', return_value='/node'), mock.patch.object(graft, '_invoke', side_effect=build):
            result = self.run_command('enable', '--package', str(self.root))
        self.assertEqual(result['state'], 'superseded')
        self.assertFalse(self.run_command('status')['enabled'])
        self.assertFalse((self.root / graft.SKILL_PATH).exists())
        self.assertEqual(graft.automatic(self.root, REPO)['state'], 'disabled')

    def test_skill_created_during_build_is_preserved_without_adoption(self):
        def build(*args, **kwargs):
            skill = self.root / graft.SKILL_PATH
            skill.parent.mkdir(parents=True)
            skill.write_text(graft.SKILL, encoding='utf-8')
            return {}
        with mock.patch.object(graft.shutil, 'which', return_value='/node'), mock.patch.object(graft, '_invoke', side_effect=build):
            with self.assertRaisesRegex(ValueError, 'user-owned'):
                self.run_command('enable', '--package', str(self.root))
        self.assertFalse(self.run_command('status')['enabled'])
        self.assertEqual((self.root / graft.SKILL_PATH).read_text(encoding='utf-8'), graft.SKILL)

    def test_disable_then_new_enable_fences_the_earlier_build(self):
        self.enable()
        def build(*args, **kwargs):
            self.run_command('disable')
            self.enable()
            return {}
        with mock.patch.object(graft.shutil, 'which', return_value='/node'), mock.patch.object(graft, '_invoke', side_effect=build):
            result = self.run_command('enable', '--package', str(self.root / 'obsolete-package'))
        self.assertEqual(result['state'], 'superseded')
        self.assertTrue(self.run_command('status')['enabled'])
        self.assertNotIn('obsolete-package', (graft.storage(self.root) / 'settings.json').read_text())

    def test_automatic_reuses_enabled_setup_without_index_or_network_work(self):
        self.enable()
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.parent.rglob('*') if p.is_file()}
        with mock.patch.object(graft_setup, 'prepare', side_effect=AssertionError('No setup')), mock.patch.object(graft, '_invoke', side_effect=AssertionError('No rebuild')):
            self.assertEqual(graft.automatic(self.root, REPO)['state'], 'enabled')
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.parent.rglob('*') if p.is_file()})

    def test_explicit_disable_before_first_init_is_remembered(self):
        self.run_command('disable')
        with mock.patch.object(graft_setup, 'prepare', side_effect=AssertionError('Opt-out')):
            self.assertEqual(graft.automatic(self.root, REPO)['state'], 'disabled')
        self.enable()
        self.assertTrue(self.run_command('status')['enabled'])

    def test_previous_version_receipts_keep_their_enabled_or_disabled_choice(self):
        self.enable()
        path = graft.storage(self.root) / 'settings.json'
        value = json.loads(path.read_text())
        value.pop('disabledByUser')
        value.pop('skillOwned')
        with mock.patch.object(graft_setup, 'prepare', side_effect=AssertionError('No migration')):
            for enabled in (True, False):
                value['enabled'] = enabled
                path.write_text(json.dumps(value))
                before = path.read_bytes(), path.stat().st_mtime_ns
                self.assertEqual(graft.automatic(self.root, REPO)['state'], 'enabled' if enabled else 'disabled')
                self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))

    def test_enable_without_package_prepares_once_and_creates_native_skill(self):
        with mock.patch.object(graft_setup, 'prepare', return_value=(Path('/node'), self.root / 'package')) as setup:
            with mock.patch.object(graft.shutil, 'which', return_value='/node'), mock.patch.object(graft, '_invoke', return_value={'adapter': graft.OWNER}):
                result = graft.automatic(self.root, REPO)
        setup.assert_called_once()
        self.assertTrue(result['enabled'])
        self.assertTrue((self.root / graft.SKILL_PATH).is_file())

    def test_project_default_skip_and_dependency_failure_do_not_block_configuration(self):
        parser = main.build_parser(REPO)
        with mock.patch.object(graft, 'automatic', side_effect=ValueError('offline')) as automatic:
            for command in (['init', '--dry-run'], ['init', '--install-only'], ['config']):
                project._configure_retrieval(parser.parse_args(command), REPO, self.root)
            automatic.assert_not_called()
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                project._configure_retrieval(parser.parse_args(['init']), REPO, self.root)
            automatic.assert_called_once_with(self.root, REPO, disabled=False)
            self.assertIn('ordinary code search', errors.getvalue())


class ProjectGraftTests(unittest.TestCase):
    setUp = project_fixtures.ProjectCliTests.setUp
    run_cli = project_fixtures.ProjectCliTests.run_cli

    def test_successful_and_existing_init_prepare_retrieval_without_regeneration(self):
        os.environ['FAKE_CODEX_MODE'] = 'generate'
        with mock.patch.object(graft, 'automatic', return_value={'state': 'enabled'}) as activate:
            code, out, err = self.run_cli('init', '--retrieval', 'auto')
            self.assertEqual(code, 0, err)
            activate.assert_called_once_with(self.root, REPO, disabled=False)
            self.codex.reset_mock()
            before = project_fixtures.snapshot(self.root)
            code, out, err = self.run_cli('init', '--retrieval', 'auto')
            self.assertEqual(code, 0, err)
            self.assertEqual(activate.call_count, 2)
            self.codex.assert_not_called()
            self.assertEqual(before, project_fixtures.snapshot(self.root))

    def test_failed_configuration_never_starts_retrieval_setup(self):
        os.environ['FAKE_CODEX_MODE'] = 'corrupt'
        with mock.patch.object(graft, 'automatic') as activate, mock.patch.object(jev, 'automatic') as advice:
            code, out, err = self.run_cli('init', '--retrieval', 'auto')
        self.assertNotEqual(code, 0)
        activate.assert_not_called()
        advice.assert_not_called()
