<#
.SYNOPSIS
  conda-pack the given env to conda_env_bundle.tar.gz (for offline copy with the project).

.PARAMETER EnvName
  Default: douyin-compass

.PARAMETER OutFile
  Default: <ProjectRoot>\conda_env_bundle.tar.gz

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\pack_conda_env.ps1
#>
param(
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
  [string]$EnvName = "douyin-compass",
  [string]$OutFile = "",
  [switch]$SkipPrepHint = $false
)

$ErrorActionPreference = "Stop"

if (-not $OutFile) {
  $OutFile = Join-Path $ProjectRoot "conda_env_bundle.tar.gz"
}

$conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $conda) {
  throw "conda not found."
}

function Get-CondaBase {
  $lines = (& conda info --base 2>&1 | ForEach-Object { "$_" })
  foreach ($line in $lines) {
    $t = $line.Trim()
    # 只要「盘符:\」形式的一行，避免 conda 报错/多行输出污染路径
    if ($t -match '^[A-Za-z]:\\' -and (Test-Path -LiteralPath $t)) {
      return $t
    }
  }
  throw "Could not resolve conda base from 'conda info --base'. Output:`n$( $lines -join "`n" )"
}

function Find-CondaPackExe {
  try {
    $condaBase = Get-CondaBase
    $scriptExe = Join-Path $condaBase "Scripts\conda-pack.exe"
    if (Test-Path -LiteralPath $scriptExe) {
      return [string]$scriptExe
    }
  }
  catch {
    # ignore; fall through
  }

  $exe = Get-Command conda-pack -ErrorAction SilentlyContinue
  if ($exe -and $exe.Source -match '\.(exe|EXE)$') {
    return [string]$exe.Source
  }

  return $null
}

function Ensure-CondaPackExe {
  $existing = Find-CondaPackExe
  if ($existing) { return $existing }

  Write-Host "Installing conda-pack into conda base (conda-forge)..."
  # conda 常把进度写到 stderr；直接调用可能触发 PowerShell NativeCommandError，改用 cmd 避免中断
  cmd.exe /c "conda install -n base -c conda-forge conda-pack -y"
  $condaOk = ($LASTEXITCODE -eq 0)

  $existing = Find-CondaPackExe
  if ($existing) { return $existing }

  if (-not $condaOk) {
    Write-Host "conda install conda-pack failed (e.g. Malformed version string); trying pip in base..."
  }

  $condaBase = Get-CondaBase
  $basePy = Join-Path $condaBase "python.exe"
  if (-not (Test-Path $basePy)) {
    throw "base python not found: $basePy"
  }

  & $basePy -m pip install --upgrade conda-pack 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) {
    throw "pip install conda-pack failed; fix conda/pip then retry."
  }

  $explicit = Join-Path $condaBase "Scripts\conda-pack.exe"
  if (Test-Path -LiteralPath $explicit) {
    return [string]$explicit
  }

  throw "conda-pack installed but conda-pack.exe not found under $($condaBase)\Scripts."
}

$packExe = [string](Ensure-CondaPackExe)

Write-Host "Using: $packExe"
Write-Host "conda-pack env '$EnvName' -> $OutFile (large file, normal)..."

if (Test-Path $OutFile) {
  Remove-Item $OutFile -Force
}

$oldEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
  # 含空格路径不要用 Start-Process 拆参；与 conda-pack 0.7 使用长选项更稳
  & $packExe @("--name", $EnvName, "--output", $OutFile, "--ignore-editable-packages") 2>&1 | Out-Host
}
finally {
  $ErrorActionPreference = $oldEap
}
if ($LASTEXITCODE -ne 0) {
  throw "conda-pack failed with exit code $LASTEXITCODE"
}

$item = Get-Item -LiteralPath $OutFile -ErrorAction SilentlyContinue
if (-not $item -or $item.Length -lt 4096) {
  throw "Archive missing or suspiciously small: $OutFile"
}

Write-Host ""
Write-Host "Created: $OutFile ($([math]::Round($item.Length / 1MB, 2)) MiB)"
if (-not $SkipPrepHint) {
  Write-Host "Tip: run prep_conda_env_for_pack.ps1 first so browsers are inside the env."
}
