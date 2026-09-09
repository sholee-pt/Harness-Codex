"""Native conversation transport and the shared project configuration boundary."""
import concurrent.futures
import json
import sys
import unittest

import test_cli_project as fixture
from harness_cli import project


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.ProjectCliTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.generate()

    def test_new_task_and_legacy_alias_preserve_the_canonical_project(self):
        f = self.fixture
        before = fixture.snapshot(f.root)
        for name in ('new', 'new', 'start'):
            code, out, err = f.run_cli(name, 'literal $HOME; \"task\"')
            self.assertEqual(code, 0, err)
            self.assertIn('sha256:', out)
            self.assertEqual('deprecated' in err, name == 'start')
            argv = json.loads(f.log.read_text())['argv']
            self.assertEqual(argv[:2], ['--cd', str(f.root)])
            self.assertTrue(argv[2].endswith('literal $HOME; \"task\"'))
        self.assertEqual(fixture.snapshot(f.root), before)

    def test_resume_picker_last_and_literal_identifier_use_current_harness(self):
        f = self.fixture
        before = fixture.snapshot(f.root)
        for options, suffix in [((), ['resume']), (('--last',), ['resume', '--last']),
                                (('--', '--model=literal-name'), ['resume', '--', '--model=literal-name'])]:
            code, out, err = f.run_cli('resume', *options)
            self.assertEqual(code, 0, err)
            argv = json.loads(f.log.read_text())['argv']
            self.assertEqual(argv[:2], ['--cd', str(f.root)])
            self.assertIn('Re-read the current project harness', argv[2])
            self.assertIn(project.harness_revision(f.root), argv[2])
            self.assertEqual(argv[3:], suffix)
        self.assertEqual(fixture.snapshot(f.root), before)

    def test_resume_rejects_invalid_selection_and_corrupt_project_before_launch(self):
        f = self.fixture
        for options in [('--last', 'id'), ('bad\nidentifier',), ('x' * 1025,)]:
            self.assertNotEqual(f.run_cli('resume', *options)[0], 0)
            self.assertFalse(f.log.exists())
        (f.root / '.harness/manifest.json').write_text('{}')
        self.assertNotEqual(f.run_cli('resume')[0], 0)
        self.assertFalse(f.log.exists())

    def test_fingerprint_ignores_formatting_and_runtime_files_but_detects_configuration(self):
        f = self.fixture
        path = f.root / '.harness/manifest.json'
        content = json.loads(path.read_text())
        original = project.harness_revision(f.root)
        path.write_text(json.dumps(content, sort_keys=True, indent=4), encoding='utf-8')
        runtime = f.root / '.harness/sessions/example'
        runtime.mkdir(parents=True)
        (runtime / 'session.json').write_text('{"fixture":true}')
        self.assertEqual(project.harness_revision(f.root), original)
        content['generator']['version'] = '9.8'
        path.write_text(json.dumps(content), encoding='utf-8')
        changed = project.harness_revision(f.root)
        self.assertNotEqual(changed, original)
        self.assertEqual(f.run_cli('resume', 'native-session')[0], 0)
        self.assertIn(changed, json.loads(f.log.read_text())['argv'][2])

    def test_concurrent_native_launches_do_not_write_project_configuration(self):
        f = self.fixture
        before = fixture.snapshot(f.root)
        command = [sys.executable, '-B', str(f.fake)]
        def launch(index):
            project._check_existing(fixture.REPO_ROOT, f.root, required=True)
            return project._launch(command, f.root, project._work_prompt(None), resume=index == 2, last=index == 2)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            self.assertEqual(list(executor.map(launch, range(3))), [0, 0, 0])
        self.assertEqual(fixture.snapshot(f.root), before)


if __name__ == '__main__':
    unittest.main()
