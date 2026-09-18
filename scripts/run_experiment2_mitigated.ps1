# Mitigated Experiment 2: n=10 per model, 300s job cap, JSON-mode structured edits.
# Clean-run safeguards: benchmark.lock (single PID), preflight stale-job drain,
# cancel on harness timeout, BENCHMARK_MODE (no full-draft fallback), cooldown between models.
# Results: output/benchmark/experiment2_mitigated/ (does not touch experiment2/)
# If a run is stuck: scripts\stop_benchmark_and_cleanup.ps1 then re-run this script once.
$ErrorActionPreference = "Stop"
$Root = "c:\Users\aaron\agentic_rag_mvp"
$OutDir = Join-Path $Root "output\benchmark\experiment2_mitigated"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$env:EMBEDDING_PROVIDER = "ollama"
$env:EMBEDDING_MODEL = "nomic-embed-text"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Log = Join-Path $OutDir "run.log"
$Err = Join-Path $OutDir "run.err"

"Started $(Get-Date -Format o)" | Out-File (Join-Path $OutDir "STATUS.txt") -Encoding utf8

& $Py (Join-Path $Root "scripts\llm_benchmark.py") --run --plot `
  --experiment-id experiment2_mitigated `
  --mission-id llm_benchmark `
  --models "phi3,llama3.2:3b,gemma2:2b" `
  --trials 10 `
  --timeout 300 `
  --skip-judge `
  1>> $Log 2>> $Err

$code = $LASTEXITCODE
"Finished $(Get-Date -Format o) exit_code=$code" | Add-Content (Join-Path $OutDir "STATUS.txt") -Encoding utf8
exit $code
