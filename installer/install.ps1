# Install an unpacked Codex release using Windows PowerShell 5.1 or PowerShell 7.
[CmdletBinding()]
param(
    [string]$SourceRoot = $PSScriptRoot,
    [string]$CondaExe,
    [string]$CondaHome,
    [string]$DataDir,
    [string]$BinDir,
    [ValidateSet('compatible', 'check', 'off')][string]$AutoUpdate = 'compatible',
    [switch]$NoModifyPath,
    [switch]$Help
)
$ErrorActionPreference = 'Stop'
if ($Help) {
    Write-Output 'Install Harness for Codex on Windows x64. Options: -CondaExe PATH, -CondaHome PATH (isolated Miniforge), -DataDir PATH, -BinDir PATH, -AutoUpdate compatible|check|off, -NoModifyPath.'
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
foreach ($directory in @($BinDir, $DataDir)) {
    if ($directory -match '[%!";\r\n]') { throw 'Installation paths contain unsupported characters.' }
}

# Do not activate Conda or change the caller's project Python environment.
$condaCommand = $null
if ($CondaExe) {
    if (-not (Test-Path -LiteralPath $CondaExe -PathType Leaf)) { throw '-CondaExe does not name an existing executable.' }
    $condaCommand = [IO.Path]::GetFullPath($CondaExe)
} elseif (-not $CondaHome) {
    $found = Get-Command conda.exe -ErrorAction SilentlyContinue
    $candidates = @($env:CONDA_EXE)
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
    if (-not $CondaHome) { $CondaHome = Join-Path $env:LOCALAPPDATA 'HarnessCodexConda' }
    $CondaHome = [IO.Path]::GetFullPath($CondaHome)
    if ($CondaHome -match '[%!"\r\n]') { throw 'Miniforge installation path contains unsupported characters.' }
    $condaCommand = Join-Path $CondaHome 'Scripts\conda.exe'
    if (-not (Test-Path -LiteralPath $condaCommand -PathType Leaf)) {
        if (Test-Path -LiteralPath $CondaHome) { throw "Existing incomplete or unrelated directory preserved: $CondaHome" }
        $download = Join-Path ([IO.Path]::GetTempPath()) ('harness-miniforge-' + [guid]::NewGuid().ToString('N') + '.exe')
        try {
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
            $process = Start-Process -FilePath $download -ArgumentList "/S /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /D=$CondaHome" -WindowStyle Hidden -PassThru
            if (-not $process.WaitForExit(600000)) {
                & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F | Out-Null
                throw 'Miniforge installation exceeded 600 seconds. Its partial directory is preserved for review.'
            }
            if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $condaCommand -PathType Leaf)) {
                throw 'Miniforge installation failed; any partial directory is preserved for review.'
            }
        } finally {
            if (Test-Path -LiteralPath $download) { Remove-Item -LiteralPath $download -Force }
        }
    }
}

function Invoke-HarnessConda {
    $originalEnvs = $env:CONDA_ENVS_PATH
    try {
        if ($CondaHome) { $env:CONDA_ENVS_PATH = Join-Path $CondaHome 'envs' }
        & $condaCommand @args
        $script:condaExit = $LASTEXITCODE
    } finally { $env:CONDA_ENVS_PATH = $originalEnvs }
}
$environmentJson = Invoke-HarnessConda info --json
if ($condaExit -ne 0) { throw 'Unable to inspect Conda environments.' }
$environmentInfo = $environmentJson -join "`n" | ConvertFrom-Json
# Registered environments from other Conda installations need not be resolvable by name.
$existing = @($environmentInfo.envs_dirs | ForEach-Object { Join-Path $_ 'harness' } |
    Where-Object { Test-Path -LiteralPath (Join-Path $_ 'conda-meta\history') -PathType Leaf })
if ($CondaHome) {
    $expectedEnvironment = Join-Path $CondaHome 'envs\harness'
    $existing = @($existing | Where-Object { [IO.Path]::GetFullPath($_) -ieq $expectedEnvironment })
}
if ($existing.Count -eq 0) {
    Invoke-HarnessConda create --name harness --override-channels --channel conda-forge python=3.11 git --yes
    if ($condaExit -ne 0) { throw 'Unable to create the harness Conda environment.' }
} else {
    # A dedicated Git makes updates work even when the calling shell has no Git.
    Invoke-HarnessConda run --no-capture-output -n harness git --version
    if ($condaExit -ne 0) {
        Invoke-HarnessConda install --name harness --override-channels --channel conda-forge git --yes
        if ($condaExit -ne 0) { throw 'Unable to prepare Git in the harness environment.' }
    }
}
$installArguments = @('run', '--no-capture-output', '-n', 'harness', 'python', '-B', (Join-Path $SourceRoot 'harness.py'), 'install', '--data-dir', $DataDir, '--bin-dir', $BinDir, '--auto-update', $AutoUpdate)
if ($NoModifyPath) { $installArguments += '--no-modify-path' }
Invoke-HarnessConda @installArguments
if ($condaExit -ne 0) { throw 'Harness installation failed.' }
if (-not $NoModifyPath) {
    if (-not @($env:Path -split ';' | Where-Object { $_.TrimEnd('\') -ieq $BinDir.TrimEnd('\') }).Count) {
        $env:Path = "$BinDir;$env:Path"
    }
    Write-Output 'Ready in this PowerShell session: harness-codex --version'
}
