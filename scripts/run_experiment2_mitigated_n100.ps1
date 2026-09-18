# Overnight mitigated benchmark: n=100 trials per model (300 total), clean-run safeguards.
# Do NOT start a second copy. If stuck: scripts\stop_benchmark_and_cleanup.ps1 then re-run with --resume.
$ErrorActionPreference = "Stop"
$Root = "c:\Users\aaron\agentic_rag_mvp"
$OutDir = Join-Path $Root "output\benchmark\experiment2_mitigated_n100"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

param([switch]$Resume)

$env:EMBEDDING_PROVIDER = "ollama"
$env:EMBEDDING_MODEL = "nomic-embed-text"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $Root "scripts\llm_benchmark.py"
$Log = Join-Path $OutDir "run.log"
$Err = Join-Path $OutDir "run.err"

$line = "Started $(Get-Date -Format o) trials=100 per model"
if ($Resume) { $line += " (resume)" }
$line | Out-File (Join-Path $OutDir "STATUS.txt") -Encoding utf8

$resumeFlag = if ($Resume) { "--resume" } else { "" }
$argLine = "`"$Script`" --run --plot $resumeFlag --experiment-id experiment2_mitigated_n100 --mission-id llm_benchmark --models `"phi3,llama3.2:3b,gemma2:2b`" --trials 100 --timeout 300 --skip-judge"
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$Py`" $argLine >> `"$Log`" 2>> `"$Err`"" -WorkingDirectory $Root -WindowStyle Hidden
Write-Host "Benchmark started detached. Logs: $Log"

# Process runs detached; check STATUS.txt / run.log for completion.
