# Prevents system sleep while Experiment 2 runs. Stop with Ctrl+C or close window after benchmark finishes.
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class StayAwake {
  [DllImport("kernel32.dll", CharSet=CharSet.Auto, SetLastError=true)]
  public static extern uint SetThreadExecutionState(uint esFlags);
}
"@
Write-Host "Stay-awake active (prevents sleep). Close this window when experiment is done."
while ($true) {
  [StayAwake]::SetThreadExecutionState(0x80000003) | Out-Null
  Start-Sleep -Seconds 45
}
