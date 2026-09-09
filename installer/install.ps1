# Install an unpacked Codex release using Windows PowerShell 5.1 or PowerShell 7.
[CmdletBinding()]
param(
    [string]$SourceRoot = $PSScriptRoot,
    [string]$CondaExe,
    [string]$CondaHome,
    [string]$DataDir,
    [string]$BinDir,
    [ValidateSet('compatible', 'check', 'off')][string]$AutoUpdate = 'compatible',
    [ValidateSet('ask', 'reuse', 'reset')][string]$Existing = 'ask',
    [switch]$NoModifyPath,
    [switch]$Help
)
$ErrorActionPreference = 'Stop'
if ($Help) {
    Write-Output 'Install Harness for Codex on Windows x64. Options: -CondaExe PATH, -CondaHome PATH (isolated Miniforge), -DataDir PATH, -BinDir PATH, -AutoUpdate compatible|check|off, -Existing ask|reuse|reset, -NoModifyPath.'
    return
}
if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitProcess -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') {
    throw 'This installer requires Windows x64 and a 64-bit PowerShell process.'
}
if ($CondaExe -and $CondaHome) { throw 'Choose -CondaExe or -CondaHome, not both.' }
if ($SourceRoot -and -not (Test-Path -LiteralPath (Join-Path $SourceRoot 'harness.py') -PathType Leaf) -and
    (Split-Path -Leaf $SourceRoot) -eq 'installer') {
    $SourceRoot = Split-Path -Parent $SourceRoot
}
if (-not $SourceRoot -or -not (Test-Path -LiteralPath (Join-Path $SourceRoot 'harness.py') -PathType Leaf)) {
    throw 'Run install.ps1 from a complete Harness source archive.'
}
if (-not $DataDir) { $DataDir = Join-Path $env:LOCALAPPDATA 'HarnessCodex' }
if (-not $BinDir) { $BinDir = Join-Path $env:LOCALAPPDATA 'Programs\HarnessCodex\bin' }
$DataDir = [IO.Path]::GetFullPath($DataDir)
$BinDir = [IO.Path]::GetFullPath($BinDir)
function Assert-HarnessPath([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if ((Test-Path -LiteralPath $current) -and ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Installation path contains a reparse point; preserved: $current"
        }
        $current = Split-Path -Parent $current
    }
}
foreach ($directory in @($BinDir, $DataDir)) {
    if ($directory -match '[%!";\r\n]') { throw 'Installation paths contain unsupported characters.' }
    Assert-HarnessPath $directory
}

