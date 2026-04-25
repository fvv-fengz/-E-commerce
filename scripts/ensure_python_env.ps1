<#
.SYNOPSIS
  部署机「Python 环境优先」预检：conda_env 可用 / 自动解压 tar.gz / 或确认本机有 py、python 可建 .venv。

  由 一键启动.bat 最先调用；也可单独运行排查环境。
#>
param(
  [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
  $ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
}
else {
  $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
}

$resolveScript = Join-Path $PSScriptRoot "resolve_conda_python.ps1"
$unpackScript = Join-Path $PSScriptRoot "unpack_conda_env.ps1"

function Get-ResolvedCondaPython {
  param([string]$Root)
  $line = & $resolveScript -ProjectRoot $Root 2>$null | Select-Object -First 1
  if ($line -and (Test-Path -LiteralPath $line)) {
    return $line.Trim()
  }
  return $null
}

function Test-VenvPython {
  param([string]$Root)
  $py = Join-Path $Root ".venv\Scripts\python.exe"
  return (Test-Path -LiteralPath $py)
}

function Test-PyLauncherOrPython {
  $hasPy = [bool](Get-Command py.exe -ErrorAction SilentlyContinue)
  $hasPython = [bool](Get-Command python.exe -ErrorAction SilentlyContinue)
  return $hasPy -or $hasPython
}

$tarGz = Join-Path $ProjectRoot "conda_env_bundle.tar.gz"
$condaDir = Join-Path $ProjectRoot "conda_env"

Write-Host "[python-env] ProjectRoot: $ProjectRoot"

$resolved = Get-ResolvedCondaPython $ProjectRoot
if ($resolved) {
  Write-Host "[python-env] OK: $resolved"
  exit 0
}

if (Test-Path -LiteralPath $tarGz) {
  Write-Host "[python-env] Offline bundle found; extracting (first run may take several minutes) ..."
  $cleanDest = Test-Path -LiteralPath $condaDir
  if ($cleanDest) {
    Write-Host "[python-env] Existing conda_env without valid python.exe — using clean extract (removing stale folder)."
  }
  try {
    if ($cleanDest) {
      & $unpackScript -ProjectRoot $ProjectRoot -ArchivePath $tarGz -CleanDest
    }
    else {
      & $unpackScript -ProjectRoot $ProjectRoot -ArchivePath $tarGz
    }
  }
  catch {
    Write-Host "[python-env] ERROR: unpack failed: $($_.Exception.Message)"
    exit 1
  }

  $resolved = Get-ResolvedCondaPython $ProjectRoot
  if (-not $resolved) {
    Write-Host "[python-env] ERROR: After unpack, no python.exe under conda_env."
    Write-Host "[python-env] Listing conda_env top-level:"
    if (Test-Path -LiteralPath $condaDir) {
      Get-ChildItem -LiteralPath $condaDir -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  - $($_.Name)" }
    }
    else {
      Write-Host "  (conda_env missing)"
    }
    Write-Host "[python-env] Try: delete folder conda_env manually, ensure conda_env_bundle.tar.gz is complete, run unpack again."
    exit 1
  }
  Write-Host "[python-env] OK: $resolved"
  exit 0
}

if (Test-VenvPython $ProjectRoot) {
  Write-Host "[python-env] OK: .venv\Scripts\python.exe exists."
  exit 0
}

if (Test-PyLauncherOrPython) {
  Write-Host "[python-env] OK: py.exe or python.exe on PATH (start_streamlit will create .venv if needed)."
  exit 0
}

Write-Host ""
Write-Host "[python-env] ERROR: No usable Python."
Write-Host "  - No conda_env (and no conda_env_bundle.tar.gz to auto-extract)."
Write-Host "  - No .venv yet."
Write-Host "  - No py.exe / python.exe on PATH."
Write-Host ""
Write-Host "Fix A (offline bundle): copy conda_env_bundle.tar.gz to project root, then run:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\unpack_conda_env.ps1 -CleanDest"
Write-Host "Fix B: Install Python 3.10+ for Windows, check 'Add python.exe to PATH', reinstall launcher."
Write-Host ""
exit 1
