"""Verify release reproducibility, committed payload identity, and output safety."""

from __future__ import annotations

import hashlib
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
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from build import build_release, release_publish, source as build_source
from harness_cli import distribution as dist


class ReleaseBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "release source"
        self.root.mkdir()
        for name in build_source.ROOT_FILES:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / name, self.root / name)
        for name in build_source.ROOT_DIRS:
            shutil.copytree(REPO_ROOT / name, self.root / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        self.git("init", "--quiet")
        self.git("config", "core.autocrlf", "false")
        self.git("add", "--all")
        self.git("-c", "user.name=Harness fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--quiet", "-m", "Isolated release fixture")
        self.commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.version = build_source.release_version(self.root)
        self.output = self.base / "build output"

    def git(self, *arguments):
        return subprocess.run(["git", "-c", "safe.directory=" + self.root.as_posix(), "-C", str(self.root), *arguments],
                              check=True, capture_output=True, text=True, encoding="utf-8")

    def contents(self, artifact):
        with tarfile.open(artifact, "r:gz") as archive:
            prefix = f"harness-codex-{self.version}/"
            files = {}
            for member in archive.getmembers():
                self.assertTrue(member.name.startswith(prefix), member.name)
                self.assertTrue(member.isfile(), member.name)
                self.assertEqual(member.mtime, 0)
                self.assertEqual(member.uid, 0)
                self.assertEqual(member.gid, 0)
                self.assertNotIn("..", Path(member.name).parts)
                relative = member.name[len(prefix):]
                self.assertNotIn(relative, files)
                self.assertEqual(member.mode, 0o755 if relative in {"harness.py", "install.sh"} else 0o644)
                files[relative] = archive.extractfile(member).read()
        return files

    def create_link(self, target, link, *, directory=False):
        if os.name == 'nt' and directory:
            result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.addCleanup(lambda: link.rmdir() if os.path.lexists(link) else None)
            return
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            self.skipTest(f"Symlink creation unavailable: {exc}")

    def test_linux_publication_verifies_real_committed_payload_before_remote_calls(self):
        build_release.build(self.root, self.output)
        notes = self.base / 'notes.md'
        notes.write_text('Fixture release')
        with mock.patch.object(release_publish, '__file__', str(self.root / 'build/release_publish.py')):
            assets, content = release_publish.verified_assets(self.output, self.commit, 'v' + self.version, notes)
            self.assertEqual(set(assets), {f'harness-codex-{self.version}-linux.tar.gz',
                                          'install_harness_codex.sh', 'SHA256SUMS', 'build.json'})
            self.assertEqual(content, b'Fixture release')
            (self.root / 'harness.py').write_text('# changed after the build\n')
            with mock.patch.object(release_publish, 'gh') as github, self.assertRaisesRegex(ValueError, 'clean committed source'):
                release_publish.publish(self.output, self.commit, 'v' + self.version, notes, 'sholee-pt/Harness-Codex')
            github.assert_not_called()

    def test_clean_build_binds_payload_checksums_metadata_and_commit(self):
        report = build_release.build(self.root, self.output, platform='both')
        artifact = Path(report["artifact"])
        self.assertEqual(report["version"], self.version)
        self.assertEqual(report["commit"], self.commit)
        self.assertFalse(report["developmentBuild"])
        self.assertEqual(report["sha256"], hashlib.sha256(artifact.read_bytes()).hexdigest())
        self.assertEqual((self.output / "SHA256SUMS").read_text(encoding="utf-8"),
                         f"{report['sha256']}  {artifact.name}\n{report['bootstrapSha256']}  install_harness_codex.sh\n"
                         f"{report['windowsSha256']}  harness-codex-{self.version}-windows.zip\n"
                         f"{report['windowsBootstrapSha256']}  install_harness_codex.ps1\n")
        linux_bootstrap = (self.output / "install_harness_codex.sh").read_bytes()
        self.assertIn(('VERSION=' + self.version + '\n').encode(), linux_bootstrap)
        self.assertEqual(report["bootstrapSha256"], hashlib.sha256(linux_bootstrap).hexdigest())
        files = self.contents(artifact)
        windows = Path(report['windowsArtifact'])
        self.assertEqual(report['windowsSha256'], hashlib.sha256(windows.read_bytes()).hexdigest())
        with zipfile.ZipFile(windows) as archive:
            windows_files = {}
            for entry in archive.infolist():
                self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(entry.external_attr >> 16, 0o100644)
                windows_files[entry.filename.split('/', 1)[1]] = archive.read(entry)
        self.assertEqual(windows_files, files)
        bootstrap = self.output / 'install_harness_codex.ps1'
        self.assertIn("$version = '" + self.version + "'\n", bootstrap.read_text())
        self.assertIn('Harness for Codex ' + self.version + ' Windows installer.', bootstrap.read_text())
        self.assertEqual(report['windowsBootstrapSha256'], hashlib.sha256(bootstrap.read_bytes()).hexdigest())
        metadata = json.loads(files["_release.json"])
        self.assertEqual(metadata, {"runtime": "codex", "version": self.version, "commit": self.commit,
                                    "branch": f"v{self.version}", "sourceContract": dist.SOURCE_CONTRACT})
        expected = {}
        for name in build_source.ROOT_FILES:
            if Path(name).name not in {"install_harness_codex.sh", "install_harness_codex.ps1"}:
                expected[Path(name).name] = (self.root / name).read_bytes()
        for name in ("install_harness.sh", "install_harness_codex.sh", "install_harness_codex.ps1"):
            self.assertNotIn(name, files, "Download-only installers do not belong in runtime archives")
        for name in build_source.ROOT_DIRS:
            for path in (self.root / name).rglob("*"):
                if path.is_file():
                    expected[path.relative_to(self.root).as_posix()] = path.read_bytes()
        self.assertEqual(set(files), set(expected) | {"_release.json", "CONTENTS.sha256"})
        for name, data in expected.items():
            self.assertEqual(files[name], data, name)
        checksum_entries = dict(line.split("  ", 1)[::-1]
                                for line in files["CONTENTS.sha256"].decode("utf-8").splitlines())
        self.assertEqual(set(checksum_entries), set(files) - {"CONTENTS.sha256"})
        for name, digest in checksum_entries.items():
            self.assertEqual(digest, hashlib.sha256(files[name]).hexdigest(), name)
        self.assertEqual(report["files"], len(files))

    def test_ambiguous_downloader_versions_fail_before_output_creation(self):
        for name, declaration in [('install_harness_codex.sh', 'VERSION=0.1.0-beta'),
                                  ('install_harness_codex.ps1', "$version = '0.1.0-beta'")]:
            with self.subTest(name=name):
                path = self.root / 'installer' / name
                original = path.read_bytes()
                path.write_bytes(original + ('\n' + declaration + '\n').encode())
                try:
                    with self.assertRaisesRegex(ValueError, 'exactly one version declaration'):
                        build_release.build(self.root, self.output, allow_dirty=True)
                    self.assertFalse(self.output.exists())
                finally:
                    path.write_bytes(original)

    def test_archive_bytes_are_deterministic_across_output_directories(self):
        first = build_release.build(self.root, self.output, platform='both')
        second = build_release.build(self.root, self.base / "another output", platform='both')
        self.assertEqual(Path(first["artifact"]).read_bytes(), Path(second["artifact"]).read_bytes())
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(Path(first['windowsArtifact']).read_bytes(), Path(second['windowsArtifact']).read_bytes())
        self.assertEqual(Path(first["artifact"]).read_bytes()[4:8], b"\0\0\0\0")

    def test_default_linux_release_contains_only_declared_assets_and_checksums(self):
        report = build_release.build(self.root, self.output)
        self.assertEqual(report['platforms'], ['linux'])
        self.assertNotIn('windowsArtifact', report)
        expected = {f'harness-codex-{self.version}-linux.tar.gz', 'install_harness_codex.sh'}
        self.assertEqual({p.name for p in self.output.iterdir()}, expected | {'SHA256SUMS', 'build.json'})
        sums = dict(line.split('  ', 1)[::-1] for line in (self.output / 'SHA256SUMS').read_text().splitlines())
        self.assertEqual(set(sums), expected)
        for name, digest in sums.items():
            self.assertEqual(digest, hashlib.sha256((self.output / name).read_bytes()).hexdigest())
        repeated = build_release.build(self.root, self.base / 'linux repeated')
        self.assertEqual(Path(report['artifact']).read_bytes(), Path(repeated['artifact']).read_bytes())
        with self.assertRaisesRegex(ValueError, 'platform'):
            build_release.build(self.root, self.base / 'invalid', platform='unknown')
        self.assertFalse((self.base / 'invalid').exists())

    def test_dirty_source_is_refused_before_creating_output(self):
        (self.root / "README.md").write_bytes(b"local unpublished modification\n")
        with self.assertRaises(ValueError):
            build_release.build(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_allow_dirty_marks_development_payload_without_commit_claim(self):
        (self.root / "README.md").write_bytes(b"local unpublished modification\n")
        report = build_release.build(self.root, self.output, allow_dirty=True)
        self.assertIsNone(report["commit"])
        self.assertTrue(report["developmentBuild"])
        files = self.contents(report["artifact"])
        self.assertIsNone(json.loads(files["_release.json"])["commit"])
        self.assertEqual(files["README.md"], b"local unpublished modification\n")

    def test_assume_unchanged_cannot_falsely_bind_modified_bytes_to_commit(self):
        self.git("update-index", "--assume-unchanged", "README.md")
        (self.root / "README.md").write_bytes(b"hidden working-tree change\n")
        self.assertEqual(self.git("status", "--porcelain=v1").stdout.strip(), "")
        with self.assertRaises(ValueError):
            build_release.build(self.root, self.output)
        self.assertFalse(self.output.exists())
        report = build_release.build(self.root, self.output, allow_dirty=True)
        self.assertIsNone(report["commit"])
        self.assertTrue(report["developmentBuild"])
        files = self.contents(report["artifact"])
        self.assertEqual(files["README.md"], b"hidden working-tree change\n")
        self.assertIsNone(json.loads(files["_release.json"])["commit"])

    def test_assume_unchanged_cannot_falsely_bind_missing_runtime_file_to_commit(self):
        name = ".agents/skills/harness/scripts/harness_doctor.py"
        self.git("update-index", "--assume-unchanged", name)
        (self.root / name).unlink()
        self.assertEqual(self.git("status", "--porcelain=v1").stdout.strip(), "")
        with self.assertRaises(ValueError):
            build_release.build(self.root, self.output)
        self.assertFalse(self.output.exists())
        with self.assertRaisesRegex(ValueError, "harness_doctor"):
            build_release.build(self.root, self.output, allow_dirty=True)
        self.assertFalse(self.output.exists())

    def test_existing_output_content_is_preserved(self):
        self.output.mkdir()
        sentinel = self.output / "build.json"
        sentinel.write_bytes(b"existing unrelated report\r\n")
        previous = sentinel.stat().st_mtime_ns
        with self.assertRaises(ValueError):
            build_release.build(self.root, self.output)
        self.assertEqual(sentinel.read_bytes(), b"existing unrelated report\r\n")
        self.assertEqual(sentinel.stat().st_mtime_ns, previous)
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_output_inside_source_is_refused_even_for_development_build(self):
        output = self.root / "new-output"
        with self.assertRaises(ValueError):
            build_release.build(self.root, output, allow_dirty=True)
        self.assertFalse(output.exists())

    def test_source_root_alias_preserves_committed_payload_and_output_boundary(self):
        alias = self.base / "source alias"
        self.create_link(self.root, alias, directory=True)
        with self.assertRaises(ValueError):
            build_release.build(alias, alias / "nested output")
        self.assertFalse((self.root / "nested output").exists())
        actual = build_release.build(alias, self.output)
        expected = build_release.build(self.root, self.base / "physical output")
        self.assertEqual(actual["commit"], self.commit)
        self.assertFalse(actual["developmentBuild"])
        self.assertEqual(Path(actual["artifact"]).read_bytes(), Path(expected["artifact"]).read_bytes())

    def test_symlink_inside_payload_is_refused_even_for_development_build(self):
        target = self.base / "external.py"
        target.write_bytes(b"external data\n")
        self.create_link(target, self.root / "harness_cli/linked.py")
        with self.assertRaises(ValueError):
            build_release.build(self.root, self.output, allow_dirty=True)
        self.assertFalse(self.output.exists())
        self.assertEqual(target.read_bytes(), b"external data\n")

    def test_output_alias_is_refused_and_target_is_untouched(self):
        target = self.base / "external output"
        target.mkdir()
        self.create_link(target, self.output, directory=True)
        with self.assertRaises(ValueError):
            build_release.build(self.root, self.output)
        self.assertEqual(list(target.iterdir()), [])

    def test_output_parent_alias_builds_at_physical_location_without_changing_other_files(self):
        target = self.base / "external parent"
        target.mkdir()
        sentinel = target / "user.txt"
        sentinel.write_bytes(b"unrelated user data\n")
        before = sentinel.read_bytes(), sentinel.stat().st_mtime_ns
        alias = self.base / "output parent alias"
        self.create_link(target, alias, directory=True)
        report = build_release.build(self.root, alias / "nested output")
        artifact = Path(report["artifact"])
        self.assertEqual(artifact.parent, (target / "nested output").resolve())
        self.assertEqual(report["commit"], self.commit)
        self.assertEqual(report["sha256"], hashlib.sha256(artifact.read_bytes()).hexdigest())
        self.assertEqual((sentinel.read_bytes(), sentinel.stat().st_mtime_ns), before)
        self.assertEqual(set(target.iterdir()), {sentinel, target / "nested output"})
        contents = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in artifact.parent.iterdir()}
        with self.assertRaises(ValueError):
            build_release.build(self.root, alias / "nested output")
        self.assertEqual({path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in artifact.parent.iterdir()}, contents)


if __name__ == "__main__":
    unittest.main()
