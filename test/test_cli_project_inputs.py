"""Project briefs, existing-installation notices, and lifecycle CLI preflight."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

import test_cli_project as fixtures
from harness_cli import main, project


class ProjectInputTests(unittest.TestCase):
    setUp = fixtures.ProjectCliTests.setUp
    run_cli = fixtures.ProjectCliTests.run_cli
    generate = fixtures.ProjectCliTests.generate

    def test_markdown_brief_is_read_as_literal_reference_with_bom_and_unicode(self):
        brief = self.base / "project brief.md"
        text = "# 연구 프로젝트\n\n- 목표: 세포 모델 검증\n- 인용: `$HOME` & $(literal)\n"
        brief.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
        before = (brief.read_bytes(), brief.stat().st_mtime_ns)
        os.environ["FAKE_CODEX_MODE"] = "generate"
        code, out, err = self.run_cli("init", "--goal-file", str(brief))
        self.assertEqual(code, 0, err)
        invocation = json.loads(self.log.read_text(encoding="utf-8"))["argv"]
        self.assertEqual(len(invocation), 3)
        self.assertIn(json.dumps(str(brief), ensure_ascii=False), invocation[-1])
        self.assertNotIn(text, invocation[-1])
        self.assertIn("reference material", invocation[-1])
        self.assertIn("do not independently authorize Git operations", invocation[-1])
        self.assertEqual((brief.read_bytes(), brief.stat().st_mtime_ns), before)

    def test_relative_goal_file_uses_invocation_directory(self):
        brief = self.base / "brief.markdown"
        brief.write_text("# Explicit project description\n", encoding="utf-8")
        before = Path.cwd()
        try:
            os.chdir(self.base)
            code, out, err = self.run_cli("init", "--goal-file", brief.name, "--dry-run", tty=False)
        finally:
            os.chdir(before)
        self.assertEqual(code, 0, err)
        self.assertEqual(list(self.root.iterdir()), [])
        self.codex.assert_not_called()

    def test_large_brief_stays_out_of_argv_and_checks_encoding_after_first_chunk(self):
        brief = self.base / 'large.md'
        content = ('# 연구\n' + '유전자 순서와 데이터 분할을 확인할 것.\n' * 20000).encode('utf-8')
        brief.write_bytes(content)
        os.environ['FAKE_CODEX_MODE'] = 'generate'
        code, _, err = self.run_cli('init', '--goal-file', str(brief))
        self.assertEqual(code, 0, err)
        argv = json.loads(self.log.read_text())['argv']
        self.assertLess(len(argv[-1].encode('utf-8')), 4096)
        self.assertEqual(brief.read_bytes(), content)
        from harness_cli.project_brief import reference
        for suffix in (b'\xff', b'\x00', b'\xf0\x9f'):
            brief.write_bytes(content + suffix)
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                reference(brief)

    def test_invalid_briefs_fail_before_generator_writes_or_codex(self):
        examples = [("empty.md", b" \n"), ("binary.md", b"# A\0B"), ("encoded.md", b"\xff\xfe\x00\x00"),
                    ("wrong.txt", b"# Goal")]
        for name, data in examples:
            brief = self.base / name
            brief.write_bytes(data)
            with self.subTest(name=name):
                code, out, err = self.run_cli("init", "--goal-file", str(brief))
                self.assertEqual(code, 1)
                self.assertEqual(list(self.root.iterdir()), [])
                self.assertFalse(self.log.exists())
        for brief in (self.base / "missing.md", self.base):
            self.assertEqual(self.run_cli("init", "--goal-file", str(brief))[0], 1)
        self.codex.assert_not_called()

    def test_goal_text_and_file_are_mutually_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            self.parser.parse_args(["init", "--goal", "x", "--goal-file", "brief.md"])
        self.assertEqual(caught.exception.code, 2)

    def test_goal_file_symlink_is_refused(self):
        target = self.base / "target.md"
        target.write_text("Project brief", encoding="utf-8")
        link = self.base / "linked.md"
        try:
            link.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"Symlinks unavailable: {exc}")
        code, out, err = self.run_cli("init", "--goal-file", str(link), "--install-only")
        self.assertEqual(code, 1)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_goal_precedes_automatic_tool_update(self):
        with mock.patch.object(main, "_environment"), mock.patch.object(main, "_automatic_update") as update:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main.main(["init", "--project", str(self.root), "--goal-file", str(self.base / "missing.md")],
                                 source_root=fixtures.REPO_ROOT)
        self.assertEqual(code, 1)
        update.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_init_reports_and_exits_without_codex_or_writes(self):
        self.generate()
        before = fixtures.snapshot(self.root)
        code, out, err = self.run_cli("init", tty=False)
        self.assertEqual(code, 0, err)
        self.assertIn("already exists", out)
        self.assertIn("The generated harness was retained", out)
        self.assertEqual(fixtures.snapshot(self.root), before)
        self.codex.assert_not_called()

    def test_explicit_goal_revisits_existing_harness(self):
        self.generate()
        code, out, err = self.run_cli("init", "--goal", "Review the existing project")
        self.assertEqual(code, 0, err)
        self.assertIn("already exists", out)
        self.assertTrue(self.log.exists())

    def test_status_distinguishes_absent_generator_configured_stale_and_invalid(self):
        code, out, err = self.run_cli("status", tty=False)
        self.assertEqual((code, json.loads(out)["state"]), (0, "absent"))
        self.assertEqual(self.run_cli("init", "--install-only", tty=False)[0], 0)
        self.assertEqual(json.loads(self.run_cli("status", tty=False)[1])["state"], "generator-only")
        self.generate()
        self.assertEqual(json.loads(self.run_cli("status", tty=False)[1])["state"], "configured")
        (self.root / "pyproject.toml").write_text("# Changed source\n", encoding="utf-8")
        self.assertEqual(json.loads(self.run_cli("status", tty=False)[1])["state"], "stale-evidence")
        (self.root / ".agents/skills/project-harness/SKILL.md").write_text("modified", encoding="utf-8")
        code, out, err = self.run_cli("status", tty=False)
        self.assertEqual((code, json.loads(out)["state"]), (1, "invalid"))
        self.assertFalse(self.log.exists())

    def test_pending_removal_blocks_init_even_when_manifest_is_absent(self):
        folder = self.root / ".harness"
        folder.mkdir()
        (folder / "transaction.json").write_text('{"operation":"remove","removalSchemaVersion":1}', encoding="utf-8")
        before = fixtures.snapshot(self.root)
        for command in ("init", "configure", "reset"):
            with self.subTest(command=command):
                code, out, err = self.run_cli(command, tty=False)
                self.assertEqual(code, 1)
                self.assertIn("--recover", err)
                self.assertEqual(fixtures.snapshot(self.root), before)
        code, out, err = self.run_cli("status", tty=False)
        self.assertEqual(json.loads(out)["state"], "removal-pending")
        self.codex.assert_not_called()

    def test_transport_limit_is_checked_before_installation(self):
        with mock.patch.object(project, "_validate_prompt_transport", side_effect=project.ProjectError("transport limit")):
            code, out, err = self.run_cli("init", "--goal", "Brief")
        self.assertEqual(code, 1)
        self.assertIn("transport limit", err)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_orphaned_recovery_data_blocks_configuration_without_a_manifest(self):
        for name, expected in (("removals", "orphaned-removal-workspace"),
                               ("transactions", "orphaned-transaction-workspace")):
            with self.subTest(name=name):
                backup = self.root / ".harness" / name
                backup.mkdir(parents=True)
                (backup / "original.txt").write_bytes(b"original recovery bytes")
                before = fixtures.snapshot(self.root)
                for command in ("init", "configure", "reset"):
                    code, out, err = self.run_cli(command, tty=False)
                    self.assertEqual(code, 1)
                    self.assertIn("without its journal", err)
                    self.assertEqual(fixtures.snapshot(self.root), before)
                code, out, err = self.run_cli("status", tty=False)
                self.assertEqual((code, json.loads(out)["state"]), (1, expected))
                self.assertIsNone(json.loads(out)["nextCommand"])
                (backup / "original.txt").unlink()
                backup.rmdir()
        self.codex.assert_not_called()

    def test_remove_preview_then_apply_and_reinstall_preserve_user_and_git_files(self):
        self.assertEqual(self.run_cli("init", "--install-only", tty=False)[0], 0)
        self.generate()
        (self.root / "user.txt").write_bytes(b"user bytes\r\n")
        git = self.root / ".git"
        git.mkdir()
        (git / "config").write_bytes(b"Git sentinel\n")
        protected = {name: value for name, value in fixtures.snapshot(self.root).items()
                     if name in {"user.txt", ".git/config", "pyproject.toml"}}
        before = fixtures.snapshot(self.root)
        for flags in ((), ("--yes", "--dry-run")):
            code, out, err = self.run_cli("remove", *flags, tty=False)
            self.assertEqual(code, 0, err)
            self.assertIn("Preview only", out)
            self.assertEqual(fixtures.snapshot(self.root), before)
        code, out, err = self.run_cli("remove", "--yes", tty=False)
        self.assertEqual(code, 0, err)
        self.assertFalse((self.root / ".harness/manifest.json").exists())
        self.assertEqual(json.loads(self.run_cli("status", tty=False)[1])["state"], "generator-only")
        self.assertEqual(self.run_cli("remove", "--include-generator", "--yes", tty=False)[0], 0)
        self.assertEqual(json.loads(self.run_cli("status", tty=False)[1])["state"], "absent")
        self.assertEqual(self.run_cli("init", "--install-only", tty=False)[0], 0)
        for name, value in protected.items():
            self.assertEqual(fixtures.snapshot(self.root)[name], value)
        self.codex.assert_not_called()

    def test_reset_previews_without_terminal_and_validates_before_removal(self):
        self.generate()
        before = fixtures.snapshot(self.root)
        code, out, err = self.run_cli("reset", tty=False)
        self.assertEqual(code, 0, err)
        self.assertIn("Preview only", out)
        self.assertEqual(fixtures.snapshot(self.root), before)
        self.codex.assert_not_called()
        code, out, err = self.run_cli("reset", "--yes", "--goal-file", str(self.base / "missing.md"))
        self.assertEqual(code, 1)
        self.codex.side_effect = project.ProjectError("Codex CLI was not found")
        code, out, err = self.run_cli("reset", "--yes", "--goal", "New project description")
        self.assertEqual(code, 1)
        self.assertIn("not found", err)
        self.assertEqual(fixtures.snapshot(self.root), before)

    def test_reset_reads_brief_and_independently_validates_fresh_configuration(self):
        self.generate()
        brief = self.base / "reset.md"
        brief.write_text("# Revised responsibilities\n", encoding="utf-8")
        os.environ["FAKE_CODEX_MODE"] = "generate"
        code, out, err = self.run_cli("reset", "--yes", "--goal-file", str(brief))
        self.assertEqual(code, 0, err)
        self.assertIn("Project harness files validate", out)
        self.assertIn(json.dumps(str(brief)), json.loads(self.log.read_text())["argv"][-1])
        self.assertFalse((self.root / ".harness/transaction.json").exists())
        self.assertEqual(json.loads(self.run_cli("status", tty=False)[1])["state"], "configured")

    def test_cancelled_reset_keeps_generator_and_reports_incomplete_configuration(self):
        self.generate()
        os.environ["FAKE_CODEX_EXIT"] = "7"
        code, out, err = self.run_cli("reset", "--yes")
        self.assertEqual(code, 7)
        self.assertIn("config to continue", out)
        self.assertIn("not been confirmed", err)
        self.assertFalse((self.root / ".harness/manifest.json").exists())
        self.assertEqual(json.loads(self.run_cli("status", tty=False)[1])["state"], "generator-only")

    def test_reset_stops_before_codex_when_removal_cleanup_requires_recovery(self):
        from harness_cli import lifecycle
        self.generate()
        real_remove = lifecycle.remove_project

        def interrupted_cleanup(*args, **kwargs):
            if kwargs.get("dry_run", True):
                return real_remove(*args, **kwargs)
            with mock.patch.object(lifecycle, "_cleanup", side_effect=OSError("cleanup unavailable")):
                return real_remove(*args, **kwargs)

        with mock.patch.object(lifecycle, "remove_project", side_effect=interrupted_cleanup):
            code, out, err = self.run_cli("reset", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("cleanup remains pending", err)
        self.assertFalse(self.log.exists())
        self.assertTrue((self.root / ".harness/transaction.json").exists())
        before = fixtures.snapshot(self.root)
        code, out, err = self.run_cli("remove", "--recover", tty=False)
        self.assertEqual(code, 0, err)
        self.assertEqual(fixtures.snapshot(self.root), before)
        self.assertEqual(self.run_cli("remove", "--recover", "--yes", tty=False)[0], 0)
        self.assertFalse((self.root / ".harness/transaction.json").exists())

    def test_status_distinguishes_empty_router_directory_from_unowned_content(self):
        router = self.root / ".agents/skills/project-harness"
        (router / "references/empty").mkdir(parents=True)
        self.assertEqual(json.loads(self.run_cli("status", tty=False)[1])["state"], "absent")
        (router / "user.md").write_text("User content", encoding="utf-8")
        code, out, err = self.run_cli("status", tty=False)
        self.assertEqual((code, json.loads(out)["state"]), (1, "unowned-artifacts"))


if __name__ == "__main__":
    unittest.main()
