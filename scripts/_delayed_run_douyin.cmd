@echo off
chcp 65001 >nul
set "ROOT=%~dp0.."
cd /d "%ROOT%"
set "LOG=%ROOT%\log"
if not exist "%LOG%" mkdir "%LOG%"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if exist "%PY%" goto RUN
set "PY=python"
:RUN
echo [%date% %time%] start douyin >> "%LOG%\delayed_run_douyin.log"
"%PY%" "%ROOT%\scripts\run_template_trial.py" --template "doc\scrape-template-jinritemai-v1.json" >> "%LOG%\delayed_run_douyin.log" 2>&1
echo [%date% %time%] exit %ERRORLEVEL% >> "%LOG%\delayed_run_douyin.log"
