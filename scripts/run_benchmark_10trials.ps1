# Single canonical 10-trial Experiment 2 run (detached python, no stdout pipe).
$ErrorActionPreference = "Stop"
$Root = "c:\Users\aaron\agentic_rag_mvp"
$OutDir = Join-Path $Root "output\benchmark\experiment2"
$Lock = Join-Path $OutDir "benchmark.lock"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object {
  $_.CommandLine -like "*llm_benchmark.py*"
} | ForEach-Object {
  Write-Host "Stopping PID $($_.ProcessId)"
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

if (Test-Path $Lock) {
  $oldPid = Get-Content $Lock -ErrorAction SilentlyContinue
  if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
    Write-Error "Benchmark already running (python PID $oldPid)."
    exit 1
  }
  Remove-Item $Lock -Force
}

& $Py (Join-Path $Root "scripts\cleanup_benchmark_state.py") | Out-Host

$env:EMBEDDING_PROVIDER = "ollama"
$env:EMBEDDING_MODEL = "nomic-embed-text"
"Started $(Get-Date -Format o)" | Set-Content (Join-Path $OutDir "STATUS.txt") -Encoding utf8

$proc = Start-Process -FilePath $Py -ArgumentList @(
  "-u", (Join-Path $Root "scripts\llm_benchmark.py"),
  "--run", "--plot",
  "--mission-id", "llm_benchmark",
  "--experiment-id", "experiment2",
  "--trials", "10",
  "--timeout", "300",
  "--judge-model", "llama3.2:3b"
) -WorkingDirectory $Root -WindowStyle Hidden -PassThru

$proc.Id | Set-Content $Lock -Encoding utf8
Write-Host "Benchmark python PID=$($proc.Id)"
Write-Host "Monitor: (Get-Content output\benchmark\experiment2\results.csv -EA 0).Count  (expect 31)"
