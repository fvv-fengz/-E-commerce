<#
.SYNOPSIS
  在 ProjectRoot\conda_env 下查找 python.exe（标准 Scripts、根目录、或一层子目录）。
  找到则向 stdout 打印完整路径（单行）；找不到则无输出。供 .bat for /f 使用。
#>
param(
  [string]$ProjectRoot = ""
)

if (-not $ProjectRoot) {
  $ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
}
else {
  $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
}

$base = Join-Path $ProjectRoot "conda_env"
if (-not (Test-Path -LiteralPath $base)) {
  exit 0
}

$candidates = @(
  (Join-Path $base "Scripts\python.exe"),
  (Join-Path $base "python.exe")
)
foreach ($c in $candidates) {
  if (Test-Path -LiteralPath $c) {
    Write-Output $c
    exit 0
  }
}

Get-ChildItem -Path $base -Directory -ErrorAction SilentlyContinue | ForEach-Object {
  $p = Join-Path $_.FullName "Scripts\python.exe"
  if (Test-Path -LiteralPath $p) {
    Write-Output $p
    exit 0
  }
}

exit 0
