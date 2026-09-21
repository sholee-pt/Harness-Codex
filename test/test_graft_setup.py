"""Bootstrap isolation, ownership and failure behavior without network access."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

from harness_cli import graft_setup as setup


class GraftSetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.name = 'node-v22.1.0-linux-x64'
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:xz') as archive:
            for name in ('bin/node', 'lib/node_modules/npm/bin/npm-cli.js'):
                entry = tarfile.TarInfo(self.name + '/' + name)
                entry.size, entry.mode = 4, 0o755
                archive.addfile(entry, io.BytesIO(b'fake'))
        self.archive = output.getvalue()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(setup.sys, 'platform', 'linux').start()
        mock.patch.object(setup.platform, 'machine', return_value='x86_64').start()
        self.download = mock.patch.object(setup, '_download', side_effect=self.fetch).start()
        self.original_install = setup._install
        self.install = mock.patch.object(setup, '_install', side_effect=self.package).start()

    def fetch(self, url, destination, limit):
        data = (hashlib.sha256(self.archive).hexdigest() + '  ' + self.name + '.tar.xz\n').encode() if url.endswith('.txt') else self.archive
        destination.write_bytes(data)

    def package(self, node, prefix, version, log):
        package = prefix / 'node_modules/@nanonets/graft'
        package.mkdir(parents=True)
        (package / 'package.json').write_text(json.dumps({'name': '@nanonets/graft', 'version': version}))

    def test_cold_setup_then_offline_reuse_preserves_runtime_bytes_and_timestamps(self):
        node, package = setup.prepare(self.home, '0.18.0')
        self.assertTrue(node.is_file())
        self.assertTrue(package.is_dir())
        self.assertEqual(self.download.call_count, 2)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.home.rglob('*') if p.is_file()}
        self.assertEqual(setup.prepare(self.home, '0.18.0'), (node, package))
        self.assertEqual(self.download.call_count, 2)
        self.install.assert_called_once()
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.home.rglob('*') if p.is_file()})
        (package / 'package.json').write_text('[]')
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            setup.prepare(self.home, '0.18.0')
        self.assertEqual((package / 'package.json').read_text(), '[]')
        self.assertEqual(self.download.call_count, 2)

    def test_unowned_existing_runtime_is_preserved_without_download(self):
        root = self.home / '.runtime/graft-0.18.0-linux-x64'
        root.mkdir(parents=True)
        (root / 'keep').write_bytes(b'user')
        with self.assertRaises(OSError):
            setup.prepare(self.home, '0.18.0')
        self.download.assert_not_called()
        self.assertEqual((root / 'keep').read_bytes(), b'user')

    def test_checksum_mismatch_never_installs_or_promotes_partial_runtime(self):
        def damaged(url, destination, limit):
            self.fetch(url, destination, limit)
            if not url.endswith('.txt'):
                destination.write_bytes(b'corrupt')
        self.download.side_effect = damaged
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            setup.prepare(self.home, '0.18.0')
        self.install.assert_not_called()
        self.assertFalse((self.home / '.runtime/graft-0.18.0-linux-x64').exists())
        self.assertFalse(list((self.home / '.runtime').glob('.pending-*')))

    def test_install_failure_preserves_existing_files_and_cleans_stage(self):
        (self.home / 'keep').write_bytes(b'user')
        self.install.side_effect = ValueError('registry unavailable')
        with self.assertRaisesRegex(ValueError, 'registry'):
            setup.prepare(self.home, '0.18.0')
        self.assertEqual((self.home / 'keep').read_bytes(), b'user')
        self.assertFalse((self.home / '.runtime/graft-0.18.0-linux-x64').exists())
        self.assertFalse(list((self.home / '.runtime').glob('.pending-*')))
        self.assertFalse((self.home / '.runtime/.install.lock').exists())

    def test_archive_cannot_write_outside_staging(self):
        archive = self.home / 'bad.tar.xz'
        with tarfile.open(archive, 'w:xz') as output:
            entry = tarfile.TarInfo(self.name + '/../escaped')
            entry.size = 1
            output.addfile(entry, io.BytesIO(b'x'))
        with self.assertRaises(ValueError):
            setup._extract(archive, self.home / 'output', self.name)
        self.assertFalse((self.home / 'escaped').exists())

    def test_npm_timeout_terminates_process_group(self):
        process = mock.MagicMock(pid=1234)
        process.wait.side_effect = [subprocess.TimeoutExpired('npm', 180), 0]
        with mock.patch.object(setup.subprocess, 'Popen') as start, mock.patch.object(setup.os, 'killpg', create=True) as kill, mock.patch.object(setup.signal, 'SIGKILL', 9, create=True):
            start.return_value.__enter__.return_value = process
            with self.assertRaises(subprocess.TimeoutExpired):
                self.original_install(self.home / 'runtime/node/bin/node', self.home / 'runtime/package', '0.18.0', self.home / 'log')
        kill.assert_called_once()
        self.assertEqual(kill.call_args.args[0], 1234)
        self.assertEqual(process.wait.call_count, 2)
