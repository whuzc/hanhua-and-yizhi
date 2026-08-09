param(
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$toolRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$srcRoot = Join-Path $toolRoot 'src'
$spec = Join-Path $toolRoot 'scripts\game2apk.spec'
$portableRoot = Join-Path $toolRoot 'dist\portable'
$env:PYTHONPATH = $srcRoot

$python = (Get-Command python -ErrorAction Stop).Source
if (-not $SkipTests) {
    & $python (Join-Path $toolRoot 'tests\run_tests.py')
    if ($LASTEXITCODE -ne 0) { throw "unit tests failed; portable build stopped" }
}

New-Item -ItemType Directory -Path $portableRoot -Force | Out-Null
& $python -m PyInstaller --noconfirm --clean --distpath $portableRoot --workpath (Join-Path $toolRoot '.work\pyinstaller') $spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$portableAppRoot = (Resolve-Path (Join-Path $portableRoot 'game2apk-tool')).Path
$templateSource = Join-Path $toolRoot 'templates\android-rpgmv'
$templateTarget = Join-Path $portableAppRoot 'templates\android-rpgmv'
if (-not (Test-Path -LiteralPath $templateSource -PathType Container)) { throw "clean Android template is missing: $templateSource" }
if (Test-Path -LiteralPath $templateTarget) {
    Remove-Item -LiteralPath $templateTarget -Recurse -Force
}
Copy-Item -LiteralPath $templateSource -Destination $templateTarget -Recurse -Force
$frontendSource = Join-Path $toolRoot 'frontend'
$frontendTarget = Join-Path $portableAppRoot 'frontend'
if (-not (Test-Path -LiteralPath $frontendSource -PathType Container)) { throw "frontend assets are missing: $frontendSource" }
if (Test-Path -LiteralPath $frontendTarget) { Remove-Item -LiteralPath $frontendTarget -Recurse -Force }
Copy-Item -LiteralPath $frontendSource -Destination $frontendTarget -Recurse -Force

$artifactDirectoryNames = @('build', '.gradle', '.gradle-home', '.work', '.state', 'dist')
Get-ChildItem -LiteralPath $templateTarget -Recurse -Directory -Force |
    Sort-Object FullName -Descending |
    Where-Object { $artifactDirectoryNames -contains $_.Name } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
Get-ChildItem -LiteralPath $templateTarget -Recurse -File -Force |
    Where-Object { $_.Extension -match '(?i)^\.(apk|aab|jks|keystore)$' -or $_.Name -match '(?i)password|api[_-]?key' } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

$forbidden = Get-ChildItem -LiteralPath $portableAppRoot -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '(?i)(\.rpgsave$|\.jks$|\.keystore$|password|api[_-]?key)' }
if ($forbidden) {
    throw "portable output contains a forbidden credential/save-like file"
}
Write-Host "Portable tool: $portableAppRoot"
