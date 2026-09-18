$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
$logDir = Join-Path (Get-Location) "output\benchmark\experiment3"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$runLog = Join-Path $logDir "run.log"
$statusFile = Join-Path $logDir "STATUS.txt"

"STARTED $(Get-Date -Format o)" | Set-Content $statusFile

try {
    & $py scripts\llm_benchmark.py `
        --run `
        --experiment-id experiment3 `
        --mission-id llm_benchmark_inc `
        --models "llama3.2:3b,gemma2:2b" `
        --trials 5 `
        --update-intent update_from_evidence `
        --delta-dir data/eval/rmp_gold/deltas `
        2>&1 | Tee-Object -FilePath $runLog

    & $py scripts\llm_benchmark.py --plot --experiment-id experiment3 2>&1 | Tee-Object -FilePath (Join-Path $logDir "plot.log") -Append
    "SUCCESS $(Get-Date -Format o)" | Set-Content $statusFile
} catch {
    "FAILED $(Get-Date -Format o): $_" | Set-Content $statusFile
    throw
}
