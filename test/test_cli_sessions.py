"""Native conversation transport and the shared project configuration boundary."""
import concurrent.futures
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

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
            self.assertEqual(out, '')
            self.assertIn('deprecated', err)
            argv = json.loads(f.log.read_text())['argv']
            self.assertEqual(argv[:2], ['--cd', str(f.root)])
            self.assertEqual(argv[2:], ['--', 'literal $HOME; \"task\"'])
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
            self.assertEqual(argv[2:], suffix)
            self.assertNotIn('$project-harness', ' '.join(argv))
        self.assertEqual(fixture.snapshot(f.root), before)

    def test_compat_resume_leaves_project_validation_to_explicit_doctor(self):
        f = self.fixture
        self.assertNotEqual(f.run_cli('resume', '--last', 'id')[0], 0)
        self.assertFalse(f.log.exists())
        (f.root / '.harness/manifest.json').write_text('{}')
        self.assertNotEqual(f.run_cli('doctor')[0], 0)
        self.assertFalse(f.log.exists())
        self.assertEqual(f.run_cli('resume')[0], 0)
        self.assertEqual(json.loads(f.log.read_text())['argv'][2:], ['resume'])

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
        self.assertEqual(json.loads(f.log.read_text())['argv'][2:], ['resume', '--', 'native-session'])
        self.assertIn(original, (f.root / '.harness/GUIDE.md').read_text())

    def test_reload_is_explicit_and_follows_session_id(self):
        f = self.fixture
        code, out, err = f.run_cli('resume', 'native-session', '--reload-harness')
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(f.log.read_text())['argv'][2:], ['resume', '--', 'native-session'])
        self.assertIn('no longer inserts a user turn', err)

    def test_compat_resume_preserves_drift_while_doctor_rejects_managed_edits(self):
        f = self.fixture
        (f.root / 'pyproject.toml').unlink()
        manifest = (f.root / '.harness/manifest.json').read_bytes()
        self.assertEqual(f.run_cli('resume', 'native-session')[0], 0)
        self.assertEqual((f.root / '.harness/manifest.json').read_bytes(), manifest)
        self.assertFalse(project._report(fixture.REPO_ROOT, f.root)[1]['valid'])
        f.log.unlink()
        (f.root / '.agents/skills/project-harness/SKILL.md').write_text('tampered')
        self.assertEqual(f.run_cli('doctor')[0], 1)
        self.assertFalse(f.log.exists())

    def test_concurrent_native_launches_do_not_write_project_configuration(self):
        f = self.fixture
        before = fixture.snapshot(f.root)
        def launch(index):
            arguments = ['resume', '--last'] if index == 2 else ['new', 'literal task']
            args = f.parser.parse_args([*arguments, '--project', str(f.root)])
            return project._compat_conversation(args)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            self.assertEqual(list(executor.map(launch, range(3))), [0, 0, 0])
        self.assertEqual(fixture.snapshot(f.root), before)

    def test_project_dir_aliases_and_one_guide_preserve_user_content(self):
        from harness_cli import main, project_guide
        f = self.fixture
        for flag in ('--project-dir', '--project_dir'):
            args = main.build_parser(fixture.REPO_ROOT).parse_args(['resume', 'id', flag, str(f.root)])
            self.assertEqual(args.project, f.root)
            self.assertEqual(args.session_id, 'id')
        guide = f.root / project_guide.PATH
        before = (guide.read_bytes(), guide.stat().st_mtime_ns)
        for _ in range(2):
            self.assertEqual(f.run_cli('resume', 'id')[0], 0)
            self.assertEqual((guide.read_bytes(), guide.stat().st_mtime_ns), before)
        guide.write_text('User-maintained guide\n', encoding='utf-8')
        user = (guide.read_bytes(), guide.stat().st_mtime_ns)
        self.assertEqual(f.run_cli('resume', 'id')[0], 0)
        self.assertEqual((guide.read_bytes(), guide.stat().st_mtime_ns), user)
        self.assertEqual(f.run_cli('remove', '--yes', tty=False)[0], 0)
        self.assertEqual((guide.read_bytes(), guide.stat().st_mtime_ns), user)
        self.assertEqual(list(f.root.rglob('GUIDE*.md')), [guide])

    def test_owned_guide_participates_in_removal_rollback_and_apply(self):
        from harness_cli import lifecycle, project_guide
        f = self.fixture
        before = fixture.snapshot(f.root)
        self.assertEqual(f.run_cli('remove', '--dry-run', tty=False)[0], 0)
        self.assertEqual(fixture.snapshot(f.root), before)
        self.assertTrue(project_guide.owned(f.root))
        real_replace = lifecycle.os.replace
        failed = False
        def interrupt_after_guide(source, destination):
            nonlocal failed
            if Path(source) == f.root / '.harness/manifest.json' and not failed:
                failed = True
                raise OSError('Injected failure after guide moved to backup')
            return real_replace(source, destination)
        with mock.patch.object(lifecycle.os, 'replace', side_effect=interrupt_after_guide):
            self.assertEqual(f.run_cli('remove', '--yes', tty=False)[0], 1)
        self.assertTrue(failed)
        self.assertEqual(fixture.snapshot(f.root), before)
        self.assertEqual(f.run_cli('remove', '--yes', tty=False)[0], 0)
        self.assertFalse((f.root / project_guide.PATH).exists())


if __name__ == '__main__':
    unittest.main()
