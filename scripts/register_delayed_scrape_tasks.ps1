# 注册两个「仅执行一次」的计划任务：T+6h 跑拼多多，T+8h 跑抖店 v1。
# 不依赖长时间开着的 CMD；关机/休眠则到点不会执行（需开机且用户已登录，脚本任务见下方说明）。
# 用法（项目根目录，PowerShell）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\register_delayed_scrape_tasks.ps1
# 查看任务： schtasks /Query /TN "fff-dianshang-*" /V
# 删除示例： schtasks /Delete /TN "任务全名" /F

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PddCmd = Join-Path $Root "scripts\_delayed_run_pdd.cmd"
$DyCmd = Join-Path $Root "scripts\_delayed_run_douyin.cmd"

foreach ($f in @($PddCmd, $DyCmd)) {
    if (-not (Test-Path $f)) { throw "缺少: $f" }
}

$tPdd = (Get-Date).AddHours(6)
$tDy = (Get-Date).AddHours(8)
$stamp = (Get-Date).ToString("yyyyMMdd_HHmmss")

$namePdd = "fff-dianshang-pdd-6h-$stamp"
$nameDy = "fff-dianshang-dy-8h-$stamp"

# schtasks /SD：本机帮助文档为 yyyy/mm/dd
$sdPdd = $tPdd.ToString("yyyy/MM/dd")
$stPdd = $tPdd.ToString("HH:mm")
$sdDy = $tDy.ToString("yyyy/MM/dd")
$stDy = $tDy.ToString("HH:mm")

# /IT = 仅当用户已登录时运行（适合连本机 Chrome/CDP）
# /RL HIGHEST 避免部分环境权限不足（可按需改为 LIMITED）
$trPdd = "`"$PddCmd`""
$trDy = "`"$DyCmd`""

Write-Host "项目: $Root"
Write-Host "拼多多: $namePdd  计划 $($tPdd.ToString('yyyy-MM-dd HH:mm'))"
Write-Host "抖店v1: $nameDy  计划 $($tDy.ToString('yyyy-MM-dd HH:mm'))"
Write-Host ""

& schtasks /Create /TN $namePdd /TR $trPdd /SC ONCE /SD $sdPdd /ST $stPdd /F /IT /RL HIGHEST | Out-Host
& schtasks /Create /TN $nameDy /TR $trDy /SC ONCE /SD $sdDy /ST $stDy /F /IT /RL HIGHEST | Out-Host

Write-Host ""
Write-Host "已注册。日志: $Root\log\delayed_run_pdd.log 与 delayed_run_douyin.log"
Write-Host "删除任务: schtasks /Delete /TN `"$namePdd`" /F"
Write-Host "          schtasks /Delete /TN `"$nameDy`" /F"
