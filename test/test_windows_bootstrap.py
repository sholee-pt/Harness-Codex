"""Run the real PowerShell bootstrap with controlled release transport."""
import hashlib
import json
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
        self.archive = self.base / 'harness-codex-0.12.0-beta-windows.zip'
        self.sums = self.base / 'SHA256SUMS'

    def build(self, extra=()):
        self.marker.unlink(missing_ok=True)
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('harness-codex-0.12.0-beta/harness.py', '# fixture')
            archive.writestr('harness-codex-0.12.0-beta/install.ps1',
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
    if ($Uri -notlike 'https://github.com/sholee-pt/Harness-Codex/releases/download/v0.12.0-beta/*') { throw 'Unexpected network request' }
    Copy-Item -LiteralPath (Join-Path $env:TEST_ASSETS ([Uri]$Uri).Segments[-1]) -Destination $OutFile
}
try {
    & ([scriptblock]::Create([IO.File]::ReadAllText($env:TEST_BOOTSTRAP))) ARGUMENTS
} catch { Write-Output $_.Exception.Message; exit 1 }
'''.replace('ARGUMENTS', arguments)
        env = os.environ.copy()
        env.update(TEST_ASSETS=str(self.base), TEST_MARKER=str(self.marker),
                   TEST_BOOTSTRAP=str(ROOT / 'installer/install_harness_codex.ps1'), TEMP=str(self.base), TMP=str(self.base))
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
        for name in ('harness-codex-0.12.0-beta/../outside', 'harness-codex-0.12.0-beta/INSTALL.PS1',
                     'harness-codex-0.12.0-beta/CON.txt', 'harness-codex-0.12.0-beta/trailing. ',
                     'harness-codex-0.12.0-beta/name:stream', 'harness-codex-0.12.0-beta/a\\b', '/absolute'):
            with self.subTest(name=name):
                self.build([(name, b'unsafe')])
                result = self.run_bootstrap()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('Unsafe or unsupported', result.stdout)
                self.assertFalse(self.marker.exists())

    def test_symlink_entry_is_refused(self):
        info = zipfile.ZipInfo('harness-codex-0.12.0-beta/link')
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
        self.assertIn('0.12.0-beta Windows installer', result.stdout)
        self.assertFalse(self.marker.exists())


@unittest.skipUnless(POWERSHELL, 'Requires native Windows PowerShell')
class WindowsSourceInstallerTests(unittest.TestCase):
    def test_explicit_conda_home_never_selects_an_external_same_named_environment(self):
        for state in ('new', 'existing', 'incomplete'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                base = Path(directory).resolve()
                home = base / 'isolated'
                executable = home / 'Scripts/conda.exe'
                executable.parent.mkdir(parents=True)
                executable.touch()  # PowerShell alias supplies the controlled Conda transport.
                selected = home / 'envs/harness'
                external = base / 'other/envs/harness/conda-meta/history'
                external.parent.mkdir(parents=True)
                external.write_text('existing user environment')
                if state == 'existing':
                    history = selected / 'conda-meta/history'
                    history.parent.mkdir(parents=True)
                    history.write_text('isolated environment')
                    (selected / 'python.exe').touch()
                elif state == 'incomplete':
                    selected.mkdir(parents=True)
                    (selected / 'keep.txt').write_text('unrelated')
                # An explicit prefix remains usable outside Conda's named search directories.
                (base / 'info.json').write_text(json.dumps({'envs_dirs': [str(base / 'other/envs')]}))
                code = r'''
