# Resume Experiment 2 without wiping results or killing unrelated processes.
# Skips trials already in output/benchmark/experiment2/results.csv.
$ErrorActionPreference = "Stop"
$Root = "c:\Users\aaron\agentic_rag_mvp"
$OutDir = Join-Path $Root "output\benchmark\experiment2"
$Lock = Join-Path $OutDir "benchmark.lock"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object {
  $_.CommandLine -like "*llm_benchmark.py*" -and $_.CommandLine -like "*experiment2*"
}
if ($running) {
  Write-Error "Experiment 2 benchmark already running (PID $($running.ProcessId)). Not starting a duplicate."
  exit 1
}

if (Test-Path $Lock) {
  $oldPid = Get-Content $Lock -ErrorAction SilentlyContinue
  if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
    Write-Error "benchmark.lock points to live PID $oldPid. Not starting a duplicate."
    exit 1
  }
  Remove-Item $Lock -Force
}

$rows = 0
if (Test-Path (Join-Path $OutDir "results.csv")) {
  $rows = (Get-Content (Join-Path $OutDir "results.csv")).Count
}
Write-Host "Existing results.csv lines: $rows (expect 31 when complete)"

& $Py (Join-Path $Root "scripts\cleanup_benchmark_state.py") | Out-Host

$env:EMBEDDING_PROVIDER = "ollama"
$env:EMBEDDING_MODEL = "nomic-embed-text"
"Resumed $(Get-Date -Format o)" | Add-Content (Join-Path $OutDir "STATUS.txt") -Encoding utf8

$proc = Start-Process -FilePath $Py -ArgumentList @(
  "-u", (Join-Path $Root "scripts\llm_benchmark.py"),
  "--run", "--resume", "--plot",
  "--mission-id", "llm_benchmark",
  "--experiment-id", "experiment2",
  "--models", "phi3,llama3.2:3b,gemma2:2b",
  "--trials", "10",
  "--timeout", "300",
  "--judge-model", "llama3.2:3b"
) -WorkingDirectory $Root -WindowStyle Hidden -PassThru

$proc.Id | Set-Content $Lock -Encoding utf8
Write-Host "Resume worker PID=$($proc.Id)"
Write-Host "Monitor: (Get-Content output\benchmark\experiment2\results.csv).Count  (expect 31)"
