@echo off
REM 售后列表导出单测：需先启动带 9222 的 Chrome 并登录抖店
cd /d "%~dp0.."
python scripts\run_aftersale_export_test.py %*
exit /b %ERRORLEVEL%
