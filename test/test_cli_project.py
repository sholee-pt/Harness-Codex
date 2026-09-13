"""Exercise real installer/validator calls and a local fake Codex subprocess."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from harness_cli import project
from test_harness_tools import harness_apply, minimal_plan


FAKE_CODEX = '''import json, os, pathlib, sys
root = pathlib.Path(sys.argv[sys.argv.index("--cd") + 1])
pathlib.Path(os.environ["FAKE_CODEX_LOG"]).write_text(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}), encoding="utf-8")
mode = os.environ.get("FAKE_CODEX_MODE", "noop")
if mode in {"generate", "corrupt"}:
    sys.path.insert(0, str(pathlib.Path(os.environ["FAKE_HARNESS_SOURCE"]) / "test"))
    from test_harness_tools import minimal_plan, harness_apply
    harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))
    if mode == "corrupt":
        (root / ".agents/skills/project-harness/SKILL.md").write_text("damaged", encoding="utf-8")
raise SystemExit(int(os.environ.get("FAKE_CODEX_EXIT", "0")))
'''


class TerminalBuffer(io.StringIO):
    def isatty(self):
        return True


def snapshot(root: Path) -> dict:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*") if path.is_file()
    }


class ProjectCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "project with spaces"
        self.root.mkdir()
        self.fake = self.base / "fake codex.py"
        self.fake.write_text(FAKE_CODEX, encoding="utf-8")
        self.log = self.base / "codex-log.json"
        self.parser = argparse.ArgumentParser()
        project.register_project_commands(self.parser.add_subparsers(dest="command", required=True))
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, {
            "FAKE_CODEX_LOG": str(self.log), "FAKE_HARNESS_SOURCE": str(REPO_ROOT),
            "FAKE_CODEX_MODE": "noop", "FAKE_CODEX_EXIT": "0",
        }).start()
        self.codex = mock.patch.object(project, "_codex_command", return_value=[sys.executable, "-B", str(self.fake)]).start()

    def run_cli(self, command, *extra, tty=True):
        output = TerminalBuffer() if tty else io.StringIO()
        error = io.StringIO()
        options = ["--interactive", "--settings", "native", "--no-codex-integration"] if command in {"init", "configure", "config", "reset"} else (
            ['--settings', 'native'] if command in {'new', 'start', 'resume'} else [])
        args = self.parser.parse_args([command, "--json", "--project", str(self.root), *options, *extra])
        with mock.patch.object(sys, "stdin", TerminalBuffer() if tty else io.StringIO()), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = project.run_project_command(args, source_root=REPO_ROOT)
        return status, output.getvalue(), error.getvalue()

    def generate(self):
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))
        project._sync_guide(REPO_ROOT, self.root)

    def test_dry_run_does_not_need_codex_or_terminal_and_does_not_write(self):
        (self.root / "user.txt").write_text("keep", encoding="utf-8")
        before = snapshot(self.root)
        code, out, err = self.run_cli("init", "--dry-run", tty=False)
        self.assertEqual(code, 0, err)
        self.assertIn('"dryRun": true', out)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / ".agents").exists())
        self.codex.assert_not_called()
        self.assertFalse(self.log.exists())

    def test_install_only_preserves_git_and_user_instructions_without_codex(self):
        (self.root / "AGENTS.md").write_bytes(b"user instructions\r\n")
        for name in (".git", "nested/.git"):
            directory = self.root / name
            directory.mkdir(parents=True)
            (directory / "config").write_text("sentinel", encoding="utf-8")
        before = snapshot(self.root)
        code, out, err = self.run_cli("init", "--install-only", tty=False)
        self.assertEqual(code, 0, err)
        self.assertTrue((self.root / ".agents/skills/harness/SKILL.md").is_file())
        self.assertFalse((self.root / ".harness/manifest.json").exists())
        self.assertIn("did not configure", out)
        for name, value in before.items():
            self.assertEqual(snapshot(self.root)[name], value)
        self.codex.assert_not_called()
        self.assertFalse(self.log.exists())

    def test_init_missing_codex_precedes_install_writes(self):
        self.codex.side_effect = project.ProjectError("Codex CLI was not found")
        code, out, err = self.run_cli("init")
        self.assertEqual(code, 1)
        self.assertIn("not found", err)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_noninteractive_init_is_actionable_and_does_not_install(self):
        code, out, err = self.run_cli("init", tty=False)
        self.assertEqual(code, 1)
        self.assertIn("--install-only", err)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertFalse(self.log.exists())

    def test_init_child_generation_is_independently_validated(self):
        os.environ["FAKE_CODEX_MODE"] = "generate"
        goal = "작업 목표: spaces & $(literal) `text`\nsecond line"
        code, out, err = self.run_cli("init", "--goal", goal)
        self.assertEqual(code, 0, err)
        self.assertIn("Project harness files validate", out)
        self.assertIn('"runtimeLoading": "not-tested"', out)
        self.assertIn('"taskQuality": "not-measured"', out)
        record = json.loads(self.log.read_text(encoding="utf-8"))
        self.assertEqual(record["argv"][:2], ["--cd", str(self.root)])
        self.assertEqual(len(record["argv"]), 3)
        self.assertTrue(record["argv"][2].startswith("$harness "))
        self.assertTrue(record["argv"][2].endswith(goal))
        self.assertEqual(Path(record["cwd"]), self.root)
        self.assertEqual(project._report(REPO_ROOT, self.root)[0], 0)

    def test_zero_exit_without_generated_manifest_is_not_success(self):
        code, out, err = self.run_cli("init")
        self.assertEqual(code, 1)
        self.assertIn("complete project harness was not created", err)
        self.assertNotIn("Project harness files validate", out)
        self.assertTrue((self.root / ".agents/skills/harness/SKILL.md").exists())

    def test_child_failure_is_propagated_with_generator_retained(self):
        os.environ["FAKE_CODEX_EXIT"] = "7"
        code, out, err = self.run_cli("init")
        self.assertEqual(code, 7)
        self.assertIn("not been confirmed", err)
        self.assertNotIn("Project harness files validate", out)
        self.assertTrue((self.root / ".agents/skills/harness/SKILL.md").exists())

    def test_corrupt_generated_files_fail_postvalidation(self):
        os.environ["FAKE_CODEX_MODE"] = "corrupt"
        code, out, err = self.run_cli("init")
        self.assertEqual(code, 1)
        self.assertIn("not confirmed", err)
        self.assertNotIn("Project harness files validate", out)

    def test_init_rejects_corrupt_existing_manifest_before_writes(self):
        self.generate()
        (self.root / ".harness/manifest.json").write_text("{}", encoding="utf-8")
        before = snapshot(self.root)
        code, out, err = self.run_cli("init")
        self.assertEqual(code, 1)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / ".agents/skills/harness").exists())
        self.assertFalse(self.log.exists())

    def test_configure_requires_generator_installation(self):
        code, out, err = self.run_cli("configure")
        self.assertEqual(code, 1)
        self.assertIn("harness-codex init", err)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertFalse(self.log.exists())

    def test_configure_preserves_user_agents_and_uses_explicit_skill(self):
        original = b'user-owned instructions\r\n'
        (self.root / 'AGENTS.md').write_bytes(original)
        self.assertEqual(self.run_cli('init', '--install-only')[0], 0)
        os.environ['FAKE_CODEX_MODE'] = 'generate'
        code, out, err = self.run_cli('configure', '--goal', 'A focused project')
        self.assertEqual(code, 0, err)
        content = (self.root / 'AGENTS.md').read_bytes()
        block = harness_apply.harness_state.extract_managed_block(content.decode()).encode()
        self.assertEqual(content.replace(block, b''), original)
        status, report = project._report(REPO_ROOT, self.root)
        self.assertEqual(status, 0)
        self.assertEqual(report['activation']['mode'], 'managed-pointer')

    def test_configure_refuses_modified_managed_generator(self):
        self.assertEqual(self.run_cli("init", "--install-only")[0], 0)
        (self.root / ".agents/skills/harness/SKILL.md").write_text("user changed this", encoding="utf-8")
        before = snapshot(self.root)
        code, out, err = self.run_cli("configure")
        self.assertEqual(code, 1)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.log.exists())

    def test_start_passes_literal_task_without_model_or_approval_overrides(self):
        self.generate()
        before = snapshot(self.root)
        task = 'literal $HOME; "task" & `command`'
        code, out, err = self.run_cli('start', task)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(self.log.read_text())['argv'], ['--cd', str(self.root), '--', task])
        self.assertEqual(snapshot(self.root), before)

    def test_start_without_task_waits_for_next_task(self):
        self.generate()
        code, out, err = self.run_cli('start')
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(self.log.read_text())['argv'], ['--cd', str(self.root)])
        self.assertIn('deprecated', err)

    def test_start_refuses_missing_or_corrupt_manifest(self):
        self.assertEqual(self.run_cli('doctor')[0], 1)
        self.assertFalse(self.log.exists())
        self.generate()
        (self.root / '.agents/skills/project-harness/SKILL.md').write_text('edited', encoding='utf-8')
        before = snapshot(self.root)
        self.assertEqual(self.run_cli('doctor')[0], 1)
        self.assertEqual(self.run_cli('start', 'Do something')[0], 0)
        self.assertEqual(snapshot(self.root), before)

    def test_start_propagates_nonzero_child_exit(self):
        self.generate()
        os.environ["FAKE_CODEX_EXIT"] = "23"
        self.assertEqual(self.run_cli("start")[0], 23)

    def test_normal_source_edit_allows_start_with_fresh_evidence_instructions(self):
        self.generate()
        (self.root / 'pyproject.toml').write_text("[project]\nname = 'changed-project'\n", encoding='utf-8')
        before = snapshot(self.root)
        code, out, err = self.run_cli('start', 'Continue the project work')
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(self.log.read_text())['argv'][2:], ['--', 'Continue the project work'])
        self.assertEqual(snapshot(self.root), before)
        status, report = project._report(REPO_ROOT, self.root)
        self.assertEqual(status, 1)
        self.assertTrue(project._only_stale_evidence(report, root=self.root, source_root=REPO_ROOT))
        pointer = (self.root / 'AGENTS.md').read_text()
        self.assertIn('source evidence requires reading current source', pointer)

    def test_readme_evidence_edit_allows_reviewed_configure_refresh(self):
        self.assertEqual(self.run_cli("init", "--install-only")[0], 0)
        plan = minimal_plan(self.root)
        (self.root / "pyproject.toml").rename(self.root / "README.md")
        # minimal_plan shares this evidence object across its project/topology.
        plan["project"]["evidence"][0]["path"] = "README.md"
        harness_apply.apply_application(harness_apply.build_application(self.root, plan))
        (self.root / "README.md").write_text("A new project description.\nEvidence changed.\n", encoding="utf-8")
        os.environ["FAKE_CODEX_MODE"] = "generate"
        code, out, err = self.run_cli("configure", "--goal", "Review the changed project")
        self.assertEqual(code, 0, err)
        self.assertIn("evidence is stale", err)
        self.assertIn("Project harness files validate", out)
        self.assertEqual(project._report(REPO_ROOT, self.root)[0], 0)
        self.assertEqual((self.root / "README.md").read_text(encoding="utf-8"),
                         "A new project description.\nEvidence changed.\n")

    def test_init_install_only_can_proceed_with_stale_source_evidence(self):
        self.generate()
        (self.root / "pyproject.toml").write_text("[project]\nname = 'edited'\n", encoding="utf-8")
        manifest = (self.root / ".harness/manifest.json").read_bytes()
        code, out, err = self.run_cli("init", "--install-only")
        self.assertEqual(code, 0, err)
        self.assertIn("evidence is stale", err)
        self.assertEqual((self.root / ".harness/manifest.json").read_bytes(), manifest)
        self.assertTrue((self.root / ".agents/skills/harness/SKILL.md").exists())

    def test_shortened_valid_source_evidence_range_is_stale_not_corrupt(self):
        self.generate()
        (self.root / 'pyproject.toml').write_text('# shortened to one line\n', encoding='utf-8')
        self.assertEqual(self.run_cli('start')[0], 0)
        status, report = project._report(REPO_ROOT, self.root)
        self.assertEqual(status, 1)
        self.assertTrue(any('.lines exceeds ' in finding for finding in report['errors']))
        self.assertTrue(project._only_stale_evidence(report, root=self.root, source_root=REPO_ROOT))

    def test_stale_evidence_plus_managed_tampering_still_blocks_all_entrypoints(self):
        self.generate()
        (self.root / "pyproject.toml").write_text("[project]\nname = 'edited'\n", encoding="utf-8")
        (self.root / ".agents/skills/project-harness/SKILL.md").write_text("tampered", encoding="utf-8")
        before = snapshot(self.root)
        for command in ("init", "configure", "doctor"):
            with self.subTest(command=command):
                code, out, err = self.run_cli(command)
                self.assertEqual(code, 1)
                self.assertNotIn("evidence is stale", err)
                self.assertFalse(self.log.exists())
                self.assertEqual(snapshot(self.root), before)

    def test_missing_evidence_allows_start_without_refreshing_the_manifest(self):
        self.generate()
        (self.root / 'pyproject.toml').unlink()
        before = snapshot(self.root)
        self.assertEqual(self.run_cli('start')[0], 0)
        self.assertEqual(snapshot(self.root), before)
        report = json.loads(self.run_cli('status')[1])
        self.assertEqual(report['state'], 'stale-evidence')
        self.assertEqual(report['nextCommand'], 'codex')

    def test_configure_repairs_deleted_evidence_through_reviewed_generation(self):
        self.assertEqual(self.run_cli("init", "--install-only")[0], 0)
        self.generate()
        (self.root / "pyproject.toml").unlink()
        self.assertEqual(self.run_cli("start")[0], 0)
        os.environ["FAKE_CODEX_MODE"] = "generate"
        code, out, err = self.run_cli("configure", "--goal", "Review the current files and refresh evidence")
        self.assertEqual(code, 0, err)
        self.assertIn("evidence is stale", err)
        self.assertIn("Project harness files validate", out)
        self.assertEqual(project._report(REPO_ROOT, self.root)[0], 0)

    def test_init_repairs_renamed_evidence_and_preserves_renamed_file(self):
        self.generate()
        (self.root / "pyproject.toml").rename(self.root / "renamed-project.toml")
        preserved = (self.root / "renamed-project.toml").read_bytes()
        os.environ["FAKE_CODEX_MODE"] = "generate"
        code, out, err = self.run_cli("init", "--goal", "Re-analyze the renamed project")
        self.assertEqual(code, 0, err)
        self.assertIn("evidence is stale", err)
        self.assertIn("Project harness files validate", out)
        self.assertEqual((self.root / "renamed-project.toml").read_bytes(), preserved)
        self.assertEqual(project._report(REPO_ROOT, self.root)[0], 0)

    def test_install_only_with_missing_evidence_does_not_rewrite_manifest(self):
        self.generate()
        (self.root / "pyproject.toml").unlink()
        original = (self.root / ".harness/manifest.json").read_bytes()
        code, out, err = self.run_cli("init", "--install-only")
        self.assertEqual(code, 0, err)
        self.assertEqual((self.root / ".harness/manifest.json").read_bytes(), original)
        self.assertEqual(project._report(REPO_ROOT, self.root)[0], 1)
        self.assertFalse(self.log.exists())

    def test_missing_reference_cannot_hide_bad_hash_claim_or_line_metadata(self):
        self.generate()
        (self.root / "pyproject.toml").unlink()
        manifest_path = self.root / ".harness/manifest.json"
        original = manifest_path.read_text(encoding="utf-8")
        for field, bad_value in (("sha256", "bad"), ("claim", ""), ("lines", {"start": 0, "end": 2})):
            manifest = json.loads(original)
            manifest["project"]["evidence"][0][field] = bad_value
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            before = snapshot(self.root)
            for command in ("init", "configure"):
                with self.subTest(command=command, field=field):
                    code, out, err = self.run_cli(command)
                    self.assertEqual(code, 1)
                    self.assertNotIn("evidence is stale", err)
                    self.assertFalse(self.log.exists())
                    self.assertEqual(snapshot(self.root), before)

    def test_missing_evidence_and_managed_tampering_do_not_enable_repair(self):
        self.generate()
        (self.root / "pyproject.toml").unlink()
        (self.root / ".agents/skills/project-harness/SKILL.md").write_text("tampered", encoding="utf-8")
        before = snapshot(self.root)
        for command in ("init", "configure"):
            with self.subTest(command=command):
                code, out, err = self.run_cli(command)
                self.assertEqual(code, 1)
                self.assertNotIn("evidence is stale", err)
                self.assertFalse(self.log.exists())
                self.assertEqual(snapshot(self.root), before)

    def test_nonregular_evidence_is_not_a_missing_source_repair(self):
        self.generate()
        (self.root / "pyproject.toml").unlink()
        (self.root / "pyproject.toml").mkdir()
        for command in ("init", "configure"):
            with self.subTest(command=command):
                code, out, err = self.run_cli(command)
                self.assertEqual(code, 1)
                self.assertNotIn("evidence is stale", err)
                self.assertFalse(self.log.exists())

    def test_reserved_or_malformed_missing_evidence_paths_stay_blocked(self):
        self.generate()
        manifest_path = self.root / ".harness/manifest.json"
        original = manifest_path.read_text(encoding="utf-8")
        for path in ("../missing-file", ".git/missing-file", "bad\\missing-file"):
            manifest = json.loads(original)
            manifest["project"]["evidence"][0]["path"] = path
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            for command in ("init", "configure"):
                with self.subTest(command=command, path=path):
                    code, out, err = self.run_cli(command)
                    self.assertEqual(code, 1)
                    self.assertNotIn("evidence is stale", err)
                    self.assertFalse(self.log.exists())

    def test_dangling_evidence_symlink_is_not_a_missing_source_repair(self):
        self.generate()
        (self.root / "pyproject.toml").unlink()
        try:
            (self.root / "pyproject.toml").symlink_to(self.base / "missing-external")
        except OSError as exc:
            self.skipTest(f"Symlink creation unavailable: {exc}")
        for command in ("init", "configure"):
            with self.subTest(command=command):
                code, out, err = self.run_cli(command)
                self.assertEqual(code, 1)
                self.assertNotIn("evidence is stale", err)
                self.assertFalse(self.log.exists())

    def test_range_only_manifest_defect_is_not_classified_as_content_drift(self):
        self.generate()
        manifest_path = self.root / ".harness/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["project"]["evidence"][0]["lines"]["end"] = 10000
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        code, out, err = self.run_cli("doctor")
        self.assertEqual(code, 1)
        self.assertNotIn("evidence is stale", err)
        self.assertFalse(self.log.exists())

    def test_stale_evidence_and_invalid_line_shape_are_not_relaxed(self):
        self.generate()
        (self.root / "pyproject.toml").write_text("# short content\n", encoding="utf-8")
        manifest_path = self.root / ".harness/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["project"]["evidence"][0]["lines"]["start"] = 0
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        code, out, err = self.run_cli("doctor")
        self.assertEqual(code, 1)
        self.assertNotIn("evidence is stale", err)
        self.assertFalse(self.log.exists())

    def test_doctor_checks_files_without_terminal_or_codex(self):
        self.generate()
        before = snapshot(self.root)
        code, out, err = self.run_cli("doctor", tty=False)
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertTrue(report["valid"])
        self.assertEqual(report["activation"]["runtimeLoaded"], "not-tested")
        self.assertFalse(report["workspaceWrites"])
        self.assertFalse(report["codexInvoked"])
        self.assertEqual(report["summary"]["managedArtifacts"], "passed")
        self.assertEqual(report["summary"]["sourceEvidence"], "passed")
        self.assertEqual(report["summary"]["runtimeLoading"], "not-tested")
        self.assertEqual(report["summary"]["taskQuality"], "not-measured")
        self.assertEqual(snapshot(self.root), before)
        self.codex.assert_not_called()

    def test_status_changed_source_recommends_start_without_refreshing_manifest(self):
        self.generate()
        (self.root / "pyproject.toml").write_text("[project]\nname = 'edited'\n", encoding="utf-8")
        before = snapshot(self.root)
        code, out, err = self.run_cli("status", tty=False)
        report = json.loads(out)
        self.assertEqual(report["state"], "stale-evidence", err)
        self.assertEqual(report["nextCommand"], "codex")
        self.assertEqual(report["summary"]["managedArtifacts"], "passed")
        self.assertEqual(report["summary"]["sourceEvidence"], "failed")
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.log.exists())

    def test_status_missing_source_permits_work_with_review_notice(self):
        self.generate()
        (self.root / "pyproject.toml").unlink()
        before = snapshot(self.root)
        code, out, err = self.run_cli("status", tty=False)
        report = json.loads(out)
        self.assertEqual(report["state"], "stale-evidence", err)
        self.assertEqual(report["nextCommand"], "codex")
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.log.exists())

    def test_status_and_doctor_keep_source_drift_separate_from_managed_conflict(self):
        self.generate()
        (self.root / "pyproject.toml").write_text("changed", encoding="utf-8")
        (self.root / ".agents/skills/project-harness/SKILL.md").write_text("user edit", encoding="utf-8")
        before = snapshot(self.root)
        code, out, err = self.run_cli("status", tty=False)
        report = json.loads(out)
        self.assertEqual((code, report["state"]), (1, "invalid"), err)
        self.assertEqual(report["nextCommand"], "harness-codex doctor --project PATH")
        self.assertEqual(report["summary"]["managedArtifacts"], "failed")
        self.assertEqual(report["summary"]["sourceEvidence"], "failed")
        code, out, err = self.run_cli("doctor", tty=False)
        self.assertEqual(code, 1, err)
        self.assertFalse(json.loads(out)["valid"])
        self.assertEqual(json.loads(out)["summary"], report["summary"])
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.log.exists())

    def test_project_under_git_metadata_is_refused(self):
        self.root = self.root / ".git/objects"
        self.root.mkdir(parents=True)
        code, out, err = self.run_cli("init", "--install-only")
        self.assertEqual(code, 1)
        self.assertIn("Git metadata", err)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_project_is_not_implicitly_created(self):
        self.root = self.root / "missing"
        code, out, err = self.run_cli("init", "--install-only")
        self.assertEqual(code, 1)
        self.assertIn("existing directory", err)
        self.assertFalse(self.root.exists())

    def test_interrupt_signal_and_spawn_failure_have_explicit_outcomes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with mock.patch.object(project.subprocess, "run", side_effect=KeyboardInterrupt):
                self.assertEqual(project._launch(["codex"], self.root, "task"), 130)
            with mock.patch.object(project.subprocess, "run", return_value=mock.Mock(returncode=-15)):
                self.assertEqual(project._launch(["codex"], self.root, "task"), 143)
            with mock.patch.object(project.subprocess, "run", side_effect=OSError("cannot execute")):
                with self.assertRaisesRegex(project.ProjectError, "Could not launch Codex"):
                    project._launch(["codex"], self.root, "task")


if __name__ == "__main__":
    unittest.main()