$ErrorActionPreference = 'Stop'
function Invoke-FixtureConda {
    [IO.File]::AppendAllText((Join-Path $env:TEST_BASE 'calls.jsonl'), (ConvertTo-Json -Compress -InputObject @($args)) + "`n")
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'info') { Get-Content -LiteralPath (Join-Path $env:TEST_BASE 'info.json'); return }
    if ($args[0] -eq 'create') {
        $prefix = $args[[array]::IndexOf($args, '--prefix') + 1]
        [IO.Directory]::CreateDirectory((Join-Path $prefix 'conda-meta')) | Out-Null
        [IO.File]::WriteAllText((Join-Path $prefix 'conda-meta/history'), 'fixture')
        [IO.File]::WriteAllText((Join-Path $prefix 'python.exe'), '')
    }
    if ($args -contains 'git' -and $args[0] -eq 'run') { $global:LASTEXITCODE = 1 }
}
Set-Alias -Name (Join-Path $env:TEST_BASE 'isolated\Scripts\conda.exe') -Value Invoke-FixtureConda
$original = $env:CONDA_ENVS_PATH
try {
    & ([scriptblock]::Create([IO.File]::ReadAllText($env:TEST_SOURCE))) -SourceRoot (Split-Path -Parent $env:TEST_SOURCE) -CondaHome (Join-Path $env:TEST_BASE 'isolated') -DataDir (Join-Path $env:TEST_BASE 'data') -BinDir (Join-Path $env:TEST_BASE 'bin') -NoModifyPath
} catch { Write-Output $_.Exception.Message; exit 1 }
if ($env:CONDA_ENVS_PATH -cne $original) { exit 88 }
'''
                result = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', code],
                                        env={**os.environ, 'TEST_BASE': str(base), 'TEST_SOURCE': str(ROOT / 'installer/install.ps1'),
                                             'TEMP': str(base), 'TMP': str(base)}, capture_output=True, text=True, timeout=30)
                calls_path = base / 'calls.jsonl'
                self.assertTrue(calls_path.is_file(), result.stdout + result.stderr)
                calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
                self.assertEqual(external.read_text(), 'existing user environment')
                if state == 'incomplete':
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn('environment preserved', result.stdout)
                    self.assertEqual([call[0] for call in calls], ['info'])
                    self.assertEqual((selected / 'keep.txt').read_text(), 'unrelated')
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    operations = [call[0] for call in calls[1:]]
                    self.assertEqual(operations, ['create', 'run'] if state == 'new' else ['run', 'install', 'run'])
                    for call in calls[1:]:
                        self.assertNotIn('--name', call)
                        self.assertNotIn('-n', call)
                        self.assertEqual(Path(call[call.index('--prefix') + 1]), selected)

    def test_stage_logs_handle_native_warnings_and_real_exit_failures(self):
        for failure, existing in (("", False), ("", True), ("info", False), ("create", False), ("run", False)):
            with self.subTest(failure=failure, existing=existing), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                (base / "info.json").write_text(json.dumps({"envs_dirs": [str(base / "envs")]}))
                if existing:
                    history = base / "envs/harness/conda-meta/history"
                    history.parent.mkdir(parents=True)
                    history.write_text("fixture")
                    (base / 'envs/harness/python.exe').touch()
                    (base / 'data').mkdir()
                    (base / 'data/active.json').write_text('{}')  # Existing legacy CLI, controlled Conda transport.
                (base / "conda.cmd").write_text('''@echo off
if "%~1"=="%TEST_FAIL%" (
  echo dependency failure detail 1>&2
  exit /b 23
)
echo advisory warning, not an error 1>&2
if "%~1"=="info" (
  type "%TEST_BASE%\\info.json"
  exit /b 0
)
if "%~1"=="create" (
  mkdir "%~3\\conda-meta"
  type nul > "%~3\\conda-meta\\history"
  type nul > "%~3\\python.exe"
  echo Channels: conda-forge
  echo Downloading and Extracting Packages
  exit /b 0
)
echo {"treeHash":"internal-receipt","branch":null}
echo {"state":"unchanged","writes":0}
echo Installed harness-codex in fixture-bin. PATH registration skipped; invoke the command by its full path.
exit /b 0
''')
                env = {**os.environ, "TEST_BASE": str(base), "TEST_SOURCE": str(ROOT / "installer/install.ps1"),
                       "TEST_FAIL": failure, "TEMP": str(base), "TMP": str(base)}
                code = r'''
