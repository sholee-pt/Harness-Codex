"""Moving projects must not import another host's sandbox verdict or permissions."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from harness_cli import main, project, workspace_context as context
import test_cli_project as fixtures

REPO = Path(__file__).resolve().parents[1]


class WorkspaceContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'server-a' / 'project'
        self.root.mkdir(parents=True)
        (self.root / 'model.py').write_text('print("fixture")\n')

    def test_moved_mount_maps_recorded_paths_and_keeps_host_verdicts_separate(self):
        with mock.patch.object(context, 'host_key', return_value='a'), mock.patch.object(context, 'probe', return_value='unavailable') as probe:
            context.refresh(self.root, ['codex'])
            before = (self.root / context.PATH).stat().st_mtime_ns
            context.refresh(self.root, ['codex'])
            self.assertEqual(probe.call_count, 1)
            self.assertEqual((self.root / context.PATH).stat().st_mtime_ns, before)
        moved = self.base / 'server-b' / 'project'
        moved.parent.mkdir()
        old = self.root
        shutil.move(str(old), str(moved))
        with mock.patch.object(context, 'host_key', return_value='b'), mock.patch.object(context, 'probe', return_value='available'):
            self.assertEqual(context.report(moved)['sandbox'], 'not-tested')
            context.refresh(moved, ['codex'])
            self.assertEqual(context.report(moved)['sandbox'], 'available')
            self.assertEqual(context.resolve(moved, str(old / 'model.py')), moved / 'model.py')
            self.assertEqual(context.resolve(moved, 'model.py'), moved / 'model.py')
            for bad in ('../model.py', str(old) + '-other/model.py', str(old / 'absent.py')):
                with self.assertRaises(ValueError):
                    context.resolve(moved, bad)

    def test_changed_binary_force_or_expired_record_reprobes_but_status_is_read_only(self):
        with mock.patch.object(context, 'probe', return_value='unknown') as probe, mock.patch.object(context, '_fingerprint', return_value='one'):
            context.refresh(self.root, ['codex'])
            context.report(self.root)
            context.refresh(self.root, ['codex'])
            self.assertEqual(probe.call_count, 1)
            context.refresh(self.root, ['codex'], force=True)
            with mock.patch.object(context, '_fingerprint', return_value='two'):
                context.refresh(self.root, ['codex'])
            self.assertEqual(probe.call_count, 3)

    def test_probe_uses_native_sandbox_even_without_path_bwrap_and_never_relaxes_it(self):
        with mock.patch.object(context.platform, 'system', return_value='Linux'), mock.patch.object(context, '_run') as run:
            run.side_effect = [(0, 'Usage: codex sandbox linux [COMMAND]...'), (0, '')]
            self.assertEqual(context.probe(['codex'], self.root), 'available')
            argv = run.call_args.args[0]
            self.assertEqual(argv[:4], ['codex', 'sandbox', 'linux', '--'])
            self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', argv)
            run.side_effect = [(0, 'COMMAND'), (1, 'bwrap: Creating new namespace failed')]
            self.assertEqual(context.probe(['codex'], self.root), 'unavailable')
            run.side_effect = [(1, 'Unsupported subcommand')]
            self.assertEqual(context.probe(['codex'], self.root), 'unknown')

    def test_unowned_context_is_not_replaced(self):
        path = self.root / context.PATH
        path.parent.mkdir()
        path.write_text('{"user":"content"}')
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            context.refresh(self.root, ['codex'])
        self.assertEqual(path.read_bytes(), before)

    def test_context_preview_does_not_create_receipts(self):
        args = main.build_parser(REPO).parse_args(['context', '--project', str(self.root), '--json'])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            context.run(args, REPO)
        self.assertEqual(json.loads(output.getvalue())['sandbox'], 'not-tested')
        self.assertFalse((self.root / '.harness').exists())

    def test_legacy_prefix_registration_and_owned_context_removal(self):
        from harness_cli import lifecycle
        from test_harness_tools import harness_apply, minimal_plan
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))
        args = main.build_parser(REPO).parse_args(['context', '--project', str(self.root), '--remember-root',
                                                  '/old/server/project', '--resolve', '/old/server/project/model.py', '--json'])
        with mock.patch.object(project, '_codex_command', return_value=['codex']), mock.patch.object(context, 'probe', return_value='unknown'), contextlib.redirect_stdout(io.StringIO()) as output:
            context.run(args, REPO)
        self.assertEqual(json.loads(output.getvalue())['resolvedPath'], str(self.root / 'model.py'))
        self.assertTrue(context.owned(self.root))
        lifecycle.remove_project(self.root, source_root=REPO, dry_run=False)
        self.assertFalse((self.root / context.PATH).exists())
        self.assertTrue((self.root / 'model.py').is_file())

    def test_diagnostic_timeout_terminates_its_process_group(self):
        process = mock.MagicMock(pid=1234)
        process.wait.side_effect = [context.subprocess.TimeoutExpired('sandbox', 5), -9]
        with mock.patch.object(context.subprocess, 'Popen') as start, mock.patch.object(context.os, 'killpg', create=True) as kill, mock.patch.object(context.signal, 'SIGKILL', 9, create=True):
            start.return_value.__enter__.return_value = process
            self.assertEqual(context._run(['codex', 'sandbox', 'linux'], self.root), (None, ''))
        kill.assert_called_once_with(1234, 9)

    def test_generated_guidance_is_idempotent_and_agent_context_is_concise(self):
        from test_harness_tools import harness_plan_builder
        import harness_portability
        content = harness_portability.append_guidance('Existing instructions', agent=True)
        self.assertEqual(harness_portability.append_guidance(content, agent=True), content)
        self.assertLess(len(harness_portability.AGENT_GUIDANCE), len(harness_portability.GUIDANCE) // 2)


class MissingProjectTests(unittest.TestCase):
    setUp = fixtures.ProjectCliTests.setUp
    run_cli = fixtures.ProjectCliTests.run_cli

    def test_init_creates_nested_root_but_dry_run_and_invalid_input_never_do(self):
        self.root = self.base / 'missing' / 'nested'
        code, out, err = self.run_cli('init', '--dry-run', tty=False)
        self.assertEqual(code, 0, err)
        self.assertIn('would-create', out)
        self.assertFalse(self.root.parent.exists())
        self.assertEqual(self.run_cli('init', '--timeout', '0', tty=False)[0], 1)
        self.assertFalse(self.root.parent.exists())
        code, _, err = self.run_cli('init', '--install-only', tty=False)
        self.assertEqual(code, 0, err)
        self.assertTrue((self.root / '.agents/skills/harness/SKILL.md').is_file())

    def test_non_init_commands_do_not_create_and_init_rejects_files_or_git_metadata(self):
        self.root = self.base / 'missing'
        for command in ('configure', 'status', 'doctor'):
            self.assertEqual(self.run_cli(command, tty=False)[0], 1)
            self.assertFalse(self.root.exists())
        self.root.write_text('preserve')
        self.assertEqual(self.run_cli('init', '--install-only', tty=False)[0], 1)
        self.assertEqual(self.root.read_text(), 'preserve')
        self.root = self.base / '.git' / 'bad'
        self.assertEqual(self.run_cli('init', '--install-only', tty=False)[0], 1)
        self.assertFalse(self.root.parent.exists())
