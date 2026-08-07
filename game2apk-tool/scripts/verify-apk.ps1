param(
    [Parameter(Mandatory=$true)][string]$Apk,
    [string]$StartedAt,
    [string]$ApplicationId,
    [int]$VersionCode,
    [switch]$AdbInstall
)

$ErrorActionPreference = 'Stop'
$toolRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$env:PYTHONPATH = Join-Path $toolRoot 'src'
$argsList = @('game2apk.cli', 'verify', '--apk', (Resolve-Path $Apk).Path)
if ($StartedAt) { $argsList += @('--started-at', $StartedAt) }
if ($ApplicationId) { $argsList += @('--application-id', $ApplicationId) }
if ($PSBoundParameters.ContainsKey('VersionCode')) { $argsList += @('--version-code', $VersionCode) }
if ($AdbInstall) { $argsList += '--adb-install' }
& python -m $argsList
exit $LASTEXITCODE

