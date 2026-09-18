# Stop all llm_benchmark harnesses and cancel stale llm_benchmark pipeline jobs.
$ErrorActionPreference = "Stop"
$Root = "c:\Users\aaron\agentic_rag_mvp"
Set-Location $Root

Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*llm_benchmark.py*" } |
  ForEach-Object {
    Write-Host "Stopping benchmark PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

Start-Sleep -Seconds 2

Get-ChildItem "output\benchmark" -Recurse -Filter "benchmark.lock" -ErrorAction SilentlyContinue |
  ForEach-Object {
    Write-Host "Removing lock $($_.FullName)"
    Remove-Item $_.FullName -Force
  }

& "$Root\.venv\Scripts\python.exe" -c @"
from src.pipeline_job_service import fail_stale_running_jobs
n = fail_stale_running_jobs('llm_benchmark', 'stop_benchmark_and_cleanup.ps1')
print('cancelled_stale_jobs', n)
"@

& "$Root\.venv\Scripts\python.exe" -c @"
import os, sys
sys.path.insert(0, r'$Root')
os.chdir(r'$Root')
sys.path.insert(0, os.path.join(r'$Root', 'scripts'))
from llm_benchmark import ollama_unload_model
import subprocess, json
try:
    out = subprocess.check_output(['ollama', 'ps'], text=True, timeout=30)
    models = []
    for line in out.splitlines()[1:]:
        name = line.split()[0] if line.strip() else None
        if name:
            models.append(name)
except Exception:
    models = []
for m in models:
    ollama_unload_model(m)
print('ollama_unloaded', models)
"@

Write-Host "Ollama loaded models:"
ollama ps 2>$null
