"""Public bootstrap entrypoint, pipe input and fail-before-install cases."""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'install_harness_codex.sh'


@unittest.skipUnless(os.name == 'posix', 'Public installer uses Linux shell tools')
class PublicBootstrapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.archive = self.root / 'payload.tar.gz'
        self.sums = self.root / 'sums'
        self.marker = self.root / 'installed'
        curl = self.bin / 'curl'
        curl.write_text('''#!/bin/sh
url=; output=
while [ "$#" -gt 0 ]; do
  case "$1" in https://*) url=$1;; -o) shift; output=$1;; esac
  shift
done
case "$url" in
  */SHA256SUMS) cp "$TEST_SUMS" "$output" ;;
  */harness-codex-9.7-linux.tar.gz) cp "$TEST_ARCHIVE" "$output" ;;
  *) exit 87 ;;
esac
''')
        curl.chmod(0o755)
        self.env = {'PATH': str(self.bin) + ':/usr/bin:/bin', 'HOME': str(self.root),
                    'TMPDIR': str(self.root), 'TEST_SUMS': str(self.sums),
                    'TEST_ARCHIVE': str(self.archive), 'TEST_MARKER': str(self.marker)}

    def make_archive(self, *, unsafe=False, linked=False):
        with tarfile.open(self.archive, 'w:gz') as archive:
            name = '../escape' if unsafe else 'harness-codex-9.7/install.sh'
            data = b'#!/bin/sh\nprintf installed > "$TEST_MARKER"\n'
            info = tarfile.TarInfo(name)
            if linked:
                info.type = tarfile.SYMTYPE
                info.linkname = '/tmp/outside'
            else:
                info.size = len(data)
            archive.addfile(info, None if linked else io.BytesIO(data))
        self.sums.write_text(hashlib.sha256(self.archive.read_bytes()).hexdigest() + '  harness-codex-9.7-linux.tar.gz\n')

    def invoke(self, *arguments):
        return subprocess.run(['/bin/sh', '-s', '--', *arguments], input=SCRIPT.read_text(),
                              env=self.env, capture_output=True, text=True, timeout=30)

    def test_piped_script_installs_and_cleans_only_its_temporary_directory(self):
        self.make_archive()
        unrelated = self.root / 'keep'
        unrelated.write_text('user')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.marker.read_text(), 'installed')
        self.assertEqual(unrelated.read_text(), 'user')
        self.assertEqual(list(self.root.glob('harness-codex-install.*')), [])

    def test_checksum_failure_never_executes_payload(self):
        self.make_archive()
        self.sums.write_text('0' * 64 + '  harness-codex-9.7-linux.tar.gz\n')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertFalse(self.marker.exists())

    def test_traversal_and_links_are_rejected_before_extraction(self):
        for options in [{'unsafe': True}, {'linked': True}]:
            with self.subTest(options=options):
                self.make_archive(**options)
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertFalse(self.marker.exists())
                self.assertFalse((self.root / 'escape').exists())

    def test_help_and_invalid_options_need_no_download(self):
        before = list(self.root.iterdir())
        self.assertEqual(self.invoke('--help').returncode, 0)
        for options in [('--agent', 'claude'), ('--bin-dir',), ('--unknown',), ('--branch', 'codex/v9.6')]:
            self.assertNotEqual(self.invoke(*options).returncode, 0)
        self.assertEqual(list(self.root.iterdir()), before)

