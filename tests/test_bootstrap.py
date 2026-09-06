"""Exercise the downloadable Bash bootstrap without real network or model calls."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = REPO_ROOT / "install_harness.sh"
BASH = (shutil.which("bash") if os.name != "nt" else
        next((str(path) for path in (Path("C:/Program Files/Git/bin/bash.exe"),)
              if path.is_file()), None))


@unittest.skipUnless(BASH, "Bash is unavailable")
class BootstrapOfflineTests(unittest.TestCase):
    def run_offline(self, *arguments, token=None):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            environment = os.environ.copy()
            environment.update({"PATH": str(base), "TMPDIR": str(base / "must-not-be-created")})
            for name in ("GITHUB_TOKEN", "GH_TOKEN"):
                environment.pop(name, None)
            if token is not None:
                environment["GITHUB_TOKEN"] = token
            result = subprocess.run([BASH, str(BOOTSTRAP), *arguments], env=environment,
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(list(base.iterdir()), [])
            return result

    def test_help_is_offline_and_requires_no_git_or_conda(self):
        result = self.run_offline("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Git author name/email do not authenticate", result.stdout)

    def test_claude_is_rejected_before_network_temp_or_conda(self):
        result = self.run_offline("--runtime", "claude")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Claude support is not implemented", result.stderr)

    def test_foreign_repository_and_invalid_branch_are_rejected_early(self):
        for args in (("--repository", "https://example.invalid/other/repo.git"),
                     ("--branch", "claude/v2"), ("--branch", "codex/v09.3"),
                     ("--auto-update", "always")):
            with self.subTest(args=args):
                self.assertEqual(self.run_offline(*args).returncode, 1)

    def test_token_control_characters_are_rejected_without_echo(self):
        token = "fixture-secret\nunsafe-header"
        result = self.run_offline(token=token)
        self.assertEqual(result.returncode, 1)
        self.assertIn("control characters", result.stderr)
        self.assertNotIn("fixture-secret", result.stdout + result.stderr)

    def test_unpacked_source_installer_rejects_claude_before_conda(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            marker = base / "conda-was-called"
            fake_conda = base / "fake-conda"
            fake_conda.write_text('#!/usr/bin/env bash\nprintf called > "$HARNESS_TEST_CONDA_MARKER"\nexit 23\n',
                                  encoding="utf-8")
            fake_conda.chmod(0o755)
            environment = {**os.environ, "CONDA_EXE": fake_conda.as_posix(),
                           "HARNESS_TEST_CONDA_MARKER": marker.as_posix()}
            for arguments in (("--runtime", "claude"), ("--runtime=claude",)):
                with self.subTest(arguments=arguments):
                    result = subprocess.run([BASH, str(REPO_ROOT / "install.sh"), *arguments],
                                            env=environment, capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("Claude integration is not implemented", result.stderr)
                    self.assertFalse(marker.exists())


FAKE_GIT = r'''import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
commands = {"ls-remote", "init", "fetch", "rev-parse", "ls-tree", "update-ref", "read-tree", "archive", "status"}
command = next((value for value in args if value in commands), "other")
https = "https://github.com/sholee-pt/Harness.git"
transports = {https, "git@github.com:sholee-pt/Harness.git", "ssh://git@github.com/sholee-pt/Harness.git"}
network = command in {"ls-remote", "fetch"}
record = {"argv": args, "command": command, "contextClean": not any(name in os.environ for name in
          ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"))}
if network:
    record["sshCommandPreserved"] = os.environ.get("GIT_SSH_COMMAND") == os.environ.get("HARNESS_TEST_SSH_COMMAND")
    record["sshPromptsDisabled"] = os.environ.get("SSH_ASKPASS") == "/bin/false" and os.environ.get("SSH_ASKPASS_REQUIRE") == "force"
helper = os.environ.get("GIT_ASKPASS", "")
if network and https in args and helper.endswith("askpass.sh"):
    expected = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")
    source = pathlib.Path(helper).read_text(encoding="utf-8")
    answer = subprocess.run(["bash", helper, "Password for 'https://x-access-token@github.com/sholee-pt/Harness.git': "],
                            capture_output=True, text=True, check=False)
    foreign = subprocess.run(["bash", helper, "Password for 'https://x-access-token@example.invalid': "],
                             capture_output=True, text=True, check=False)
    record.update({"tokenCorrect": answer.returncode == 0 and answer.stdout == expected + "\n",
                   "tokenAbsentFromHelper": expected not in source,
                   "foreignOriginRefused": foreign.returncode != 0,
                   "credentialStoreDisabled": "credential.helper=" in args})
with pathlib.Path(os.environ["HARNESS_TEST_GIT_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record) + "\n")
if network and os.environ.get("HARNESS_TEST_AUTH_FAIL") == "1":
    print("fixture authentication failure", file=sys.stderr)
    raise SystemExit(128)
if network and https in args and os.environ.get("HARNESS_TEST_HTTPS_FAIL") == "1":
    raise SystemExit(128)
if command == "fetch" and os.environ.get("HARNESS_TEST_FETCH_FAIL") == "1":
    raise SystemExit(128)
if command == "rev-parse" and "FETCH_HEAD^{commit}" in args and os.environ.get("HARNESS_TEST_FETCH_MISMATCH") == "1":
    print("f" * 40)
    raise SystemExit(0)
unsafe = os.environ.get("HARNESS_TEST_UNSAFE_TREE", "")
if command == "ls-tree" and unsafe:
    mode, kind, size, path = {
        "link": ("120000", "blob", "8", "linked-file"),
        "submodule": ("160000", "commit", "-", "submodule"),
        "traversal": ("100644", "blob", "8", "../escape"),
        "git": ("100644", "blob", "8", ".git/config"),
        "control": ("100644", "blob", "8", "bad\npath"),
    }[unsafe]
    sys.stdout.buffer.write((mode + " " + kind + " " + "a" * 40 + " " + size + "\t" + path + "\0").encode())
    raise SystemExit(0)
mapped = [os.environ["HARNESS_TEST_SOURCE"] if value in transports else
          "protocol.file.allow=always" if value == "protocol.file.allow=never" else value for value in args]
if command == "ls-remote" and os.environ.get("HARNESS_TEST_VERSION_MISMATCH") == "1":
    print(os.environ["HARNESS_TEST_LATEST_SHA"] + "\trefs/heads/codex/v9.11")
    raise SystemExit(0)
raise SystemExit(subprocess.run([os.environ["HARNESS_TEST_REAL_GIT"], *mapped], check=False).returncode)
'''


FAKE_CONDA = r'''import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
with pathlib.Path(os.environ["HARNESS_TEST_CONDA_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(args) + "\n")
if args == ["env", "list", "--json"]:
    print(json.dumps({"envs": [sys.prefix]}))
    raise SystemExit(0)
if args[:6] == ["run", "--no-capture-output", "-n", "harness", "python", "-B"]:
    raise SystemExit(subprocess.run([sys.executable, "-B", *args[6:]], check=False).returncode)
raise SystemExit("Unexpected Conda operation in bootstrap fixture")
'''


@unittest.skipUnless(os.name == "posix" and BASH and shutil.which("git") and shutil.which("tar"),
                     "Linux bootstrap integration requires POSIX Bash/Git/tar")
class BootstrapIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.base = Path(cls.temporary.name)
        cls.source = cls.base / "upstream source"
        cls.source.mkdir()
        cls.real_git = shutil.which("git")
        sys.path.insert(0, str(REPO_ROOT))
        import build_release
        for name in build_release.ROOT_FILES:
            shutil.copyfile(REPO_ROOT / name, cls.source / name)
        for name in build_release.ROOT_DIRS:
            shutil.copytree(REPO_ROOT / name, cls.source / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        cls.git("init", "--quiet")
        cls.git("config", "core.autocrlf", "false")
        metadata = cls.source / ".agents/skills/harness/scripts/harness_metadata.py"
        original = metadata.read_text(encoding="utf-8")
        cls.commits = {}
        for version in ("9.9", "9.10"):
            metadata.write_text(re.sub(r'^HARNESS_VERSION = "[^"]+"', f'HARNESS_VERSION = "{version}"',
                                       original, flags=re.MULTILINE), encoding="utf-8")
            cls.git("add", "--all")
            cls.git("-c", "user.name=Harness fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", f"Fixture {version}")
            cls.commits[version] = cls.git("rev-parse", "HEAD").stdout.strip()
            cls.git("branch", f"codex/v{version}")
        cls.git("branch", "claude/v999")
        cls.git("branch", "codex/v099.1")

    @classmethod
    def git(cls, *arguments):
        environment = os.environ.copy()
        for name in tuple(environment):
            if name.startswith("GIT_"):
                environment.pop(name, None)
        return subprocess.run([cls.real_git, "-c", "safe.directory=" + cls.source.as_posix(), "-C", str(cls.source), *arguments],
                              env=environment, capture_output=True, text=True, encoding="utf-8", check=True)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.commands = self.directory / "commands"
        self.commands.mkdir()
        self.scratch = self.directory / "scratch"
        self.scratch.mkdir()
        self.project = self.directory / "project with spaces"
        self.project.mkdir()
        (self.project / ".git").mkdir()
        (self.project / ".git/config").write_bytes(b"project metadata sentinel\n")
        (self.project / "source.py").write_bytes(b"# existing source\n")
        self.data = self.directory / "tool data"
        self.bin_dir = self.directory / "tool bin"
        self.git_log = self.directory / "git.jsonl"
        self.conda_log = self.directory / "conda.jsonl"
        self.environment = os.environ.copy()
        for name in tuple(self.environment):
            if name.startswith("GIT_") or name in {"GITHUB_TOKEN", "GH_TOKEN", "HARNESS_TOOL_HOME", "HARNESS_NO_UPDATE_CHECK"}:
                self.environment.pop(name, None)
        for name, content in (("fake_git.py", FAKE_GIT), ("fake_conda.py", FAKE_CONDA)):
            (self.directory / name).write_text(content, encoding="utf-8")
        for command, script in (("git", "fake_git.py"), ("conda", "fake_conda.py")):
            wrapper = self.commands / command
            wrapper.write_text('#!/usr/bin/env bash\nexec "$HARNESS_TEST_PYTHON" -B "$HARNESS_TEST_FIXTURE_DIR/' + script + '" "$@"\n', encoding="utf-8")
            wrapper.chmod(0o755)
        self.environment.update({
            "PATH": str(self.commands) + os.pathsep + os.environ["PATH"],
            "TMPDIR": str(self.scratch), "HOME": str(self.directory),
            "CONDA_EXE": str(self.commands / "conda"),
            "HARNESS_TEST_PYTHON": sys.executable, "HARNESS_TEST_FIXTURE_DIR": str(self.directory),
            "HARNESS_TEST_SOURCE": str(self.source), "HARNESS_TEST_REAL_GIT": self.real_git,
            "HARNESS_TEST_GIT_LOG": str(self.git_log), "HARNESS_TEST_CONDA_LOG": str(self.conda_log),
            "HARNESS_TEST_LATEST_SHA": self.commits["9.10"],
        })

    def records(self):
        return [json.loads(line) for line in self.git_log.read_text(encoding="utf-8").splitlines()] if self.git_log.exists() else []

    def run_bootstrap(self, *arguments, trace=False):
        before = {str(path.relative_to(self.project)): (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.project.rglob("*") if path.is_file()}
        result = subprocess.run([BASH, *(["-x"] if trace else []), str(BOOTSTRAP),
                                 "--data-dir", str(self.data), "--bin-dir", str(self.bin_dir), *arguments],
                                cwd=self.project, env=self.environment, capture_output=True, text=True,
                                encoding="utf-8", timeout=90)
        self.assertEqual(list(self.scratch.iterdir()), [])
        after = {str(path.relative_to(self.project)): (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in self.project.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        return result

    def test_latest_numeric_codex_revision_installs_actual_cli_with_provenance(self):
        result = self.run_bootstrap("--auto-update", "off")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        active = json.loads((self.data / "active.json").read_text(encoding="utf-8"))
        self.assertEqual(active["version"], "9.10")
        self.assertEqual(active["commit"], self.commits["9.10"])
        self.assertIsNone(active["branch"])
        self.assertEqual(active["auto_update"], "off")
        version = subprocess.run([str(self.bin_dir / "harness"), "--version"], env=self.environment,
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertIn("9.10", version.stdout)
        fetches = [record["argv"] for record in self.records() if record["command"] == "fetch"]
        self.assertEqual(len(fetches), 1)
        self.assertEqual(fetches[0][-1], self.commits["9.10"])

    def test_explicit_branch_and_ssh_transport_are_preserved(self):
        transport = "ssh://git@github.com/sholee-pt/Harness.git"
        result = self.run_bootstrap("--branch", "codex/v9.9", "--repository", transport)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        active = json.loads((self.data / "active.json").read_text(encoding="utf-8"))
        self.assertEqual(active["version"], "9.9")
        self.assertEqual(active["branch"], "codex/v9.9")
        self.assertEqual(active["repository"], transport)

    def test_https_failure_falls_back_to_known_ssh_transport(self):
        self.environment["HARNESS_TEST_HTTPS_FAIL"] = "1"
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        active = json.loads((self.data / "active.json").read_text(encoding="utf-8"))
        self.assertEqual(active["repository"], "git@github.com:sholee-pt/Harness.git")

    def test_existing_ssh_identity_command_is_preserved_without_prompting(self):
        command = 'ssh -i "/home/fixture/key with spaces" -o IdentitiesOnly=yes'
        self.environment.update({"GIT_SSH_COMMAND": command, "HARNESS_TEST_SSH_COMMAND": command})
        result = self.run_bootstrap("--repository", "git@github.com:sholee-pt/Harness.git")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        network = [record for record in self.records() if record["command"] in {"ls-remote", "fetch"}]
        self.assertTrue(network)
        self.assertTrue(all(record["sshCommandPreserved"] and record["sshPromptsDisabled"] for record in network))

    def test_token_helper_is_ephemeral_origin_scoped_and_never_logged(self):
        token = "github_pat.fixture-JWT.value_with-hyphens"
        self.environment.update({"GITHUB_TOKEN": token, "GH_TOKEN": "lower-priority-token"})
        result = self.run_bootstrap(trace=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        probes = [record for record in self.records() if "tokenCorrect" in record]
        self.assertTrue(probes)
        self.assertTrue(all(record["tokenCorrect"] and record["tokenAbsentFromHelper"]
                            and record["foreignOriginRefused"] and record["credentialStoreDisabled"] for record in probes))
        combined = result.stdout + result.stderr + self.git_log.read_text(encoding="utf-8") + self.conda_log.read_text(encoding="utf-8")
        self.assertNotIn(token, combined)
        self.assertNotIn("lower-priority-token", combined)
        for path in self.data.rglob("*"):
            if path.is_file():
                self.assertNotIn(token.encode(), path.read_bytes(), str(path))

    def test_missing_authentication_stops_before_conda_and_installation(self):
        self.environment["HARNESS_TEST_AUTH_FAIL"] = "1"
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 1)
        self.assertIn("name/email are not authentication", result.stderr)
        self.assertFalse(self.conda_log.exists())
        self.assertFalse(self.data.exists())
        self.assertFalse(self.bin_dir.exists())

    def test_failed_fetch_preserves_existing_installation(self):
        self.data.mkdir()
        sentinel = self.data / "user-owned-file"
        sentinel.write_bytes(b"existing installation sentinel\n")
        original = sentinel.stat().st_mtime_ns
        self.environment["HARNESS_TEST_FETCH_FAIL"] = "1"
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(list(self.data.iterdir()), [sentinel])
        self.assertEqual(sentinel.stat().st_mtime_ns, original)
        self.assertFalse(self.conda_log.exists())

    def test_fetched_commit_mismatch_is_rejected_before_installer(self):
        self.environment["HARNESS_TEST_FETCH_MISMATCH"] = "1"
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 1)
        self.assertIn("differs", result.stderr)
        self.assertFalse(self.conda_log.exists())

    def test_links_submodules_and_unsafe_paths_are_rejected_before_extraction(self):
        for kind in ("link", "submodule", "traversal", "git", "control"):
            with self.subTest(kind=kind):
                self.environment["HARNESS_TEST_UNSAFE_TREE"] = kind
                result = self.run_bootstrap()
                self.assertEqual(result.returncode, 1)
                self.assertFalse(self.conda_log.exists())
                self.assertFalse(self.data.exists())
                self.assertFalse((self.directory / "escape").exists())

    def test_branch_version_mismatch_is_rejected_before_execution(self):
        self.environment["HARNESS_TEST_VERSION_MISMATCH"] = "1"
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not match", result.stderr)
        self.assertFalse(self.conda_log.exists())

    def test_git_environment_injection_is_removed_only_from_git_commands(self):
        self.environment.update({"GIT_DIR": str(self.project / ".git"), "GIT_WORK_TREE": str(self.project),
                                 "GIT_INDEX_FILE": str(self.project / ".git/index"), "GIT_CONFIG_COUNT": "1",
                                 "GIT_CONFIG_KEY_0": "core.worktree", "GIT_CONFIG_VALUE_0": str(self.project)})
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(all(record["contextClean"] for record in self.records()))
        self.assertFalse((self.project / ".git/index").exists())


if __name__ == "__main__":
    unittest.main()
