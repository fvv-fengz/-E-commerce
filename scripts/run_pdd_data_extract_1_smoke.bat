@echo off
chcp 65001 >nul
cd /d "%~dp0\.."

echo ============================================================
echo 拼多多数据提取_1（smoke 冒烟）
echo ============================================================
echo 模板: doc\scrape-template-pdd-拼多多数据提取_1-smoke.json
echo.

python scripts\run_template_trial.py ^
  --template doc\scrape-template-pdd-拼多多数据提取_1-smoke.json ^
  --selector-hints-file log\selector_hints_pdd_data_extract_1.json ^
  --field-locator-timeout-ms 5000

echo.
pause