$before = @($env:Path, $env:CONDA_PREFIX, $env:CONDA_DEFAULT_ENV, $env:CONDA_ENVS_PATH) -join '|'
$result = 0
try {
    & ([scriptblock]::Create([IO.File]::ReadAllText($env:TEST_SOURCE))) -SourceRoot (Split-Path -Parent $env:TEST_SOURCE) -CondaExe (Join-Path $env:TEST_BASE 'conda.cmd') -DataDir (Join-Path $env:TEST_BASE 'data') -BinDir (Join-Path $env:TEST_BASE 'bin') -NoModifyPath
} catch { Write-Output $_.Exception.Message; $result = 1 }
if ($before -cne (@($env:Path, $env:CONDA_PREFIX, $env:CONDA_DEFAULT_ENV, $env:CONDA_ENVS_PATH) -join '|')) { exit 88 }
exit $result
'''
                result = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', code],
                                        env=env, capture_output=True, text=True, timeout=30)
                logs = list(base.glob('harness-codex-install-log-*.txt'))
                self.assertEqual(len(logs), 1, result.stdout + result.stderr)
                log = logs[0].read_text(encoding='utf-8-sig')
                self.assertIn(logs[0].name, result.stdout)
                if failure:
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertNotIn('Installation complete', result.stdout)
                    self.assertIn('exit 23', result.stdout)
                    self.assertIn('dependency failure detail', result.stdout)
                    self.assertIn('dependency failure detail', log)
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertRegex(result.stdout, r'\[3/3\].*: done \(\d+s\)')
                    self.assertIn('Installed harness-codex in fixture-bin', result.stdout)
                    self.assertIn('PATH registration skipped', result.stdout)
                    for detail in ('"treeHash"', '"writes":0', 'advisory warning'):
                        self.assertNotIn(detail, result.stdout + result.stderr)
                        self.assertIn(detail, log)
                    self.assertNotIn('Downloading and Extracting', result.stdout)
                    self.assertEqual('Reusing the existing' in result.stdout, existing)


if __name__ == '__main__':
    unittest.main()

@unittest.skipUnless(POWERSHELL, 'Requires native Windows PowerShell')
class WindowsProgressClockTests(unittest.TestCase):
    def test_native_clock_ticks_and_pauses_for_questions(self):
        import re
        native_environment = os.environ.copy()
        # A PowerShell 7 parent can export incompatible module search paths to
        # Windows PowerShell 5.1. Let this fixture host find its own modules.
        native_environment.pop('PSModulePath', None)
        native_environment.pop('PSMODULEPATH', None)
        policy = subprocess.check_output([POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', 'Get-ExecutionPolicy'],
                                         text=True, env=native_environment, timeout=30).strip()
        if policy in {'Restricted', 'AllSigned'}:
            if os.environ.get('GITHUB_ACTIONS') == 'true':
                self.fail('Windows CI must permit its local unsigned clock fixture under its existing policy: ' + policy)
            self.skipTest('Existing PowerShell policy prevents unsigned fixture execution: ' + policy)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = (ROOT / 'installer/install.ps1').read_text(encoding='utf-8')
            csharp = re.search(r"Add-Type -TypeDefinition @'\n(.*?)\n'@", source, re.S).group(1)
            (base / 'Clock.cs').write_text(csharp, encoding='utf-8')
            pause = base / 'harness-codex-progress-clock'
            pause.write_bytes(b'Harness installation progress\nrunning\n')
            runner = base / 'check.ps1'
            runner.write_text("""
$ErrorActionPreference = 'Stop'
Add-Type -Path (Join-Path $PSScriptRoot 'Clock.cs')
$pause = Join-Path $PSScriptRoot 'harness-codex-progress-clock'
try {
 [HarnessInstallClock]::Start('Clock', $pause)
 Start-Sleep -Milliseconds 1400
 [IO.File]::WriteAllText($pause, "Harness installation progress`npaused`n")
 Start-Sleep -Milliseconds 300
 [Console]::Write('PAUSE-BEGIN')
 Start-Sleep -Milliseconds 500
 [Console]::Write('PAUSE-END')
} finally {
 [HarnessInstallClock]::Stop()
}
""", encoding='utf-8')
            result = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-File', str(runner)],
                                    capture_output=True, text=True, timeout=30, env=native_environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Clock  1s', result.stdout)
            self.assertIn('PAUSE-BEGINPAUSE-END', result.stdout)
