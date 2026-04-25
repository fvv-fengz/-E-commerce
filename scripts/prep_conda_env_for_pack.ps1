<#
.SYNOPSIS
  Install Playwright chromium INTO the conda env prefix so conda-pack includes browsers.

.PARAMETER EnvName
  Conda env name (default: douyin-compass).

.EXAMPLE
  conda activate douyin-compass
  powershell -ExecutionPolicy Bypass -File .\scripts\prep_conda_env_for_pack.ps1

NOTE
  Does not use 'conda run' (missing on older conda). Uses python.exe inside the env.
#>
param(
  [string]$EnvName = "douyin-compass"
)

$ErrorActionPreference = "Stop"

$conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $conda) {
  throw "conda not found. Install Miniconda/Anaconda and ensure conda is on PATH."
}

Write-Host "[1/2] Installing Playwright chromium into env '$EnvName' (browsers live under env prefix)..."

$helper = Join-Path $PSScriptRoot "_playwright_install_in_prefix.py"
if (-not (Test-Path $helper)) {
  throw "Missing helper script: $helper"
}

function Get-PythonInEnv {
  param([string]$Name)

  $baseOut = & conda info --base 2>&1
  if ($LASTEXITCODE -ne 0) {
    throw "conda info --base failed: $baseOut"
  }
  $base = ($baseOut | Select-Object -First 1).ToString().Trim()
  $fromList = Join-Path $base "envs\$Name\python.exe"
  if (Test-Path $fromList) {
    return $fromList
  }

  # Env not under default envs\<name> (or name mismatch) — use active prefix if it matches env name
  $prefix = $env:CONDA_PREFIX
  if ($prefix -and ((Split-Path $prefix -Leaf) -eq $Name)) {
    $py = Join-Path $prefix "python.exe"
    if (Test-Path $py) {
      return $py
    }
  }

  throw "Cannot find python.exe for conda env '$Name'. Expected '$fromList'. Create the env or pass -EnvName."
}

$pyExe = Get-PythonInEnv -Name $EnvName
Write-Host "Using: $pyExe"

& $pyExe $helper
if ($LASTEXITCODE -ne 0) {
  throw "playwright install failed, exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Done. Next on this machine run:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\pack_conda_env.ps1"
Write-Host "Then zip the project (export_project_bundle.ps1) so conda_env_bundle.tar.gz is included."
