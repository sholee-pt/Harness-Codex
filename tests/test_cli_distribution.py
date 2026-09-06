"""Managed CLI install/update ownership and failure behavior, without a remote."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

from harness_cli import distribution as dist


A = "a" * 40
B = "b" * 40
C = "c" * 40


def files(root):
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns) for path in root.rglob("*") if path.is_file()}


def source(root, version="9.2", commit=A):
    root.mkdir(parents=True, exist_ok=True)
    for name in dist.REQUIRED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n" if name.endswith(".py") else "Harness\n", encoding="utf-8")
    (root / dist.METADATA).write_text(f'HARNESS_VERSION = "{version}"\n', encoding="utf-8")
    (root / "harness.py").write_text('import os, sys\nprint("fake-harness", *sys.argv[1:])\nprint(os.environ.get("HARNESS_TOOL_HOME", "missing"))\n', encoding="utf-8")
    if commit:
        (root / "_release.json").write_text(json.dumps({"version": version, "commit": commit, "branch": f"codex/v{version}"}), encoding="utf-8")
    return root


def archive(source_root, archive_path, extra=()):
    with tarfile.open(archive_path, "w") as bundle:
        for path in sorted(source_root.rglob("*")):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(source_root).as_posix(), recursive=False)
        for name, data, kind in extra:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            if kind == tarfile.REGTYPE:
                entry.size = len(data)
                bundle.addfile(entry, io.BytesIO(data))
            else:
                entry.linkname = data.decode()
                bundle.addfile(entry)


class DistributionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = source(self.base / "source")
        self.data = self.base / "tool data"
        self.bin = self.base / "bin dir"
        self.candidate = source(self.base / "candidate", "9.3", B)
        self.calls = []
        self.heads = f"{B}\trefs/heads/codex/v9.3\n"
        self.ancestor_code = 0
        self.resolved = B
        self.archive_extra = ()

    def install(self, **kwargs):
        return dist.install_tool(self.source, self.data, self.bin, sys.executable, **kwargs)

    def fake_git(self, arguments, **kwargs):
        self.calls.append(arguments)
        stdout = b""
        code = 0
        if arguments[0] == "ls-remote":
            stdout = self.heads.encode()
        elif "rev-parse" in arguments:
            stdout = (self.resolved + "\n").encode()
        elif "merge-base" in arguments:
            code = self.ancestor_code
        elif "archive" in arguments:
            output = next(item.removeprefix("--output=") for item in arguments if item.startswith("--output="))
            archive(self.candidate, Path(output), self.archive_extra)
        return subprocess.CompletedProcess(arguments, code, stdout, b"")

    def update(self, **kwargs):
        with mock.patch.object(dist, "_git", side_effect=self.fake_git):
            return dist.update_tool(self.data, **kwargs)

    def test_install_has_owned_runtime_and_working_launcher(self):
        (self.source / "tests").mkdir()
        (self.source / "tests/user-data.txt").write_text("excluded")
        state = self.install()
        self.assertEqual(state["version"], "9.2")
        self.assertEqual(state["auto_update"], "compatible")
        self.assertEqual(state["releaseId"], A)
        self.assertFalse((Path(state["sourceRoot"]) / "tests").exists())
        invoked = subprocess.run([sys.executable, "-B", str(self.data / "launcher.py"), "--version"], capture_output=True, text=True, check=True)
        self.assertIn("fake-harness --version", invoked.stdout)
        self.assertIn(str(self.data), invoked.stdout)
        self.assertFalse(list(self.data.rglob("__pycache__")))
        if os.name != "nt":
            direct = subprocess.run([str(self.bin / "harness"), "--help"], capture_output=True, text=True, check=True)
            self.assertIn("fake-harness --help", direct.stdout)

    def test_install_without_git_uses_content_hash_identity(self):
        (self.source / "_release.json").unlink()
        state = self.install(auto_update="off")
        self.assertIsNone(state["commit"])
        self.assertEqual(state["releaseId"], "content-" + state["treeHash"])
        self.assertEqual(state["auto_update"], "off")

    def test_repeat_install_keeps_release_and_launcher(self):
        first = self.install()
        source_before = files(Path(first["release_root"]))
        launcher_before = files(self.bin)
        repeated = self.install()
        self.assertEqual(first, repeated)
        self.assertEqual(source_before, files(Path(first["release_root"])))
        self.assertEqual(launcher_before, files(self.bin))

    def test_installed_command_can_change_its_policy_without_losing_provenance(self):
        first = self.install()
        state = dist.install_tool(first["sourceRoot"], self.data, self.bin, sys.executable, auto_update="off")
        self.assertEqual(state["auto_update"], "off")
        self.assertEqual(state["commit"], A)
        self.assertEqual(first["treeHash"], state["treeHash"])

    def test_unowned_tool_directory_is_preserved(self):
        self.data.mkdir()
        (self.data / "user.txt").write_text("original")
        before = files(self.data)
        with self.assertRaises(dist.DistributionError):
            self.install()
        self.assertEqual(before, files(self.data))
        self.assertFalse(self.bin.exists())

    def test_unowned_launcher_is_preserved_without_state_creation(self):
        self.bin.mkdir()
        (self.bin / "harness").write_text("existing tool")
        before = files(self.bin)
        with self.assertRaisesRegex(dist.DistributionError, "user-owned"):
            self.install()
        self.assertEqual(before, files(self.bin))
        self.assertFalse(self.data.exists())

    def test_tool_data_and_bin_paths_inside_git_metadata_are_refused(self):
        project = self.base / "project"
        metadata = project / ".git"
        metadata.mkdir(parents=True)
        (metadata / "config").write_text("user Git configuration")
        before = files(project)
        for data_dir, bin_dir in ((metadata / "tool", self.bin), (self.data, metadata / "bin")):
            with self.subTest(data_dir=data_dir, bin_dir=bin_dir):
                with self.assertRaisesRegex(dist.DistributionError, "Git metadata"):
                    dist.install_tool(self.source, data_dir, bin_dir)
                self.assertEqual(before, files(project))
                self.assertFalse(self.data.exists())
                self.assertFalse(self.bin.exists())
        for operation in (dist.mark_check, dist.check_due, dist.check_update, dist.update_tool):
            with self.assertRaisesRegex(dist.DistributionError, "Git metadata"):
                operation(metadata / "tool")
        self.assertEqual(before, files(project))

    def test_changed_source_and_launchers_block_updates(self):
        state = self.install()
        managed = Path(state["sourceRoot"]) / "harness.py"
        original = managed.read_bytes()
        managed.write_text("raise SystemExit('user edit')")
        with self.assertRaisesRegex(dist.DistributionError, "local changes"):
            self.update()
        self.assertEqual(self.calls, [])
        managed.write_bytes(original)
        (self.bin / "harness").write_text("user launcher")
        with self.assertRaisesRegex(dist.DistributionError, "launcher was changed"):
            self.update()
        self.assertEqual(self.calls, [])

    def test_extra_managed_files_and_bytecode_caches_are_refused(self):
        state = self.install()
        extra = Path(state["sourceRoot"]) / "extra.py"
        extra.write_text("user content")
        with self.assertRaisesRegex(dist.DistributionError, "unexpected files"):
            dist.installed_status(self.data)
        extra.unlink()
        cache = Path(state["sourceRoot"]) / "harness_cli/__pycache__"
        cache.mkdir()
        with self.assertRaisesRegex(dist.DistributionError, "bytecode caches"):
            dist.installed_status(self.data)

    def test_loader_rejects_edited_sources_before_running_them(self):
        state = self.install()
        (Path(state["sourceRoot"]) / "harness.py").write_text("print('EDIT WAS EXECUTED')")
        result = subprocess.run([sys.executable, "-B", str(self.data / "launcher.py")], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("EDIT WAS EXECUTED", result.stdout)

    def test_invalid_candidate_source_never_creates_installation(self):
        for missing in ("harness_cli/project.py", "harness.py"):
            path = self.source / missing
            original = path.read_bytes()
            path.unlink()
            with self.assertRaisesRegex(dist.DistributionError, "missing required"):
                self.install()
            self.assertFalse(self.data.exists())
            path.write_bytes(original)
        (self.source / "harness_cli/project.py").write_text("invalid ( python")
        with self.assertRaisesRegex(dist.DistributionError, "syntax"):
            self.install()
        self.assertFalse(self.data.exists())

    def test_numeric_branch_selection_and_read_only_check(self):
        self.install()
        self.heads = f"{C}\trefs/heads/claude/v100\n{A}\trefs/heads/codex/v9.9\n{B}\trefs/heads/codex/v9.10\n{C}\trefs/heads/codex/v9.11-bad\n"
        before = files(self.data)
        with mock.patch.object(dist, "_git", side_effect=self.fake_git):
            check = dist.check_update(self.data)
        self.assertEqual(check["branch"], "codex/v9.10")
        self.assertEqual(check["availableVersion"], "9.10")
        self.assertTrue(check["updateAvailable"])
        self.assertEqual(before, files(self.data))

    def test_pinned_branch_is_queried_and_other_heads_are_ignored(self):
        self.install(branch="codex/v9.2", repository="git@github.com:sholee-pt/Harness.git")
        self.heads = f"{A}\trefs/heads/codex/v9.2\n{B}\trefs/heads/codex/v100\n"
        with mock.patch.object(dist, "_git", side_effect=self.fake_git):
            check = dist.check_update(self.data)
        self.assertEqual(check["status"], "up-to-date")
        self.assertEqual(self.calls[0][-1], "refs/heads/codex/v9.2")
        self.assertIn("git@github.com:sholee-pt/Harness.git", self.calls[0])

    def test_explicit_repo_and_branch_validation_precedes_mutation(self):
        for bad_repo in ("https://token@github.com/sholee-pt/Harness.git", "https://example.org/Harness.git", "/tmp/repo"):
            with self.assertRaises(dist.DistributionError):
                self.install(repository=bad_repo)
        for bad_branch in ("claude/v9.2", "codex/v09.2", "codex/v9.2;command", "../refs/heads/main", "codex/v9.2.1"):
            with self.assertRaises(dist.DistributionError):
                self.install(branch=bad_branch)
        self.assertFalse(self.data.exists())

    def test_update_fetches_resolved_commit_and_preserves_old_release(self):
        old = self.install(auto_update="check")
        old_files = files(Path(old["sourceRoot"]))
        old_launchers = files(self.bin)
        updated = self.update()
        new = updated["installation"]
        self.assertEqual(updated["status"], "updated")
        self.assertEqual(new["commit"], B)
        self.assertEqual(new["version"], "9.3")
        self.assertEqual(new["auto_update"], "check")
        self.assertIsNone(new["branch"])
        self.assertEqual(old_files, files(Path(old["sourceRoot"])))
        self.assertEqual(old_launchers, files(self.bin))
        fetch = next(command for command in self.calls if "fetch" in command)
        self.assertEqual(fetch[-1], B)
        self.assertTrue(any(command[-3:] == ["--is-ancestor", A, B] for command in self.calls))
        self.assertFalse((self.data / ".install.lock").exists())
        self.assertFalse(list(self.data.glob(".download-*")))

    def test_up_to_date_update_does_not_rewrite_active_metadata(self):
        self.install()
        self.heads = f"{A}\trefs/heads/codex/v9.2\n"
        before = files(self.data)
        result = self.update()
        self.assertFalse(result["updated"])
        self.assertEqual(before, files(self.data))
        self.assertEqual(len(self.calls), 1)

    def test_explicit_tracking_selection_is_saved_when_code_is_up_to_date(self):
        self.install()
        self.heads = f"{A}\trefs/heads/codex/v9.2\n"
        result = self.update(branch="codex/v9.2", repository="git@github.com:sholee-pt/Harness.git")
        self.assertFalse(result["updated"])
        self.assertEqual(result["installation"]["branch"], "codex/v9.2")
        self.assertEqual(result["installation"]["repository"], "git@github.com:sholee-pt/Harness.git")

    def test_higher_version_branch_pointing_to_old_commit_is_not_up_to_date(self):
        self.install()
        self.candidate = self.source
        self.resolved = A
        self.heads = f"{A}\trefs/heads/codex/v9.3\n"
        before = files(self.data)
        with mock.patch.object(dist, "_git", side_effect=self.fake_git):
            self.assertTrue(dist.check_update(self.data)["updateAvailable"])
        with self.assertRaisesRegex(dist.DistributionError, "disagrees"):
            self.update()
        self.assertEqual(before, files(self.data))

    def test_downgrades_and_rewritten_history_are_rejected(self):
        self.install()
        before = files(self.data)
        self.heads = f"{B}\trefs/heads/codex/v9.1\n"
        with self.assertRaisesRegex(dist.DistributionError, "downgrade"):
            self.update()
        self.assertEqual(before, files(self.data))
        self.heads = f"{B}\trefs/heads/codex/v9.3\n"
        self.ancestor_code = 1
        with self.assertRaisesRegex(dist.DistributionError, "forward update"):
            self.update()
        self.assertEqual(before, files(self.data))

    def test_same_version_forward_update_requires_known_commit(self):
        self.candidate = source(self.base / "same-version", "9.2", B)
        self.heads = f"{B}\trefs/heads/codex/v9.2\n"
        self.install()
        self.assertTrue(self.update()["updated"])

    def test_same_version_content_only_update_is_refused(self):
        (self.source / "_release.json").unlink()
        self.install()
        self.heads = f"{B}\trefs/heads/codex/v9.2\n"
        before = files(self.data)
        with self.assertRaisesRegex(dist.DistributionError, "provenance"):
            self.update()
        self.assertEqual(before, files(self.data))

    def test_auto_update_checks_major_again_inside_lock(self):
        self.install()
        self.heads = f"{B}\trefs/heads/codex/v10\n"
        before = files(self.data)
        with self.assertRaisesRegex(dist.DistributionError, "major version"):
            self.update(expected_major=9)
        self.assertEqual(before, files(self.data))
        self.assertEqual(len(self.calls), 1)

    def test_candidate_metadata_and_pinned_commit_must_agree(self):
        self.install()
        before = files(self.data)
        self.resolved = C
        with self.assertRaisesRegex(dist.DistributionError, "immutable commit"):
            self.update()
        self.assertEqual(before, files(self.data))
        self.resolved = B
        (self.candidate / "_release.json").write_text(json.dumps({"version": "9.3", "commit": C}))
        with self.assertRaisesRegex(dist.DistributionError, "disagrees"):
            self.update()
        self.assertEqual(before, files(self.data))

    def test_branch_version_mismatch_preserves_active_source(self):
        self.install()
        before = files(self.data)
        self.heads = f"{B}\trefs/heads/codex/v9.4\n"
        with self.assertRaisesRegex(dist.DistributionError, "disagrees"):
            self.update()
        self.assertEqual(before, files(self.data))

    def test_unsafe_archive_members_preserve_active_source(self):
        self.install()
        before = files(self.data)
        for name, value, kind in (("../outside", b"overwrite", tarfile.REGTYPE), ("/absolute", b"overwrite", tarfile.REGTYPE), ("harness_cli/link.py", b"../../outside", tarfile.SYMTYPE), ("harness_cli/hard.py", b"harness.py", tarfile.LNKTYPE), ("C:/drive", b"bad", tarfile.REGTYPE), ("harness_cli/project.py", b"duplicate", tarfile.REGTYPE)):
            with self.subTest(name=name):
                self.archive_extra = [(name, value, kind)]
                with self.assertRaises(dist.DistributionError):
                    self.update()
                self.assertEqual(before, files(self.data))

    def test_source_size_limit_precedes_installation(self):
        with mock.patch.object(dist, "MAX_TREE_BYTES", 20):
            with self.assertRaisesRegex(dist.DistributionError, "limits"):
                self.install()
        self.assertFalse(self.data.exists())

    def test_failed_network_download_preserves_state_and_hides_credentials(self):
        self.install()
        before = files(self.data)
        secret = "https://private-token@github.com/sholee-pt/Harness.git"
        failure = subprocess.CompletedProcess(["git"], 128, b"", secret.encode())
        with mock.patch.object(dist.subprocess, "run", return_value=failure):
            with self.assertRaises(dist.DistributionError) as raised:
                dist.update_tool(self.data)
        self.assertNotIn("private-token", str(raised.exception))
        self.assertEqual(before, files(self.data))

    def test_git_ignores_project_repository_environment(self):
        result = subprocess.CompletedProcess(["git"], 0, b"", b"")
        with mock.patch.dict(os.environ, {"GIT_DIR": "/some/project/.git", "GIT_WORK_TREE": "/some/project", "GIT_INDEX_FILE": "/some/index"}), mock.patch.object(dist.subprocess, "run", return_value=result) as run:
            dist._git(["ls-remote", dist.DEFAULT_REPOSITORY], timeout=1)
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("GIT_DIR", environment)
        self.assertNotIn("GIT_WORK_TREE", environment)
        self.assertNotIn("GIT_INDEX_FILE", environment)
        self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")

    def test_concurrent_install_lock_is_preserved(self):
        self.install()
        lock = self.data / ".install.lock"
        lock.write_text("another owner")
        before = files(self.data)
        with self.assertRaisesRegex(dist.DistributionError, "another installation"):
            self.update()
        self.assertEqual(before, files(self.data))
        self.assertEqual(self.calls, [])

    def test_check_ttl_does_not_write_until_marked(self):
        self.install()
        before = files(self.data)
        self.assertTrue(dist.check_due(self.data, now=100))
        self.assertEqual(before, files(self.data))
        dist.mark_check(self.data, now=100)
        self.assertFalse(dist.check_due(self.data, ttl_seconds=10, now=109))
        self.assertTrue(dist.check_due(self.data, ttl_seconds=10, now=110))
        self.assertTrue(dist.check_due(self.data, ttl_seconds=10, now=90))

    def test_modified_release_during_fetch_is_not_overwritten(self):
        state = self.install()
        edited = Path(state["sourceRoot"]) / "harness_cli/main.py"
        active = (self.data / "active.json").read_bytes()
        def mutate(arguments, **kwargs):
            result = self.fake_git(arguments, **kwargs)
            if "fetch" in arguments:
                edited.write_text("# user edit during download\n")
            return result
        with mock.patch.object(dist, "_git", side_effect=mutate):
            with self.assertRaisesRegex(dist.DistributionError, "local changes"):
                dist.update_tool(self.data)
        self.assertEqual((self.data / "active.json").read_bytes(), active)
        self.assertEqual(edited.read_text(), "# user edit during download\n")
        self.assertFalse((self.data / "releases" / B).exists())

    def test_transient_receipt_and_pointer_failures_are_retryable(self):
        self.install()
        before = files(self.data)
        original_write = dist._write_json
        for failed_name in (B + ".json", "active.json"):
            with self.subTest(failed_name=failed_name):
                def failing_write(path, value):
                    if path.name == failed_name:
                        raise OSError("injected write failure")
                    return original_write(path, value)
                with mock.patch.object(dist, "_write_json", side_effect=failing_write):
                    with self.assertRaisesRegex(OSError, "injected"):
                        self.update()
                self.assertEqual(before, files(self.data))
                self.assertFalse((self.data / "releases" / B).exists())
        self.assertTrue(self.update()["updated"])

    def test_failed_initial_install_preserves_empty_destination_and_retries(self):
        self.data.mkdir()
        self.bin.mkdir()
        original_write = dist._write_json
        def failing_write(path, value):
            if path.name == "active.json":
                raise OSError("injected initial failure")
            return original_write(path, value)
        with mock.patch.object(dist, "_write_json", side_effect=failing_write):
            with self.assertRaisesRegex(OSError, "injected"):
                self.install()
        self.assertTrue(self.data.is_dir())
        self.assertTrue(self.bin.is_dir())
        self.assertEqual(list(self.data.iterdir()), [])
        self.assertEqual(list(self.bin.iterdir()), [])
        self.assertEqual(self.install()["commit"], A)

    def test_rollback_retains_user_changes_to_newly_staged_release(self):
        self.install()
        active_before = (self.data / "active.json").read_bytes()
        original_write = dist._write_json
        def failing_write(path, value):
            if path.name == "active.json":
                (self.data / "releases" / B / "harness.py").write_text("# concurrent user edit\n")
                raise OSError("injected pointer failure")
            return original_write(path, value)
        with mock.patch.object(dist, "_write_json", side_effect=failing_write):
            with self.assertRaisesRegex(OSError, "injected"):
                self.update()
        self.assertEqual((self.data / "active.json").read_bytes(), active_before)
        self.assertEqual((self.data / "releases" / B / "harness.py").read_text(), "# concurrent user edit\n")

    def test_source_and_destination_symlinks_are_rejected(self):
        link = self.base / "linked-data"
        real = self.base / "real-data"
        real.mkdir()
        try:
            link.symlink_to(real, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        with self.assertRaisesRegex(dist.DistributionError, "symlinks"):
            dist.install_tool(self.source, link, self.bin)
        self.assertEqual(list(real.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "POSIX interpreter symlink behavior")
    def test_conda_style_python_symlink_is_supported(self):
        link = self.base / "python"
        link.symlink_to(Path(sys.executable).resolve())
        state = dist.install_tool(self.source, self.data, self.bin, link)
        self.assertEqual(state["python"], str(Path(sys.executable).resolve()))
        invoked = subprocess.run([str(self.bin / "harness"), "--version"], check=True, capture_output=True, text=True)
        self.assertIn("fake-harness --version", invoked.stdout)

    @unittest.skipUnless(shutil.which("git"), "Git required for local provenance fixture")
    def test_clean_checkout_gets_provenance_but_local_edits_do_not(self):
        (self.source / "_release.json").unlink()
        def git(*args):
            subprocess.run(["git", "-c", "safe.directory=" + str(self.source), "-C", str(self.source), *args], check=True, capture_output=True)
        git("init")
        git("add", ".")
        git("-c", "user.name=Harness Test", "-c", "user.email=harness-test@example.invalid", "commit", "-m", "fixture")
        commit = dist._checkout_commit(self.source, dist._snapshot(self.source))
        self.assertRegex(commit, r"^[0-9a-f]{40}$")
        (self.source / "harness_cli/main.py").write_text("# changed\n")
        self.assertIsNone(dist._checkout_commit(self.source, dist._snapshot(self.source)))
        git("checkout", "--", "harness_cli/main.py")
        (self.source / "harness_cli/untracked.py").write_text("# untracked runtime\n")
        self.assertIsNone(dist._checkout_commit(self.source, dist._snapshot(self.source)))


if __name__ == "__main__":
    unittest.main()
