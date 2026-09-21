"""Optional retrieval cannot take ownership of existing project instructions."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from harness_cli import graft, main

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
        self.assertFalse((self.root / '.harness').exists())

    def test_repeat_enable_is_noop_for_settings_and_skill(self):
        self.enable()
        files = [self.root / graft.SKILL_PATH, graft.storage(self.root) / 'settings.json']
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in files]
        self.enable()
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in files])
        self.run_command('disable')
        self.assertFalse(files[0].exists())
