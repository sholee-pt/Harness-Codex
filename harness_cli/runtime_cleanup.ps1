# Remove only the immutable runtime receipt's unchanged files after Python exits.
param([Parameter(Mandatory=$true)][string]$PlanSha256,
      [string]$JobDirectory = $PSScriptRoot,
      [string]$ScriptPath = $PSCommandPath)
$ErrorActionPreference = 'Stop'
# A caller running PowerShell 7 can pass its incompatible PSModulePath to 5.1.
# Load only the native Windows modules needed by this cleanup helper.
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1')
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Management\Microsoft.PowerShell.Management.psd1')
$job = $JobDirectory
if ((Get-FileHash -LiteralPath (Join-Path $job 'plan.json') -Algorithm SHA256).Hash.ToLowerInvariant() -cne $PlanSha256) { throw 'Cleanup plan changed' }
$plan = Get-Content -LiteralPath (Join-Path $job 'plan.json') -Raw | ConvertFrom-Json
function Checked-Path([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            if ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse point preserved' }
        }
        $current = Split-Path -Parent $current
    }
    return [IO.Path]::GetFullPath($Path)
}
try {
    $parent = Get-Process -Id $plan.waitPid -ErrorAction SilentlyContinue
    if ($parent -and -not $parent.WaitForExit(600000)) { throw 'Runtime is still running' }
    $root = Checked-Path $plan.root
    $receipt = Join-Path $root '.harness-runtime-files.json'
    if ((Get-FileHash -LiteralPath $receipt -Algorithm SHA256).Hash.ToLowerInvariant() -cne $plan.receiptSha256) { throw 'Runtime receipt changed' }
    $owner = Join-Path $root '.harness-runtime-owner'
    [void](Checked-Path $owner)
    if ((Get-FileHash -LiteralPath $owner -Algorithm SHA256).Hash.ToLowerInvariant() -cne $plan.files.'.harness-runtime-owner'.sha256) { throw 'Runtime owner marker changed' }
    $remaining = [Collections.Generic.List[string]]::new()
    foreach ($file in $plan.files.PSObject.Properties) {
        if ($file.Name -eq '.harness-runtime-owner') { continue }
        $path = [IO.Path]::GetFullPath((Join-Path $root $file.Name))
        try {
            if (-not $path.StartsWith($root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Path outside runtime' }
            [void](Checked-Path $path)
            if (-not (Test-Path -LiteralPath $path)) { continue }
            $info = Get-Item -LiteralPath $path -Force
            if ($null -eq $file.Value.sha256 -or $info.PSIsContainer -or $info.Length -ne $file.Value.size -or
                (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $file.Value.sha256) { throw 'Changed file preserved' }
            Remove-Item -LiteralPath $path -Force
        } catch { $remaining.Add($path) }
    }
    foreach ($name in @($plan.directories | Where-Object { $_ -ne '.' } | Sort-Object { $_.Split('/').Count } -Descending)) {
        try {
            $path = [IO.Path]::GetFullPath((Join-Path $root $name))
            if (-not $path.StartsWith($root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Path outside runtime' }
            [void](Checked-Path $path)
            if (Test-Path -LiteralPath $path) { [IO.Directory]::Delete($path, $false) }
        } catch { $remaining.Add($path) }
    }
    $names = @(Get-ChildItem -LiteralPath $root -Force | Select-Object -ExpandProperty Name)
    if ($remaining.Count -eq 0 -and $names.Count -eq 2 -and $names -contains '.harness-runtime-owner' -and $names -contains '.harness-runtime-files.json') {
        Remove-Item -LiteralPath $receipt -Force
        Remove-Item -LiteralPath (Join-Path $root '.harness-runtime-owner') -Force
        [IO.Directory]::Delete($root, $false)
        foreach ($entry in $plan.registry.PSObject.Properties) {
            if (-not $entry.Name.StartsWith('Software\Microsoft\Windows\CurrentVersion\Uninstall\', [StringComparison]::Ordinal)) { throw 'Unexpected registry scope' }
            $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($entry.Name)
            if ($null -eq $key) { continue }
            try {
                if ($key.SubKeyCount -ne 0 -or $key.ValueCount -ne @($entry.Value.PSObject.Properties).Count) { throw 'Modified runtime registration preserved' }
                foreach ($value in $entry.Value.PSObject.Properties) {
                    if ($key.GetValue($value.Name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) -cne $value.Value[0] -or
                        [int]$key.GetValueKind($value.Name) -ne $value.Value[1]) { throw 'Modified runtime registration preserved' }
                }
            } finally { $key.Dispose() }
            [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKey($entry.Name, $false)
        }
        $registration = Checked-Path $plan.condaRegistration
        if (Test-Path -LiteralPath $registration -PathType Leaf) {
            $bytes = [IO.File]::ReadAllBytes($registration)
            if ($bytes.Length -gt 1048576) { throw 'Large Conda registration preserved' }
            $encoding = [Text.UTF8Encoding]::new($false, $true)
            $text = $encoding.GetString($bytes)
            $prefix = [IO.Path]::GetFullPath((Join-Path $root 'envs\harness'))
            $kept = [Text.StringBuilder]::new()
            foreach ($line in [regex]::Matches($text, '[^\r\n]*(?:\r\n|\n|\r|$)')) {
                $value = $line.Value.Trim()
                $remove = $false
                if ($value) { try { $remove = [IO.Path]::GetFullPath($value) -ieq $prefix } catch {} }
                if (-not $remove) { [void]$kept.Append($line.Value) }
            }
            if ($kept.ToString() -cne $text) {
                $temporary = $registration + '.harness-' + [guid]::NewGuid().ToString('N')
                [IO.File]::WriteAllBytes($temporary, $encoding.GetBytes($kept.ToString()))
                try {
                    if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($registration)) -cne [Convert]::ToBase64String($bytes)) { throw 'Conda registration changed concurrently' }
                    [IO.File]::Replace($temporary, $registration, [NullString]::Value)
                } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force } }
            }
        }
        Remove-Item -LiteralPath (Join-Path $job 'plan.json') -Force
        Remove-Item -LiteralPath $ScriptPath -Force
        [IO.Directory]::Delete($job, $false)
    } else {
        $remaining.Add($root)
        $remaining | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $job 'remaining.json') -Encoding UTF8
    }
} catch {
    $_.Exception.Message | Set-Content -LiteralPath (Join-Path $job 'error.txt') -Encoding UTF8
    exit 1
}