$installLog = Join-Path ([IO.Path]::GetTempPath()) ('harness-codex-install-log-' + [guid]::NewGuid().ToString('N') + '.txt')
$logStream = [IO.File]::Open($installLog, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
$logStream.Dispose()
$pauseFile = Join-Path ([IO.Path]::GetTempPath()) ('harness-codex-progress-' + [guid]::NewGuid().ToString('N'))
$previousPauseFile = $env:HARNESS_INSTALL_PAUSE_FILE
$liveProgress = $false
$script:installStep = 'Starting installer'
try {
[IO.File]::WriteAllText($pauseFile, "Harness installation progress`nrunning`n", [Text.UTF8Encoding]::new($false))
$env:HARNESS_INSTALL_PAUSE_FILE = $pauseFile
$liveProgress = -not [Console]::IsOutputRedirected
if ($liveProgress -and -not ('HarnessInstallClock' -as [type])) {
    # A native console writer keeps ticking while synchronous Conda/download
    # calls run. It never changes PowerShell execution policy or opens a window.
    Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
public static class HarnessInstallClock {
    static Thread worker;
    static volatile bool stopping;
    static int Width() {
        try { return Math.Max(40, Console.WindowWidth - 1); }
        catch { return 80; }
    }
    public static void Stop() {
        stopping = true;
        if (worker != null) { worker.Join(1000); worker = null; }
        try { Console.Write("\r" + new string(' ', Width()) + "\r"); Console.Out.Flush(); } catch {}
    }
    public static void Start(string label, string pause) {
        Stop(); stopping = false;
        worker = new Thread(() => {
            var clock = Stopwatch.StartNew(); int frame = 0;
            while (!stopping) {
                try {
                    if (!File.ReadAllText(pause).Contains("\npaused\n")) {
                        string text = "  " + "|/-\\"[(frame++) % 4] + " " + label + "  " + (int)clock.Elapsed.TotalSeconds + "s";
                        int width = Width();
                        Console.Write("\r" + (text.Length > width ? text.Substring(0, width) : text.PadRight(width)));
                        Console.Out.Flush();
                    }
                } catch {}
                Thread.Sleep(200);
            }
        });
        worker.IsBackground = true;
        worker.Start();
    }
}
'@
}
function Start-HarnessStep([string]$Label) {
    $script:installStep = $Label
    $script:stepClock = [Diagnostics.Stopwatch]::StartNew()
    Write-Host "`n$Label" -ForegroundColor Cyan
    [IO.File]::AppendAllText($installLog, "`n$Label`n")
    if ($liveProgress) { [HarnessInstallClock]::Start($Label, $pauseFile) }
}
function Complete-HarnessStep {
    if ($liveProgress) { [HarnessInstallClock]::Stop() }
    Write-Host ("  OK  {0}: done ({1}s)" -f $installStep, [int]$stepClock.Elapsed.TotalSeconds) -ForegroundColor Green
}
Write-Host "`nHarness for Codex installer`n================================`nDetailed log: $installLog"
Start-HarnessStep '[1/3] Checking installation tools'
$ownedRuntime = $null
$runtimeReference = Join-Path $DataDir 'runtime.json'
if (Test-Path -LiteralPath $runtimeReference -PathType Leaf) {
    Assert-HarnessPath $runtimeReference
    $ownedRuntime = (Get-Content -LiteralPath $runtimeReference -Raw | ConvertFrom-Json).root
    Assert-HarnessPath $ownedRuntime
}
# Do not activate Conda or change the caller's project Python environment.
$condaCommand = $null
if ($CondaExe) {
    if (-not (Test-Path -LiteralPath $CondaExe -PathType Leaf)) { throw '-CondaExe does not name an existing executable.' }
    $condaCommand = [IO.Path]::GetFullPath($CondaExe)
} elseif (-not $CondaHome) {
    $found = Get-Command conda.exe -ErrorAction SilentlyContinue
    $candidates = @($env:CONDA_EXE)
    if ($ownedRuntime) { $candidates = @((Join-Path $ownedRuntime 'Scripts\conda.exe')) + $candidates }
    if ($found) { $candidates += $found.Source }
    foreach ($name in @('miniforge3', 'miniconda3', 'anaconda3')) {
        $candidates += Join-Path $env:USERPROFILE "$name\Scripts\conda.exe"
    }
    $candidates += Join-Path $env:LOCALAPPDATA 'HarnessCodexConda\Scripts\conda.exe'
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { $condaCommand = $candidate; break }
    }
}
if (-not $condaCommand) {
    if (-not $CondaHome) { $CondaHome = "$DataDir-runtime" }
    $CondaHome = [IO.Path]::GetFullPath($CondaHome)
    Assert-HarnessPath $CondaHome
    if ($CondaHome -match '[%!"\r\n]') { throw 'Miniforge installation path contains unsupported characters.' }
    $condaCommand = Join-Path $CondaHome 'Scripts\conda.exe'
    if (-not (Test-Path -LiteralPath $condaCommand -PathType Leaf)) {
        if (Test-Path -LiteralPath $CondaHome) { throw "Existing incomplete or unrelated directory preserved: $CondaHome" }
        $download = Join-Path ([IO.Path]::GetTempPath()) ('harness-miniforge-' + [guid]::NewGuid().ToString('N') + '.exe')
        try {
            Write-Host '      Downloading and verifying the Python environment manager...'
            $ProgressPreference = 'SilentlyContinue'
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing -TimeoutSec 300 -Uri 'https://github.com/conda-forge/miniforge/releases/download/26.5.3-0/Miniforge3-26.5.3-0-Windows-x86_64.exe' -OutFile $download
            $hasher = [Security.Cryptography.SHA256]::Create()
            $stream = [IO.File]::OpenRead($download)
            try { $digest = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
            finally { $stream.Dispose(); $hasher.Dispose() }
            if ($digest -cne 'ac05d86a4dbf3094fe112e14d1547a07cb10c6ae04bca274f88f1c09a5549876') {
                throw 'Miniforge SHA-256 verification failed.'
            }
            # NSIS requires /D last, without quotes around its value (including spaces).
            Write-Host '      Installing the Python environment manager; this may take a few minutes...'
            $process = Start-Process -FilePath $download -ArgumentList "/S /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /D=$CondaHome" -WindowStyle Hidden -PassThru
            if (-not $process.WaitForExit(600000)) {
                & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F | Out-Null
                throw 'Miniforge installation exceeded 600 seconds. Its partial directory is preserved for review.'
            }
            if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $condaCommand -PathType Leaf)) {
                throw 'Miniforge installation failed; any partial directory is preserved for review.'
            }
            $ownedRuntime = $CondaHome
        } finally {
            if (Test-Path -LiteralPath $download) { Remove-Item -LiteralPath $download -Force }
        }
    }
}

