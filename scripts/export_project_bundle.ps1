<#
.SYNOPSIS
  将项目打成 zip，便于拷贝到其它电脑解压后运行（不含 .venv / 大体量运行产出）。

.PARAMETER ProjectRoot
  项目根目录，默认为本脚本上一级。

.PARAMETER OutZip
  输出 zip 路径；默认为桌面 fff-dianshang_bundle_<日期时间>.zip

.PARAMETER IncludeOutput
  是否包含 output 目录（通常很大，默认不包含）

.PARAMETER IncludeLog
  是否包含 log 目录（默认不包含）

.PARAMETER IncludeDailydate
  是否包含 dailydate 目录（默认不包含）

.PARAMETER CondaArchivePath
  可选：conda-pack 生成的 conda_env_bundle.tar.gz 路径。
  若项目根目录已存在 conda_env_bundle.tar.gz，会直接打进 zip（可与 -CondaArchivePath 覆盖默认路径）。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\export_project_bundle.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\export_project_bundle.ps1 -CondaArchivePath D:\bak\conda_env_bundle.tar.gz
#>
param(
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
  [string]$OutZip = "",
  [switch]$IncludeOutput = $false,
  [switch]$IncludeLog = $false,
  [switch]$IncludeDailydate = $false,
  [string]$CondaArchivePath = ""
)

$ErrorActionPreference = "Stop"

if (-not $OutZip) {
  $desk = [Environment]::GetFolderPath("Desktop")
  $OutZip = Join-Path $desk ("fff-dianshang_bundle_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".zip")
}

$stamp = [Guid]::NewGuid().ToString("n").Substring(0, 8)
$stage = Join-Path $env:TEMP ("fff_bundle_stage_" + $stamp)

Write-Host "Project: $ProjectRoot"
Write-Host "Stage: $stage"
Write-Host "Zip: $OutZip"

if (Test-Path $stage) {
  Remove-Item $stage -Recurse -Force
}
New-Item -ItemType Directory -Path $stage | Out-Null

$excludeDirs = @(
  ".venv", ".git", "__pycache__", ".pytest_cache", "node_modules",
  ".mypy_cache", ".ruff_cache", "conda_env"
)
if (-not $IncludeOutput) { $excludeDirs += "output" }
if (-not $IncludeLog) { $excludeDirs += "log" }
if (-not $IncludeDailydate) { $excludeDirs += "dailydate" }

$robArgs = @("/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/XD") + $excludeDirs
& robocopy $ProjectRoot $stage @robArgs | Out-Null
$robocode = $LASTEXITCODE
if ($robocode -ge 8) {
  throw "robocopy failed, exit code: $robocode"
}

$guideSrc = Join-Path $ProjectRoot "doc\新电脑部署指南.txt"
if (Test-Path $guideSrc) {
  Copy-Item $guideSrc (Join-Path $stage "部署说明.txt") -Force
}

$condaTarDefault = Join-Path $ProjectRoot "conda_env_bundle.tar.gz"
if ($CondaArchivePath -ne "" -and (Test-Path $CondaArchivePath)) {
  Copy-Item $CondaArchivePath (Join-Path $stage "conda_env_bundle.tar.gz") -Force
  Write-Host "Added conda bundle (custom path): $CondaArchivePath"
}
elseif (Test-Path $condaTarDefault) {
  Write-Host "conda_env_bundle.tar.gz at project root was copied into zip by robocopy."
}
else {
  Write-Host "Hint: conda_env_bundle.tar.gz missing (run prep_conda_env_for_pack.ps1 then pack_conda_env.ps1)."
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
if (Test-Path $OutZip) {
  Remove-Item $OutZip -Force
}
[System.IO.Compression.ZipFile]::CreateFromDirectory($stage, $OutZip)

Remove-Item $stage -Recurse -Force

Write-Host ""
Write-Host "Created: $OutZip"
Write-Host "Copy zip to target PC; read 部署说明.txt after extract."
Write-Host "  With conda_env_bundle.tar.gz: run scripts\unpack_conda_env.ps1 then start_streamlit_console.bat (no install_local.ps1)."
Write-Host "  Python-only venv path: run scripts\install_local.ps1"
Write-Host "Excluded dir names: $($excludeDirs -join ', ') (use -IncludeOutput / -IncludeLog / -IncludeDailydate to change)."
