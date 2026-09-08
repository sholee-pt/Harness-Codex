"""Run the real PowerShell bootstrap with controlled release transport."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('powershell.exe') if os.name == 'nt' else None


@unittest.skipUnless(POWERSHELL, 'Requires native Windows PowerShell')
class WindowsBootstrapTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.marker = self.base / 'executed.txt'
        self.archive = self.base / 'harness-codex-9.8-windows.zip'
        self.sums = self.base / 'SHA256SUMS'

    def build(self, extra=()):
        self.marker.unlink(missing_ok=True)
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('harness-codex-9.8/harness.py', '# fixture')
            archive.writestr('harness-codex-9.8/install.ps1',
                             "param($SourceRoot, $AutoUpdate, $NoModifyPath, $BinDir)\n"
                             "[IO.File]::WriteAllText($env:TEST_MARKER, $BinDir + '|' + $AutoUpdate + '|' + $NoModifyPath)\n")
            for name, data in extra:
                if isinstance(name, str):
                    entry = zipfile.ZipInfo()
                    # Bypass ZipInfo's Windows slash normalization to exercise raw ZIP names.
                    entry.filename = name
                    name = entry
                archive.writestr(name, data)
        self.sums.write_text(hashlib.sha256(self.archive.read_bytes()).hexdigest() + '  ' + self.archive.name + '\n')

    def run_bootstrap(self, arguments="-BinDir 'C:\\some bin' -AutoUpdate off -NoModifyPath"):
        code = r'''
$ErrorActionPreference = 'Stop'
function Invoke-WebRequest {
    param($Uri, $OutFile, [switch]$UseBasicParsing, $TimeoutSec)
    if ($Uri -notlike 'https://github.com/sholee-pt/Harness/releases/download/codex-v9.8/*') { throw 'Unexpected network request' }
    Copy-Item -LiteralPath (Join-Path $env:TEST_ASSETS ([Uri]$Uri).Segments[-1]) -Destination $OutFile
}
try {
    & ([scriptblock]::Create([IO.File]::ReadAllText($env:TEST_BOOTSTRAP))) ARGUMENTS
} catch { Write-Output $_.Exception.Message; exit 1 }
'''.replace('ARGUMENTS', arguments)
        env = os.environ.copy()
        env.update(TEST_ASSETS=str(self.base), TEST_MARKER=str(self.marker),
                   TEST_BOOTSTRAP=str(ROOT / 'install_harness_codex.ps1'), TEMP=str(self.base), TMP=str(self.base))
        result = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', code],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertFalse(list(self.base.glob('harness-codex-install-*')), result.stdout + result.stderr)
        return result

    def test_valid_archive_dispatches_options_and_cleans_temporary_files(self):
        self.build()
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.marker.read_text(), 'C:\\some bin|off|True')

    def test_invalid_checksum_never_executes_source(self):
        self.build()
        self.archive.write_bytes(self.archive.read_bytes() + b'changed')
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA-256', result.stdout)
        self.assertFalse(self.marker.exists())

    def test_duplicate_checksum_never_executes_source(self):
        self.build()
        self.sums.write_bytes(self.sums.read_bytes() * 2)
        self.assertNotEqual(self.run_bootstrap().returncode, 0)
        self.assertFalse(self.marker.exists())

    def test_unsafe_entries_are_refused_before_extraction_or_execution(self):
        for name in ('harness-codex-9.8/../outside', 'harness-codex-9.8/INSTALL.PS1',
                     'harness-codex-9.8/CON.txt', 'harness-codex-9.8/trailing. ',
                     'harness-codex-9.8/name:stream', 'harness-codex-9.8/a\\b', '/absolute'):
            with self.subTest(name=name):
                self.build([(name, b'unsafe')])
                result = self.run_bootstrap()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('Unsafe or unsupported', result.stdout)
                self.assertFalse(self.marker.exists())

    def test_symlink_entry_is_refused(self):
        info = zipfile.ZipInfo('harness-codex-9.8/link')
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        self.build([(info, b'outside')])
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsafe or unsupported', result.stdout)
        self.assertFalse(self.marker.exists())

    def test_help_is_offline_without_release_assets(self):
        result = self.run_bootstrap('-Help')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('9.8 Windows installer', result.stdout)
        self.assertFalse(self.marker.exists())


if __name__ == '__main__':
    unittest.main()