function Invoke-HarnessConda {
    $originalEnvs = $env:CONDA_ENVS_PATH
    $originalErrorPreference = $ErrorActionPreference
    try {
        if ($CondaHome) { $env:CONDA_ENVS_PATH = Join-Path $CondaHome 'envs' }
        # PowerShell 5.1 wraps native stderr as ErrorRecord; warnings are not exit failures.
        $ErrorActionPreference = 'Continue'
        & $condaCommand @args 2>&1 | ForEach-Object {
            [IO.File]::AppendAllText($installLog, "$_`n")
            if ($_ -isnot [Management.Automation.ErrorRecord]) { $_ }
        }
        $script:condaExit = $LASTEXITCODE
    } finally {
        $env:CONDA_ENVS_PATH = $originalEnvs
        $ErrorActionPreference = $originalErrorPreference
    }
}
Complete-HarnessStep
Start-HarnessStep '[2/3] Preparing the isolated Harness environment'
$environmentJson = Invoke-HarnessConda info --json
if ($condaExit -ne 0) { throw "Unable to inspect Conda environments (exit $condaExit)." }
$environmentInfo = $environmentJson -join "`n" | ConvertFrom-Json
# Registered environments from other Conda installations need not be resolvable by name.
$existingEnvironments = @($environmentInfo.envs_dirs | ForEach-Object { Join-Path $_ 'harness' } |
    Where-Object { Test-Path -LiteralPath (Join-Path $_ 'conda-meta\history') -PathType Leaf })
