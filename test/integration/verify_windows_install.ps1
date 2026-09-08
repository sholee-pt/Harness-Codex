# Exact built Harness assets replace private release URLs; Miniforge downloads are real.
param([Parameter(Mandatory=$true)][string]$Dist, [switch]$Cold, [string]$CondaExe)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows integration check only.' }
if ($Cold -and $env:GITHUB_ACTIONS -ne 'true') { throw 'The real registry/cold check requires a disposable GitHub Actions runner.' }
$Dist = [IO.Path]::GetFullPath($Dist)
$base = Join-Path ([IO.Path]::GetTempPath()) ('harness-windows-check-' + [guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($base)
$binary = Join-Path $base 'command bin'
$data = Join-Path $base 'tool data'
$originalPath = $env:Path
$originalLabels = @($env:CONDA_PREFIX, $env:CONDA_DEFAULT_ENV, $env:CONDA_ENVS_PATH)
$registry = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', [bool]$Cold)
$oldPath = $registry.GetValue('Path', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
$oldKind = if ($null -ne $oldPath) { $registry.GetValueKind('Path') } else { $null }
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$bootstrap = Join-Path $Dist 'install_harness_codex.ps1'
$options = @{DataDir=$data; BinDir=$binary; AutoUpdate='off'}
if ($Cold) { $options.CondaHome = Join-Path $base 'miniforge' }
else { $options.CondaExe = $CondaExe; $options.NoModifyPath = $true }
function Invoke-WebRequest {
    param($Uri, $OutFile, [switch]$UseBasicParsing, $TimeoutSec)
    if ($Uri -like 'https://github.com/sholee-pt/Harness/releases/download/codex-v*/*') {
        $asset = Join-Path $Dist ([Uri]$Uri).Segments[-1]
        if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) { throw 'Unexpected Harness asset request.' }
        Copy-Item -LiteralPath $asset -Destination $OutFile
    } else {
        Microsoft.PowerShell.Utility\Invoke-WebRequest -UseBasicParsing -TimeoutSec $TimeoutSec -Uri $Uri -OutFile $OutFile
    }
}
function Get-ToolState {
    $result = @{}
    foreach ($folder in @($data, $binary)) {
        Get-ChildItem -LiteralPath $folder -Recurse -File | ForEach-Object {
            $result[$_.FullName] = ((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash + ':' + $_.LastWriteTimeUtc.Ticks)
        }
    }
    return $result
}
try {
    & ([scriptblock]::Create([IO.File]::ReadAllText($bootstrap))) @options
    $command = Join-Path $binary 'harness-codex.cmd'
    $version = & $command --version
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^Harness for Codex 9\.8$') { throw 'Installed Windows command version failed.' }
    & $command --help
    if ($LASTEXITCODE -ne 0) { throw 'Installed Windows command help failed.' }
    if (($originalLabels -join '|') -cne (@($env:CONDA_PREFIX, $env:CONDA_DEFAULT_ENV, $env:CONDA_ENVS_PATH) -join '|')) {
        throw 'Installer modified caller Conda environment.'
    }
    $registered = $registry.GetValue('Path', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    if ($Cold) {
        if (@($registered -split ';' | Where-Object { $_ -ieq $binary }).Count -ne 1) { throw 'User PATH entry missing or duplicated.' }
        if ((Get-Command harness-codex).Source -ine $command) { throw 'Current PowerShell command discovery failed.' }
        $env:Path = "$binary;$env:SystemRoot\System32;$env:SystemRoot"
        $child = & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command 'harness-codex --version'
        if ($LASTEXITCODE -ne 0 -or $child -notmatch 'Harness for Codex 9.8') { throw 'Fresh PowerShell command failed.' }
        $python = Join-Path $options.CondaHome 'envs\harness\python.exe'
        $active = Get-Content -LiteralPath (Join-Path $data 'active.json') -Raw | ConvertFrom-Json
        $releaseRoot = Join-Path $data ('releases\' + $active.releaseId)
        # No system/Conda Git on PATH: validate the bundled Git fallback in a real child.
        $probe = "import sys; sys.path.insert(0, sys.argv[1]); from harness_cli.distribution import _git; print(_git(['--version'], timeout=15).stdout.decode())"
        & $python -B -c $probe $releaseRoot
        if ($LASTEXITCODE -ne 0) { throw 'Bundled Git fallback failed.' }
    } elseif ($registered -cne $oldPath) { throw '-NoModifyPath changed the user registry.' }
    $before = Get-ToolState
    & ([scriptblock]::Create([IO.File]::ReadAllText($bootstrap))) @options
    $after = Get-ToolState
    if ($before.Count -ne $after.Count) { throw 'Repeat installation changed file count.' }
    foreach ($key in $before.Keys) { if ($after[$key] -cne $before[$key]) { throw "Repeat installation changed bytes or mtime: $key" } }
    if ($registry.GetValue('Path', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) -cne $registered) { throw 'Repeat installation changed PATH.' }
    $project = Join-Path $base 'project'
    [void][IO.Directory]::CreateDirectory($project)
    & $command init --project $project --dry-run
    if ($LASTEXITCODE -ne 0 -or @(Get-ChildItem -LiteralPath $project -Force).Count) { throw 'Init dry-run wrote project data.' }
    if ($Cold) {
        if ($null -eq $oldPath) { $registry.DeleteValue('Path', $false) } else { $registry.SetValue('Path', $oldPath, $oldKind) }
        & $command init --project $project --install-only
        if ($LASTEXITCODE -ne 0) { throw 'Installed init failed.' }
        $restored = $registry.GetValue('Path', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        if (@($restored -split ';' | Where-Object { $_ -ieq $binary }).Count -ne 1) { throw 'Init failed to restore PATH registration.' }
    }
    if ([Environment]::GetEnvironmentVariable('Path', 'Machine') -cne $machinePath) { throw 'Machine PATH changed.' }
    $uninstallBefore = Get-ToolState
    & $command uninstall --dry-run
    if ($LASTEXITCODE -ne 0) { throw 'Installed uninstall preview failed.' }
    $previousErrorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'  # Expected native stderr on PowerShell 5.1.
        'yes' | & $command uninstall 2>&1 | Out-Host
    } finally { $ErrorActionPreference = $previousErrorPreference }
    if ($LASTEXITCODE -eq 0) { throw 'Piped yes bypassed interactive uninstall confirmation.' }
    $uninstallAfter = Get-ToolState
    if ($uninstallBefore.Count -ne $uninstallAfter.Count) { throw 'Uninstall preview/refusal changed file count.' }
    foreach ($key in $uninstallBefore.Keys) { if ($uninstallAfter[$key] -cne $uninstallBefore[$key]) { throw 'Uninstall preview/refusal changed files.' } }
    $active = Get-Content -LiteralPath (Join-Path $data 'active.json') -Raw | ConvertFrom-Json
    $projectBefore = @(Get-ChildItem -LiteralPath $project -Recurse -File | ForEach-Object { $_.FullName + ':' + (Get-FileHash -LiteralPath $_.FullName).Hash }) -join '|'
    # Adapt terminal detection only; run the actual installed Python launcher and
    # interactive input branch. CI itself has no interactive Windows console.
    $confirmationProbe = Join-Path $base 'confirm-uninstall.py'
    [IO.File]::WriteAllText($confirmationProbe, "import runpy, sys`nsys.stdin.isatty = lambda: True`nsys.stdout.isatty = lambda: True`nsys.argv = sys.argv[1:]`nrunpy.run_path(sys.argv[0], run_name='__main__')`n")
    'yes' | & $active.python -B $confirmationProbe (Join-Path $data 'launcher.py') uninstall
    if ($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath $data) -or (Test-Path -LiteralPath $command)) { throw 'Confirmed installed CLI removal failed.' }
    $projectAfter = @(Get-ChildItem -LiteralPath $project -Recurse -File | ForEach-Object { $_.FullName + ':' + (Get-FileHash -LiteralPath $_.FullName).Hash }) -join '|'
    if ($projectAfter -cne $projectBefore -or -not (Test-Path -LiteralPath $active.python)) { throw 'Uninstall changed the project or Conda interpreter.' }
    if (@($registry.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) -split ';' | Where-Object { $_ -ieq $binary }).Count) { throw 'Uninstall left the dedicated bin directory in user PATH.' }
    @{verified=$true; platform='Windows'; powershell=$PSVersionTable.PSVersion.ToString(); cold=[bool]$Cold;
      harnessTransport='exact local release assets'; miniforgeTransport=$(if ($Cold) {'real official HTTPS download'} else {'existing Conda'});
      version=$version; repeatBytesAndMtime=$true; callerEnvironmentPreserved=$true; projectDryRun=$true;
      realUserPathTest=[bool]$Cold; installedCliUninstall=$true; uninstallTerminalDetection='adapted for noninteractive CI';
      uninstallKeptProjectAndConda=$true; nativeCodexExecuted=$false; evidenceDirectory=$base} | ConvertTo-Json
} finally {
    if ($Cold) {
        if ($null -eq $oldPath) { $registry.DeleteValue('Path', $false) } else { $registry.SetValue('Path', $oldPath, $oldKind) }
    }
    $registry.Dispose()
    $env:Path = $originalPath
}
