# VLM goal-check calibration: offline self-test, frame capture in Unity (with graphics), VLM queries, analysis.
# Requires: Python 3.10+ on PATH, $env:UNITY_EDITOR (Unity 2020.3.49f1 editor executable) and $env:DASHSCOPE_API_KEY.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
Write-Host "[1/4] offline self-test"
& $py test_capture.py
if ($LASTEXITCODE -ne 0) { throw "self-test failed" }
Write-Host "[2/4] capture frames (20 trials in Unity)"
& $py capture_states.py launch
if ($LASTEXITCODE -ne 0) { throw "capture failed; see the execution folder and the last runner.log" }
Write-Host "[3/4] query the VLM (resumable; answers are cached in answers.jsonl)"
& $py query_vlm.py --workers 4
if ($LASTEXITCODE -ne 0) { throw "query failed; re-run this step to resume" }
Write-Host "[4/4] analyse"
& $py analyze_vlm.py
Write-Host "VLM calibration complete: vlm_error_structure.json"
