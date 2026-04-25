# 延迟 3 小时后执行拼多多默认模板试运行。
# 在项目根目录执行：
#   .\scripts\delay_run_pdd_extract_3h.ps1
# 后台排队（另开窗口，本终端立即返回）：
#   .\scripts\delay_run_pdd_extract_3h.ps1 -Detach
#
param([switch]$Detach)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DelaySeconds = 3 * 60 * 60
$Tmpl = "doc/scrape-template-pdd-拼多多数据提取_1.json"

if ($Detach) {
    $cmd = "Set-Location -LiteralPath '$Root'; " +
        "Write-Host '[delay 3h] 等待 $DelaySeconds 秒…' -ForegroundColor Cyan; " +
        "Start-Sleep -Seconds $DelaySeconds; " +
        "Write-Host '[delay 3h] 执行 run_template_trial…' -ForegroundColor Cyan; " +
        "python .\scripts\run_template_trial.py --template `"$Tmpl`"; " +
        "Write-Host ('退出码: ' + `$LASTEXITCODE) -ForegroundColor Cyan; pause"
    Start-Process -FilePath "powershell.exe" `
        -WorkingDirectory $Root `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-Command", $cmd
    Write-Host "已在新窗口排队：约 3 小时后运行（可加 --cdp 等请自行改脚本或命令）。" -ForegroundColor Green
    exit 0
}

Set-Location -LiteralPath $Root
Write-Host "[delay 3h] 等待 $DelaySeconds 秒…" -ForegroundColor Cyan
Start-Sleep -Seconds $DelaySeconds
Write-Host "[delay 3h] 执行 run_template_trial…" -ForegroundColor Cyan
python .\scripts\run_template_trial.py --template $Tmpl
exit $LASTEXITCODE
