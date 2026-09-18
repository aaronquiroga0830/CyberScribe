# Launch Experiment 2 in a detached process (survives Cursor terminal exit)
$Root = "c:\Users\aaron\agentic_rag_mvp"
$Runner = Join-Path $Root "scripts\run_experiment2_unattended.ps1"
$OutDir = Join-Path $Root "output\benchmark\experiment2"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$proc = Start-Process powershell.exe -ArgumentList @(
  "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Runner
) -WorkingDirectory $Root -WindowStyle Hidden -PassThru

"Launched detached PID=$($proc.Id) at $(Get-Date -Format o)" | Out-File (Join-Path $OutDir "LAUNCH.txt") -Encoding utf8
Write-Host "Experiment 2 started (PID $($proc.Id)). Monitor: output\benchmark\experiment2\STATUS.txt"
