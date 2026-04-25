#Requires -Version 5.1
<#
.SYNOPSIS
  Reliable Streamlit startup for paths with spaces / parentheses (avoids fragile cmd START).
#>
param(
    [Parameter(Mandatory)][string]$PythonExe,
    [Parameter(Mandatory)][string]$ProjectRoot,
    [Parameter()][int]$Port = 8502,
    [Parameter()][switch]$Hidden
)

$ErrorActionPreference = 'Stop'
$py = (Resolve-Path -LiteralPath $PythonExe).Path
$root = (Resolve-Path -LiteralPath $ProjectRoot).Path

if (-not (Test-Path -LiteralPath $py)) {
    Write-Host "[ERROR] Python not found: $py" -ForegroundColor Red
    exit 2
}

$arguments = @(
    '-m', 'streamlit', 'run', 'scripts\streamlit_ops_console.py',
    '--server.port', "$Port",
    '--server.address', '127.0.0.1'
)

Write-Host "[Launch-StreamlitConsole] Python : $py"
Write-Host "[Launch-StreamlitConsole] WorkDir: $root"

$windowStyle = if ($Hidden) { 'Hidden' } else { 'Normal' }
$p = Start-Process -FilePath $py -ArgumentList $arguments -WorkingDirectory $root `
    -WindowStyle $windowStyle -PassThru

if (-not $p) {
    Write-Host '[ERROR] Start-Process returned null.' -ForegroundColor Red
    exit 3
}

Start-Sleep -Milliseconds 800
if ($p.HasExited -and $p.ExitCode -ne 0) {
    Write-Host "[ERROR] Streamlit exited immediately with code $($p.ExitCode)." -ForegroundColor Red
    exit [int]$p.ExitCode
}

exit 0
