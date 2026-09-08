"""CLI routing and between-session update policy; no network or live Codex."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import argparse
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from harness_cli import distribution
from harness_cli import main as cli


class CliRoutingTests(unittest.TestCase):
    def command_names(self):
        return next(action.choices for action in cli.build_parser(REPO)._actions
                    if isinstance(action, argparse._SubParsersAction))

    def test_agent_defaults_to_codex_with_hidden_runtime_alias_before_or_after_commands(self):
        parser = cli.build_parser(REPO)
        self.assertEqual(parser.parse_args(["start"]).runtime, "codex")
        for flag in ("--agent", "--runtime"):
            for command in self.command_names():
                for arguments in ([flag, "codex", command], [command, flag, "codex"], [command, flag + "=codex"]):
                    self.assertEqual(parser.parse_args(arguments).runtime, "codex")

    def test_claude_agent_and_alias_are_rejected_before_environment_network_or_writes(self):
        for flag in ("--agent", "--runtime"):
            for command in self.command_names():
                for arguments in ([flag, "claude", command], [command, flag, "claude"]):
                    with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()) as output:
                        with mock.patch.object(cli, "_environment") as environment, mock.patch.object(cli, "_automatic_update") as automatic, mock.patch.object(cli, "run_project_command") as project, mock.patch.object(distribution, "install_tool") as install, mock.patch.object(distribution, "update_tool") as update, mock.patch.object(cli, "preflight_project_command") as preflight:
                            self.assertEqual(cli.main(arguments, source_root=REPO), 2)
                            self.assertIn("not implemented", output.getvalue())
                            for operation in (environment, automatic, project, install, update, preflight):
                                operation.assert_not_called()

    def test_conflicting_agent_and_runtime_selections_are_rejected_before_work(self):
        for arguments in (["--agent", "claude", "start", "--runtime", "codex"],
                          ["--runtime", "codex", "start", "--agent", "claude"],
                          ["start", "--agent", "claude", "--agent", "codex"],
                          ["--runtime=claude", "--agent=codex", "install"]):
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()) as output:
                with mock.patch.object(cli, "_environment") as environment:
                    with self.assertRaises(SystemExit) as failure:
                        cli.main(arguments, source_root=REPO)
                    self.assertEqual(failure.exception.code, 2)
                    self.assertIn("Conflicting", output.getvalue())
                    environment.assert_not_called()
        parsed = cli.build_parser(REPO).parse_args(["--runtime", "codex", "start", "--agent", "codex"])
        self.assertEqual(parsed.runtime, "codex")

    def test_help_advertises_agent_and_hides_runtime_alias(self):
        for arguments in (["--help"], *([command, "--help"] for command in self.command_names())):
            with self.subTest(arguments=arguments), redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as exit_status:
                    cli.main(arguments, source_root=REPO)
                self.assertEqual(exit_status.exception.code, 0)
                self.assertIn("--agent", output.getvalue())
                self.assertNotIn("--runtime", output.getvalue())

    def test_unsupported_runtime_version_and_unknown_runtime_do_not_look_supported(self):
        with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()), mock.patch.object(cli, "_environment") as environment:
            self.assertEqual(cli.main(["--runtime", "claude", "--version"], source_root=REPO), 2)
            self.assertEqual(output.getvalue(), "")
            with self.assertRaises(SystemExit) as failure:
                cli.main(["--runtime", "unknown", "install"], source_root=REPO)
            self.assertEqual(failure.exception.code, 2)
            environment.assert_not_called()

    def test_help_and_version_do_not_check_environment_update_or_codex(self):
        for arguments in (["--help"], ["--version"], ["init", "--help"], ["update", "--help"]):
            with self.subTest(arguments=arguments), redirect_stdout(io.StringIO()) as output:
                with mock.patch.object(cli, "_environment") as environment, mock.patch.object(cli, "_automatic_update") as update, mock.patch.object(cli, "run_project_command") as project:
                    with self.assertRaises(SystemExit) as raised:
                        cli.main(arguments, source_root=REPO)
                    self.assertEqual(raised.exception.code, 0)
                    self.assertTrue(output.getvalue())
                    environment.assert_not_called()
                    update.assert_not_called()
                    project.assert_not_called()

    def test_no_arguments_print_help_without_environment_or_update_work(self):
        with redirect_stdout(io.StringIO()) as output, mock.patch.object(cli, "_environment") as environment, mock.patch.object(cli, "_automatic_update") as update:
            self.assertEqual(cli.main([], source_root=REPO), 0)
            self.assertIn("init", output.getvalue())
            environment.assert_not_called()
            update.assert_not_called()

    def test_environment_validation_uses_interpreter_not_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / "unrelated"
            prefix.mkdir()
            (prefix / "conda-meta").mkdir()
            (prefix / "conda-meta/history").write_text("fixture", encoding="utf-8")
            with mock.patch.object(sys, "prefix", str(prefix)), mock.patch.dict(os.environ, {"CONDA_DEFAULT_ENV": "harness", "CONDA_PREFIX": str(prefix.parent / "harness")}):
                with self.assertRaisesRegex(ValueError, "dedicated Conda"):
                    cli._environment()

    def test_update_check_is_read_only_and_propagates_selected_options(self):
        with redirect_stdout(io.StringIO()), mock.patch.object(cli, "_environment"), mock.patch.object(distribution, "check_update", return_value={"status": "up-to-date"}) as check, mock.patch.object(distribution, "update_tool") as update:
            status = cli.main(["update", "--check", "--data-dir", "a tool path", "--branch", "codex/v9.2", "--timeout", "7"], source_root=REPO)
            self.assertEqual(status, 0)
            check.assert_called_once_with(Path("a tool path"), branch="codex/v9.2", repository=None, timeout=7.0)
            update.assert_not_called()

    def test_project_exit_status_is_preserved(self):
        with mock.patch.object(cli, "_environment"), mock.patch.object(cli, "preflight_project_command"), mock.patch.object(cli, "_automatic_update", return_value=None), mock.patch.object(cli, "run_project_command", return_value=37):
            self.assertEqual(cli.main(["start", "--no-update-check"], source_root=REPO), 37)

    def test_invalid_project_preflight_precedes_auto_update(self):
        with redirect_stderr(io.StringIO()), mock.patch.object(cli, "_environment"), mock.patch.object(cli, "preflight_project_command", side_effect=ValueError("invalid goal file")), mock.patch.object(cli, "_automatic_update") as update, mock.patch.object(cli, "run_project_command") as project:
            self.assertEqual(cli.main(["init"], source_root=REPO), 1)
            update.assert_not_called()
            project.assert_not_called()

    def test_interruption_returns_conventional_status(self):
        with redirect_stderr(io.StringIO()), mock.patch.object(cli, "_environment", side_effect=KeyboardInterrupt):
            self.assertEqual(cli.main(["doctor"], source_root=REPO), 130)


class AutomaticUpdateTests(unittest.TestCase):
    @contextmanager
    def fixtures(self, *, policy="compatible", available="9.3", due=True, tty=True, stdout_tty=True):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {"HARNESS_TOOL_HOME": "unused-tool-root"}, clear=True))
            stack.enter_context(mock.patch.object(sys.stdin, "isatty", return_value=tty))
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(mock.patch.object(sys.stdout, "isatty", return_value=stdout_tty))
            stderr = stack.enter_context(redirect_stderr(io.StringIO()))
            values = {
                "state": stack.enter_context(mock.patch.object(distribution, "installed_status", return_value={"auto_update": policy, "release_root": str(REPO)})),
                "due": stack.enter_context(mock.patch.object(distribution, "check_due", return_value=due)),
                "mark": stack.enter_context(mock.patch.object(distribution, "mark_check")),
                "check": stack.enter_context(mock.patch.object(distribution, "check_update", return_value={"updateAvailable": True, "availableVersion": available, "branch": "codex/v" + available})),
                "update": stack.enter_context(mock.patch.object(distribution, "update_tool", return_value={"updated": True})),
                "call": stack.enter_context(mock.patch.object(subprocess, "call", return_value=29)),
                "stderr": stderr,
            }
            yield SimpleNamespace(**values)

    def arguments(self, **overrides):
        return SimpleNamespace(**{"command": "start", "dry_run": False, "install_only": False, "no_update_check": False, **overrides})

    def test_dry_run_install_only_doctor_and_opt_out_never_touch_update_state(self):
        for overrides in ({"command": "init", "dry_run": True}, {"command": "init", "install_only": True},
                          {"command": "init", "_existing_init_noop": True}, {"command": "doctor"},
                          {"command": "reset"}, {"command": "remove"}, {"command": "status"}, {"no_update_check": True}):
            with self.subTest(overrides=overrides), self.fixtures() as mocks:
                self.assertIsNone(cli._automatic_update(self.arguments(**overrides), REPO, ["start"]))
                mocks.state.assert_not_called()
                mocks.mark.assert_not_called()
                mocks.check.assert_not_called()
                mocks.update.assert_not_called()

    def test_off_nonterminal_and_cached_check_never_access_upstream(self):
        for options in ({"policy": "off"}, {"tty": False}, {"due": False}):
            with self.subTest(options=options), self.fixtures(**options) as mocks:
                self.assertIsNone(cli._automatic_update(self.arguments(), REPO, ["start"]))
                mocks.mark.assert_not_called()
                mocks.check.assert_not_called()
                mocks.update.assert_not_called()

    def test_explicit_environment_opt_out_never_reads_installation(self):
        with self.fixtures() as mocks, mock.patch.dict(os.environ, {"HARNESS_NO_UPDATE_CHECK": "1"}):
            self.assertIsNone(cli._automatic_update(self.arguments(), REPO, ["start"]))
            mocks.state.assert_not_called()

    def test_redirected_stdout_does_not_update_before_terminal_error(self):
        with self.fixtures(tty=True, stdout_tty=False) as mocks:
            self.assertIsNone(cli._automatic_update(self.arguments(), REPO, ["start"]))
            mocks.state.assert_not_called()
            mocks.mark.assert_not_called()
            mocks.check.assert_not_called()
            mocks.update.assert_not_called()
            mocks.call.assert_not_called()

    def test_check_policy_and_new_major_only_notify(self):
        for options in ({"policy": "check"}, {"available": "10.0"}):
            with self.subTest(options=options), self.fixtures(**options) as mocks:
                self.assertIsNone(cli._automatic_update(self.arguments(), REPO, ["start"]))
                mocks.mark.assert_called_once()
                mocks.check.assert_called_once()
                mocks.update.assert_not_called()
                mocks.call.assert_not_called()
                self.assertIn("harness-codex update", mocks.stderr.getvalue())

    def test_up_to_date_does_not_download(self):
        with self.fixtures() as mocks:
            mocks.check.return_value = {"updateAvailable": False}
            self.assertIsNone(cli._automatic_update(self.arguments(), REPO, ["start"]))
            mocks.update.assert_not_called()
            mocks.call.assert_not_called()

    def test_network_or_candidate_failure_leaves_project_command_available(self):
        for failure in ("check", "update"):
            with self.subTest(failure=failure), self.fixtures() as mocks:
                getattr(mocks, failure).side_effect = distribution.DistributionError("offline or invalid candidate")
                self.assertIsNone(cli._automatic_update(self.arguments(), REPO, ["start"]))
                mocks.mark.assert_called_once()
                mocks.call.assert_not_called()
                self.assertIn("continuing with the installed version", mocks.stderr.getvalue())

    def test_compatible_update_relaunches_same_argv_without_permission_overrides(self):
        with self.fixtures() as mocks:
            newer = REPO.parent / "new release"
            mocks.state.side_effect = [{"auto_update": "compatible"}, {"release_root": str(newer)}]
            arguments = ["start", "--project", "a path with spaces", "Fix $HOME; preserve user choices"]
            self.assertEqual(cli._automatic_update(self.arguments(), REPO, arguments), 29)
            mocks.update.assert_called_once()
            self.assertEqual(mocks.update.call_args.kwargs["expected_major"], 9)
            command = mocks.call.call_args.args[0]
            self.assertEqual(command, [sys.executable, "-B", str(newer / "harness.py"), *arguments])
            self.assertEqual(mocks.call.call_args.kwargs["env"]["HARNESS_NO_UPDATE_CHECK"], "1")
            self.assertFalse(any(flag in command for flag in ("--dangerously-bypass-approvals-and-sandbox", "--full-auto", "--model", "--sandbox")))


class InstalledEntryPointTests(unittest.TestCase):
    def test_user_local_launcher_runs_help_and_version_outside_source_checkout(self):
        with tempfile.TemporaryDirectory(prefix="harness-cli-entry-") as temporary:
            root = Path(temporary)
            data = root / "tool data"
            installed = distribution.install_tool(REPO, data, root / "command bin", python_executable=sys.executable, auto_update="off")
            expected_version = cli.version(REPO)
            self.assertEqual(installed["version"], expected_version)
            for option in ("--version", "--help"):
                result = subprocess.run([sys.executable, "-B", str(data / "launcher.py"), option], cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(expected_version if option == "--version" else "init", result.stdout)
            self.assertFalse((data / "last-check.json").exists())


if __name__ == "__main__":
    unittest.main()