$environmentSelector = @('--name', 'harness')
if (-not $ownedRuntime -and -not $CondaHome -and -not (Test-Path -LiteralPath (Join-Path $DataDir 'active.json'))) {
    $ownedRuntime = "$DataDir-runtime"
    if (Test-Path -LiteralPath $ownedRuntime) { throw "Existing runtime directory preserved: $ownedRuntime" }
    [void][IO.Directory]::CreateDirectory($ownedRuntime)
}
if ($ownedRuntime) {
    Assert-HarnessPath $ownedRuntime
    $ownerMarker = Join-Path $ownedRuntime '.harness-runtime-owner'
    if (-not (Test-Path -LiteralPath $ownerMarker)) {
        if (Test-Path -LiteralPath $runtimeReference) { throw 'Existing runtime ownership marker is missing' }
        [IO.File]::WriteAllText($ownerMarker, "harness-codex runtime v1`n$DataDir`n", [Text.UTF8Encoding]::new($false))
    }
}
if ($ownedRuntime -or $CondaHome) {
    $environmentHome = if ($ownedRuntime) { $ownedRuntime } else { $CondaHome }
    $expectedEnvironment = Join-Path $environmentHome 'envs\harness'
    # CONDA_ENVS_PATH adds a search directory; it does not exclude other Condas.
    # Creating by name can remove an existing same-named environment elsewhere.
    $environmentSelector = @('--prefix', $expectedEnvironment)
    $existingEnvironments = @()
    if (Test-Path -LiteralPath (Join-Path $expectedEnvironment 'conda-meta\history') -PathType Leaf) {
        $existingEnvironments = @($expectedEnvironment)
    }
    if (-not $existingEnvironments.Count -and (Test-Path -LiteralPath $expectedEnvironment)) {
        throw "Existing incomplete or unrelated environment preserved: $expectedEnvironment"
    }
}
if ($existingEnvironments.Count -eq 0) {
    Write-Host '      First setup: preparing Python and Git; this may take a few minutes...'
    Invoke-HarnessConda create @environmentSelector --override-channels --channel conda-forge python=3.11 git --yes | Out-Null
    if ($condaExit -ne 0) { throw "Unable to create the harness Conda environment (exit $condaExit)." }
} else {
    Write-Host '      Reusing the existing Harness environment.'
    # A dedicated Git makes updates work even when the calling shell has no Git.
    Invoke-HarnessConda run --no-capture-output @environmentSelector git --version | Out-Null
    if ($condaExit -ne 0) {
        Write-Host '      Preparing Git for tool updates...'
        Invoke-HarnessConda install @environmentSelector --override-channels --channel conda-forge git --yes | Out-Null
        if ($condaExit -ne 0) { throw "Unable to prepare Git in the harness environment (exit $condaExit)." }
    }
}
Complete-HarnessStep
Start-HarnessStep '[3/3] Installing command and applying PATH preferences'
$installArguments = @('run', '--no-capture-output') + $environmentSelector + @('python', '-B', (Join-Path $SourceRoot 'harness.py'), 'install', '--data-dir', $DataDir, '--bin-dir', $BinDir, '--auto-update', $AutoUpdate, '--existing', $Existing)
if ($ownedRuntime) { $installArguments += @('--owned-runtime', $ownedRuntime) }
if ($NoModifyPath) { $installArguments += '--no-modify-path' }
$installOutput = Invoke-HarnessConda @installArguments
if ($condaExit -ne 0) { throw "Harness installation failed (exit $condaExit)." }
if (-not $NoModifyPath) {
    if (-not @($env:Path -split ';' | Where-Object { $_.TrimEnd('\') -ieq $BinDir.TrimEnd('\') }).Count) {
        $env:Path = "$BinDir;$env:Path"
    }
}
Complete-HarnessStep
# Keep the CLI receipt contract intact; replay only its existing human summary.
$installOutput | Where-Object { $_ -like 'Installed *' } | ForEach-Object { Write-Host $_ }
if (-not $NoModifyPath) { Write-Host 'Ready in this PowerShell session: harness-codex --version' }
Write-Host "Installation complete. Detailed log: $installLog"
} catch {
    if ($liveProgress -and ('HarnessInstallClock' -as [type])) { [HarnessInstallClock]::Stop() }
    [IO.File]::AppendAllText($installLog, "$_`n")
    Write-Host "`n${installStep}: failed. Last log lines:"
    Select-String -LiteralPath $installLog -Pattern '^harness:' | ForEach-Object { Write-Host $_.Line }
    Get-Content -LiteralPath $installLog -Tail 15 | ForEach-Object { Write-Host $_ }
    throw "$_ Detailed log: $installLog"
} finally {
    if ($liveProgress -and ('HarnessInstallClock' -as [type])) { [HarnessInstallClock]::Stop() }
    $env:HARNESS_INSTALL_PAUSE_FILE = $previousPauseFile
    if (Test-Path -LiteralPath $pauseFile) { Remove-Item -LiteralPath $pauseFile -Force }
}
