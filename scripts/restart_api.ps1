param(
    [int]$Port = 8000,
    [switch]$StopOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".Search\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python not found: $python"
}

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($listener in @($listeners)) {
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $listener.OwningProcess)
    $cmd = [string]$proc.CommandLine
    if ($cmd -match "claimlab\.api") {
        Write-Host "[stop] stale claimlab.api PID $($listener.OwningProcess)"
        Stop-Process -Id $listener.OwningProcess -Force
    } else {
        throw "Port $Port is used by PID $($listener.OwningProcess), command: $cmd. Refusing to kill a non-claimlab process."
    }
}

if ($StopOnly) {
    Write-Host "[ok] port $Port is free"
    exit 0
}

Start-Sleep -Milliseconds 500
Write-Host "[start] $python -m claimlab.api"
Push-Location $root
try {
    & $python -m claimlab.api
}
finally {
    Pop-Location
}
