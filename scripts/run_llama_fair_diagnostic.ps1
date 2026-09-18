# Fair llama diagnostic: n=20, pre+post trial Ollama drain, isolated from n100 results.
# Interpretation: if success stays ~stable across trials 1-20 (no trial-9 cliff), low rate = model/cap;
# if early success then collapse, remaining issue is infra (Ollama queue / orphans).
$ErrorActionPreference = "Stop"
$Root = "c:\Users\aaron\agentic_rag_mvp"
$Exp = "experiment2_llama_fair_n20"
$OutDir = Join-Path $Root "output\benchmark\$Exp"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

powershell -NoProfile -File (Join-Path $Root "scripts\stop_benchmark_and_cleanup.ps1")

$env:EMBEDDING_PROVIDER = "ollama"
$env:EMBEDDING_MODEL = "nomic-embed-text"
$env:PYTHONUTF8 = "1"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Log = Join-Path $OutDir "run.log"
$Err = Join-Path $OutDir "run.err"

@"
Fair llama diagnostic started $(Get-Date -Format o)
- n=20 llama3.2:3b only
- pre+post trial Ollama unload (keep_alive=0)
- same caps as mitigated n100: 300s job / 210s invoke
- separate folder: $Exp (does not touch experiment2 or mitigated_n100)
"@ | Out-File (Join-Path $OutDir "FAIR_RUN_NOTES.txt") -Encoding utf8

$argLine = "`"$Root\scripts\llm_benchmark.py`" --run --plot --experiment-id $Exp --mission-id llm_benchmark --models llama3.2:3b --trials 20 --timeout 300 --skip-judge --figures-dir figures"
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "set EMBEDDING_PROVIDER=ollama&& set EMBEDDING_MODEL=nomic-embed-text&& set PYTHONUTF8=1&& `"$Py`" $argLine >> `"$Log`" 2>> `"$Err`"" -WorkingDirectory $Root -WindowStyle Hidden
Write-Host "Fair llama diagnostic started. Logs: $Log"
