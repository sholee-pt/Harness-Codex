"""Exercise real Bash PATH behavior and preserve user startup content."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from harness_cli.shell import register_path, START


@unittest.skipUnless(os.name == 'posix', 'Bash PATH registration is POSIX-only')
class ShellPathTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.bin = self.home / "a bin's $literal"
        self.profile = self.home / '.bashrc'

    def run_bash(self):
        command = f'. {shlex.quote(str(self.profile))}; . {shlex.quote(str(self.profile))}; printf "%s" "$PATH"'
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', command],
                              env={'HOME': str(self.home), 'PATH': '/usr/bin:/bin'},
                              capture_output=True, text=True, check=True).stdout

    def test_registration_preserves_content_mode_and_repeat_mtime(self):
        self.profile.write_text('# user content without a final newline')
        self.profile.chmod(0o640)
        self.assertEqual(register_path(self.bin, home=self.home)['writes'], 1)
        before = self.profile.read_bytes(), self.profile.stat().st_mtime_ns
        self.assertTrue(before[0].startswith(b'# user content without a final newline\n'))
        self.assertEqual(self.profile.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.run_bash().split(':').count(str(self.bin)), 1)
        self.assertEqual(register_path(self.bin, home=self.home)['writes'], 0)
        self.assertEqual((self.profile.read_bytes(), self.profile.stat().st_mtime_ns), before)

    def test_existing_home_or_literal_export_is_not_duplicated(self):
        binary = self.home / '.local/bin'
        for value in ['"$HOME/.local/bin:$PATH"', '"${HOME}/.local/bin:$PATH"',
                      shlex.quote(str(binary)) + ':"$PATH"', '"$PATH:' + str(binary) + '"']:
            with self.subTest(value=value):
                self.profile.write_text('export PATH=' + value + '\n')
                before = self.profile.read_bytes(), self.profile.stat().st_mtime_ns
                self.assertEqual(register_path(binary, home=self.home)['writes'], 0)
                self.assertEqual((self.profile.read_bytes(), self.profile.stat().st_mtime_ns), before)

    def test_dry_run_and_modified_marker_preserve_files(self):
        self.assertEqual(register_path(self.bin, home=self.home, dry_run=True)['writes'], 0)
        self.assertFalse(self.profile.exists())
        self.profile.write_text(START + '\n# user edit\n')
        before = self.profile.read_bytes()
        with self.assertRaisesRegex(ValueError, 'differs'):
            register_path(self.bin, home=self.home)
        self.assertEqual(self.profile.read_bytes(), before)

    def test_symlink_and_directory_profiles_are_preserved(self):
        target = self.home / 'actual-profile'
        target.write_text('original\n')
        self.profile.symlink_to(target)
        with self.assertRaises(ValueError):
            register_path(self.bin, home=self.home)
        self.assertEqual(target.read_text(), 'original\n')
        self.profile.unlink()
        self.profile.mkdir()
        with self.assertRaises(ValueError):
            register_path(self.bin, home=self.home)
        self.assertEqual(list(self.profile.iterdir()), [])

    def test_unsupported_path_and_invalid_encoding_fail_without_writes(self):
        with self.assertRaises(ValueError):
            register_path(self.home / 'bad:directory', home=self.home)
        self.profile.write_bytes(b'\xff')
        with self.assertRaises(UnicodeError):
            register_path(self.bin, home=self.home)
        self.assertEqual(self.profile.read_bytes(), b'\xff')
