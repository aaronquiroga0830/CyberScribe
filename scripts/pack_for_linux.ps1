# Creates a zip of the project for copying to Linux (excludes Windows venv and heavy regenerable dirs).
# Run from PowerShell:  .\scripts\pack_for_linux.ps1
# Output: ..\agentic_rag_mvp_for_linux.zip (next to project root) unless -OutPath is set.
param(
    [string]$OutPath = "",
    [switch]$IncludeGit
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
if ($OutPath -eq "") {
    $OutPath = Join-Path (Split-Path $root) "agentic_rag_mvp_for_linux.zip"
}

$tar = Get-Command tar -ErrorAction SilentlyContinue
if (-not $tar) {
    Write-Error "tar.exe not found (expected on Windows 10+). Install or add to PATH."
}

$excludes = @(
    ".venv",
    "node_modules",
    "__pycache__",
    "web/dist",
    "data/indexes",
    "output"
)
if (-not $IncludeGit) {
    $excludes += ".git"
}

$excludeArgs = @()
foreach ($e in $excludes) {
    $excludeArgs += "--exclude=$e"
}

Write-Host "Packing from: $root"
Write-Host "Output:       $OutPath"
Write-Host "Excludes:     $($excludes -join ', ')$(if ($IncludeGit) { '' } else { ' (use -IncludeGit to keep .git)' })"

Push-Location $root
try {
    # -a = auto compress (zip when .zip)
    $allArgs = @("-a", "-c", "-f", $OutPath) + $excludeArgs + @(".")
    & tar @allArgs
} finally {
    Pop-Location
}

Write-Host "Done."
