# Study F: offline self-test, Unity precheck, formal run (640 trials). Stops at the first failure.
# Requires: Python 3.10+ on PATH and $env:UNITY_EDITOR set to the Unity 2020.3.49f1 editor executable.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
Write-Host "[1/3] offline self-test"
& $py test_f.py
if ($LASTEXITCODE -ne 0) { throw "offline self-test failed" }
Write-Host "[2/3] Unity precheck"
& $py f_manager.py --precheck
if ($LASTEXITCODE -ne 0) { throw "precheck failed" }
$gate = Get-Content (Join-Path $PSScriptRoot "prechecks\precheck_F\precheck_gate.json") -Raw | ConvertFrom-Json
if (-not $gate.passed) { throw "precheck gate not passed; see prechecks\precheck_F" }
Write-Host "[3/3] formal run (640 trials)"
& $py f_manager.py --expected-completed 0
if ($LASTEXITCODE -ne 0) { throw "formal run halted; see execution\formal_F\status.json" }
Write-Host "Study F complete."
