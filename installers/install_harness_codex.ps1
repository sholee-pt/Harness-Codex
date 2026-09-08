# Public release bootstrap. No Git, Conda, Python, administrator, or profile script required.
[CmdletBinding()]
param(
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
    Write-Output 'Harness for Codex 9.8 Windows installer. Options: -CondaExe PATH, -CondaHome PATH, -DataDir PATH, -BinDir PATH, -AutoUpdate compatible|check|off, -NoModifyPath.'
    return
}
if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitProcess -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') {
    throw 'This installer requires Windows x64 and a 64-bit PowerShell process.'
}
$version = '9.8'
$name = "harness-codex-$version-windows.zip"
$release = "https://github.com/sholee-pt/Harness/releases/download/codex-v$version"
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('harness-codex-install-' + [guid]::NewGuid().ToString('N'))
$temporary = [IO.Path]::GetFullPath($temporary)
[void][IO.Directory]::CreateDirectory($temporary)
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    try {
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 300 -Uri "$release/$name" -OutFile (Join-Path $temporary $name)
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 300 -Uri "$release/SHA256SUMS" -OutFile (Join-Path $temporary 'SHA256SUMS')
    } catch {
        throw 'Unable to download the public Harness release. Check network access, tag/assets, and repository visibility; private GitHub resources return 404 without authentication.'
    }
    $lines = @(Get-Content -LiteralPath (Join-Path $temporary 'SHA256SUMS') | Where-Object { $_ -cmatch ('^[0-9a-f]{64}  ' + [regex]::Escape($name) + '$') })
    if ($lines.Count -ne 1) { throw 'Missing or duplicate release checksum.' }
    $archivePath = Join-Path $temporary $name
    $hasher = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($archivePath)
    try { $digest = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $hasher.Dispose() }
    if ($digest -cne $lines[0].Substring(0, 64)) {
        throw 'Harness SHA-256 verification failed.'
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($archivePath)
    try {
        $prefix = "harness-codex-$version/"
        $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        [long]$total = 0
        if ($archive.Entries.Count -eq 0 -or $archive.Entries.Count -gt 10000) { throw 'Invalid ZIP entry count.' }
        foreach ($entry in $archive.Entries) {
            $entryName = $entry.FullName
            $total += $entry.Length
            $mode = ($entry.ExternalAttributes -shr 16) -band 0xF000
            if (-not $entryName.StartsWith($prefix, [StringComparison]::Ordinal) -or
                $entryName -match '(^|/)\.{1,2}(/|$)|[\\:\x00-\x1f]|//|/$' -or
                @($entryName.Split('/') | Where-Object { $_ -match '[. ]$|^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)' }).Count -or
                -not $seen.Add($entryName) -or ($mode -ne 0 -and $mode -ne 0x8000) -or
                ($entry.ExternalAttributes -band 0x410) -ne 0 -or $entry.Length -gt 16777216 -or $total -gt 100663296) {
                throw 'Unsafe or unsupported Windows ZIP entry.'
            }
        }
        if (-not $seen.Contains($prefix + 'install.ps1') -or -not $seen.Contains($prefix + 'harness.py')) {
            throw 'Incomplete Harness Windows archive.'
        }
    } finally { $archive.Dispose() }
    [IO.Compression.ZipFile]::ExtractToDirectory($archivePath, $temporary)
    $source = Join-Path $temporary "harness-codex-$version"
    $options = @{ SourceRoot = $source; AutoUpdate = $AutoUpdate; NoModifyPath = $NoModifyPath }
    foreach ($key in @('CondaExe', 'CondaHome', 'DataDir', 'BinDir')) {
        if ($PSBoundParameters.ContainsKey($key)) { $options[$key] = $PSBoundParameters[$key] }
    }
    # Execute verified source bytes without changing persistent execution policy.
    & ([scriptblock]::Create([IO.File]::ReadAllText((Join-Path $source 'install.ps1')))) @options
} finally {
    $tempParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if ($temporary.StartsWith($tempParent, [StringComparison]::OrdinalIgnoreCase) -and
        [IO.Path]::GetFileName($temporary) -match '^harness-codex-install-[0-9a-f]{32}$' -and
        (Test-Path -LiteralPath $temporary)) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
