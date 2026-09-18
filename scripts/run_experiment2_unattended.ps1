# Unattended Experiment 2: RMP-only benchmark + local LLM judge + charts
$ErrorActionPreference = "Stop"
$Root = "c:\Users\aaron\agentic_rag_mvp"
$OutDir = Join-Path $Root "output\benchmark\experiment2"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# Reduce sleep while on AC (best-effort; stay-awake script is the main guard)
try {
  powercfg /change standby-timeout-ac 0 2>$null
  powercfg /change hibernate-timeout-ac 0 2>$null
} catch {}

# Background stay-awake (non-fatal if this fails)
try {
  Start-Process powershell.exe -ArgumentList @(
    "-NoProfile", "-WindowStyle", "Hidden", "-File", (Join-Path $Root "scripts\keep_awake.ps1")
  ) -WindowStyle Hidden
} catch {
  "Warning: could not start keep_awake.ps1: $_" | Out-File (Join-Path $OutDir "STATUS.txt")
}

$env:EMBEDDING_PROVIDER = "ollama"
$env:EMBEDDING_MODEL = "nomic-embed-text"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Log = Join-Path $OutDir "run.log"
$Err = Join-Path $OutDir "run.err"

"Started $(Get-Date -Format o)" | Out-File (Join-Path $OutDir "STATUS.txt") -Encoding utf8

& $Py (Join-Path $Root "scripts\llm_benchmark.py") --run --plot --mission-id llm_benchmark `
  --experiment-id experiment2 --judge-model llama3.2:3b `
  1>> $Log 2>> $Err

$code = $LASTEXITCODE
"Finished $(Get-Date -Format o) exit_code=$code" | Add-Content (Join-Path $OutDir "STATUS.txt") -Encoding utf8
$statusLine = if ($code -eq 0) { "SUCCESS" } else { "FAILED exit $code" }
$statusLine | Add-Content (Join-Path $OutDir "STATUS.txt") -Encoding utf8

# Stop stay-awake processes
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object {
  $_.CommandLine -like "*keep_awake.ps1*"
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

exit $code
