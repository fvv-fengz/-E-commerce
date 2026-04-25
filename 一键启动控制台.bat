@echo off
setlocal
set "ROOT=%~dp0"
for %%I in ("%ROOT%.") do set "ROOT=%%~fI"
cd /d "%ROOT%" || (
  echo [ERROR] Cannot cd to: %ROOT%
  pause
  exit /b 1
)
if not exist "%ROOT%\scripts\start_streamlit_console.bat" (
  echo [ERROR] Missing: "%ROOT%\scripts\start_streamlit_console.bat"
  pause
  exit /b 1
)
echo.
echo [一键启动] 项目: %ROOT%
echo [一键启动] 正在启动 Streamlit 控制台...
call "%ROOT%\scripts\start_streamlit_console.bat"
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" echo [WARNING] start_streamlit_console.bat exited with %EC%
