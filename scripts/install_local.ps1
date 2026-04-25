param(
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
  [switch]$CreateDesktopShortcut = $true,
  [switch]$RegisterDailyTask = $false,
  [string]$TaskTime = "09:00"
)

$ErrorActionPreference = "Stop"

Write-Host "[1/5] 项目目录: $ProjectRoot"
Set-Location $ProjectRoot

$venvPy = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  Write-Host "[2/5] 创建 .venv ..."
  py -3 -m venv ".venv"
}

Write-Host "[3/5] 安装依赖 ..."
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r (Join-Path $ProjectRoot "requirements.txt")

Write-Host "[4/5] Playwright 浏览器（chromium，供脚本依赖；体积较大）..."
& $venvPy -m playwright install chromium

$starter = Join-Path $ProjectRoot "scripts\start_streamlit_console.bat"
if (-not (Test-Path $starter)) {
  throw "启动脚本不存在: $starter"
}

if ($CreateDesktopShortcut) {
  Write-Host "[5/5] 创建桌面快捷方式 ..."
  $desktop = [Environment]::GetFolderPath("Desktop")
  $lnk = Join-Path $desktop "电商采集控制台.lnk"
  $ws = New-Object -ComObject WScript.Shell
  $shortcut = $ws.CreateShortcut($lnk)
  $shortcut.TargetPath = $starter
  $shortcut.WorkingDirectory = $ProjectRoot
  $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
  $shortcut.Description = "启动电商采集控制台（Streamlit）"
  $shortcut.Save()
  Write-Host "已创建: $lnk"
}

if ($RegisterDailyTask) {
  Write-Host "[可选] 注册每日定时任务 ..."
  $taskName = "电商采集控制台_每日启动"
  $action = New-ScheduledTaskAction -Execute $starter
  $trigger = New-ScheduledTaskTrigger -Daily -At $TaskTime
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Description "每日启动电商采集控制台" -Force | Out-Null
  Write-Host "已注册任务: $taskName ($TaskTime)"
}

Write-Host "安装完成。若出现影响使用的报错，请联系管理员维护。"
