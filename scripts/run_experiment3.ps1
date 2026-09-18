# Experiment 3: seeded partial RMP + update_from_evidence (incremental deltas).
# Launches detached Python worker; keep machine awake during run.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
$logDir = Join-Path (Get-Location) "output\benchmark\experiment3"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$setupLog = Join-Path $logDir "setup.log"
$runLog = Join-Path $logDir "run.log"

Write-Host "Experiment 3 setup (incremental mission + seed RMP)..."
& $py scripts\llm_benchmark.py --setup-incremental --experiment-id experiment3 --mission-id llm_benchmark_inc --models "llama3.2:3b,gemma2:2b" 2>&1 | Tee-Object -FilePath $setupLog

Write-Host "Starting detached benchmark run (llama + gemma, n=5, judge on)..."
$worker = Join-Path (Get-Location) "scripts\run_experiment3_worker.ps1"
Start-Process powershell -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $worker
) -WindowStyle Hidden

Write-Host "Monitor: (Get-Content output\benchmark\experiment3\results.csv).Count  # expect 11 (header + 10 rows)"
Write-Host "When complete: .\.venv\Scripts\python.exe scripts\llm_benchmark.py --plot --experiment-id experiment3"
