# Resume mitigated n=100 benchmark (single process, UTF-8 logs via cmd redirect).
param(
    [int]$Timeout = 300,
    [string]$ExperimentId = "experiment2_mitigated_n100",
    [string]$MissionId = "llm_benchmark"
)

$ErrorActionPreference = "Stop"
$Root = "c:\Users\aaron\agentic_rag_mvp"
$OutDir = Join-Path $Root "output\benchmark\$ExperimentId"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$env:EMBEDDING_PROVIDER = "ollama"
$env:EMBEDDING_MODEL = "nomic-embed-text"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $Root "scripts\llm_benchmark.py"
$Log = Join-Path $OutDir "run.log"
$Err = Join-Path $OutDir "run.err"

"Resumed $(Get-Date -Format o)" | Add-Content (Join-Path $OutDir "STATUS.txt") -Encoding utf8

$argLine = @(
    "`"$Script`"",
    "--run", "--plot", "--resume",
    "--experiment-id", $ExperimentId,
    "--mission-id", $MissionId,
    "--models", "gemma2:2b,llama3.2:3b",
    "--trials", "100",
    "--timeout", "$Timeout",
    "--skip-judge"
) -join " "

Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$Py`" $argLine >> `"$Log`" 2>> `"$Err`"" -WorkingDirectory $Root -WindowStyle Hidden
Write-Host "Benchmark started detached. Logs: $Log"
