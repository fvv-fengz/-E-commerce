<#
.SYNOPSIS
  Extract conda_env_bundle.tar.gz into conda_env and run conda-unpack.

.PARAMETER ArchivePath
  Default: <ProjectRoot>\conda_env_bundle.tar.gz

.PARAMETER TargetDir
  Default folder name: conda_env

.PARAMETER CleanDest
  解压前删除已有目标目录，避免残缺 conda_env 与 tar 合并导致 Scripts\python.exe 丢失。
#>
param(
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
  [string]$ArchivePath = "",
  [string]$TargetDirName = "conda_env",
  [switch]$CleanDest
)

$ErrorActionPreference = "Stop"

if (-not $ArchivePath) {
  $ArchivePath = Join-Path $ProjectRoot "conda_env_bundle.tar.gz"
}

if (-not (Test-Path $ArchivePath)) {
  throw "Offline env archive not found: $ArchivePath (place conda_env_bundle.tar.gz next to project root)."
}

$dest = Join-Path $ProjectRoot $TargetDirName
if ($CleanDest -and (Test-Path -LiteralPath $dest)) {
  Write-Host "CleanDest: removing $dest"
  Remove-Item -LiteralPath $dest -Recurse -Force
}
elseif (Test-Path -LiteralPath $dest) {
  Write-Host "Target exists, merging/overwriting: $dest (use -CleanDest if python.exe is still missing)"
}

Write-Host "Extract: $ArchivePath -> $dest"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

$tar = Get-Command tar.exe -ErrorAction SilentlyContinue
if (-not $tar) {
  throw "tar.exe not found (need Windows 10+ built-in tar)."
}

& tar.exe -xzf $ArchivePath -C $dest
if ($LASTEXITCODE -ne 0) {
  throw "tar failed, exit code $LASTEXITCODE"
}

$unpack = Get-ChildItem (Join-Path $dest "Scripts") -Filter "conda-unpack*" -ErrorAction SilentlyContinue | Select-Object -First 1

if ($unpack) {
  Write-Host "Running conda-unpack: $($unpack.Name)"
  & $unpack.FullName
} else {
  Write-Host "[WARN] conda-unpack not found under Scripts; run conda-unpack manually inside conda_env."
}

Write-Host ""
Write-Host "Done. Run scripts\start_streamlit_console.bat (prefers conda_env)."
