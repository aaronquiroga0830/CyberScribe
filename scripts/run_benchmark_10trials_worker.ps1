# Worker: runs 10-trial benchmark to completion (invoked detached by launcher).
$ErrorActionPreference = "Continue"
$Root = "c:\Users\aaron\agentic_rag_mvp"
$OutDir = Join-Path $Root "output\benchmark\experiment2"
Set-Location $Root

$env:EMBEDDING_PROVIDER = "ollama"
$env:EMBEDDING_MODEL = "nomic-embed-text"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Log = Join-Path $OutDir "run_10trial.log"
$Err = Join-Path $OutDir "run_10trial.err"

"Worker started $(Get-Date -Format o)" | Add-Content $Log

& $Py -u (Join-Path $Root "scripts\llm_benchmark.py") --run --plot `
  --mission-id llm_benchmark --experiment-id experiment2 `
  --trials 10 --timeout 300 --judge-model llama3.2:3b `
  1>> $Log 2>> $Err

$code = $LASTEXITCODE
"Finished $(Get-Date -Format o) exit_code=$code" | Add-Content (Join-Path $OutDir "STATUS.txt")
if ($code -eq 0) { "SUCCESS" } else { "FAILED exit $code" } | Add-Content (Join-Path $OutDir "STATUS.txt")
Remove-Item (Join-Path $OutDir "benchmark.lock") -Force -ErrorAction SilentlyContinue
exit $code
