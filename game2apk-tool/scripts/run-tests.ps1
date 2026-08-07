$ErrorActionPreference = 'Stop'
$toolRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$env:PYTHONPATH = Join-Path $toolRoot 'src'
& python (Join-Path $toolRoot 'tests\run_tests.py')
exit $LASTEXITCODE

