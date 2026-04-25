@echo off
setlocal ENABLEDELAYEDEXPANSION
REM rev-20260422c PS full path + no %%VAR%% inside IF^(^) blocks ^(fixes empty PYEXE / broken PATH^)

REM Double-click often has minimal PATH ^(no powershell / no py^)
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"

title fff2 Streamlit launcher
echo.
echo [launcher] Starting from "%~dp0"

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
cd /d "%ROOT%" || (
  echo [ERROR] Cannot cd to project root.
  pause
  exit /b 1
)
echo [launcher] ROOT=%ROOT%

set "CONDA_ENV=douyin-compass"
if defined PICKER_CONDA_ENV set "CONDA_ENV=!PICKER_CONDA_ENV!"

set "VENV=%ROOT%\.venv"
set "PORT=8502"
if defined STREAMLIT_CONSOLE_PORT set "PORT=!STREAMLIT_CONSOLE_PORT!"
if defined PICKER_STREAMLIT_PORT set "PORT=!PICKER_STREAMLIT_PORT!"
set "CDP_PORT=9222"

set "CONDA_PY="
if defined PICKER_PYTHON if exist "!PICKER_PYTHON!" set "CONDA_PY=!PICKER_PYTHON!"
if defined CONDA_PY goto conda_resolve_done

set "CONDA_PY=%ROOT%\conda_env\Scripts\python.exe"
if exist "!CONDA_PY!" goto conda_resolve_done
set "CONDA_PY=%ROOT%\conda_env\python.exe"
if exist "!CONDA_PY!" goto conda_resolve_done

for /f "usebackq delims=" %%P in (`!PS! -NoProfile -ExecutionPolicy Bypass -File "%~dp0resolve_conda_python.ps1"`) do set "CONDA_PY=%%P"
if exist "!CONDA_PY!" goto conda_resolve_done

if exist "%ProgramData%\Anaconda3\envs\!CONDA_ENV!\python.exe" set "CONDA_PY=%ProgramData%\Anaconda3\envs\!CONDA_ENV!\python.exe" & goto conda_resolve_done
if exist "D:\ProgramData\Anaconda3\envs\!CONDA_ENV!\python.exe" set "CONDA_PY=D:\ProgramData\Anaconda3\envs\!CONDA_ENV!\python.exe" & goto conda_resolve_done
if exist "%UserProfile%\Anaconda3\envs\!CONDA_ENV!\python.exe" set "CONDA_PY=%UserProfile%\Anaconda3\envs\!CONDA_ENV!\python.exe" & goto conda_resolve_done
if exist "%UserProfile%\Miniconda3\envs\!CONDA_ENV!\python.exe" set "CONDA_PY=%UserProfile%\Miniconda3\envs\!CONDA_ENV!\python.exe" & goto conda_resolve_done
if exist "%LocalAppData%\miniconda3\envs\!CONDA_ENV!\python.exe" set "CONDA_PY=%LocalAppData%\miniconda3\envs\!CONDA_ENV!\python.exe" & goto conda_resolve_done

:conda_resolve_done

REM --- conda branch: NO parenthesis-block so %% expansion is not frozen at parse time ---
if not defined CONDA_PY goto use_venv
if not exist "!CONDA_PY!" goto use_venv

for %%I in ("!CONDA_PY!\..") do set "CONDASCRIPTS=%%~fI"
for %%I in ("!CONDA_PY!\..\..") do set "CONDAROOT=%%~fI"
set "PYEXE=!CONDA_PY!"
set "PLAYWRIGHT_BROWSERS_PATH=!CONDAROOT!\playwright-browsers"
set "PATH=!CONDASCRIPTS!;%PATH%"
echo [launcher] conda Python: "!PYEXE!"
goto run_streamlit

:use_venv
if not exist "!VENV!\Scripts\python.exe" (
  echo [INFO] Creating .venv ^(need Python 3.10+^) ...
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3.12 -m venv "!VENV!" 2>nul
    if not exist "!VENV!\Scripts\python.exe" py -3.11 -m venv "!VENV!" 2>nul
    if not exist "!VENV!\Scripts\python.exe" py -3.10 -m venv "!VENV!" 2>nul
    if not exist "!VENV!\Scripts\python.exe" (
      echo [ERROR] Need py -3.10 / 3.11 / 3.12 or conda env.
      goto :err
    )
  ) else (
    where python >nul 2>&1
    if not errorlevel 1 (
      python -m venv "!VENV!" || goto :err
    ) else (
      echo [ERROR] No conda python found and no py/python on PATH.
      goto :err
    )
  )
)

if not exist "!VENV!\Scripts\python.exe" goto :err
call "!VENV!\Scripts\activate.bat"

python -c "import sys; sys.exit(0 if sys.hexversion>=0x030A0000 else 1)" 2>nul
if errorlevel 1 (
  echo [ERROR] .venv Python is below 3.10. Delete folder "!VENV!" and retry.
  goto :err
)

python -c "import streamlit" 2>nul
if errorlevel 1 (
  echo [INFO] pip install from requirements.txt ...
  python -m pip install --upgrade pip || goto :err
  pip install -r "!ROOT!\requirements.txt" || goto :err
  python -m playwright install chromium || goto :err
)

set "PYEXE=python"

:run_streamlit
if /i "!PYEXE!"=="python" (
  for /f "delims=" %%W in ('where python 2^>nul') do (
    set "PYEXE=%%W"
    goto _after_where
  )
  echo [ERROR] where python failed. Set PICKER_PYTHON to full path of python.exe
  goto :err
)
:_after_where
if not exist "!PYEXE!" (
  echo [ERROR] Missing: "!PYEXE!"
  goto :err
)

echo [launcher] Python: "!PYEXE!"
echo [ENTRY] CDP http://127.0.0.1:!CDP_PORT!/ ...
"%PS%" -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:!CDP_PORT!/json/version' -TimeoutSec 2; exit ([int]($r.StatusCode -ne 200)) } catch { exit 1 }"
if errorlevel 1 (
  echo [ENTRY] Launch Chrome CDP...
  "%PS%" -NoProfile -ExecutionPolicy Bypass -File "!ROOT!\scripts\Launch-ChromeCdp.ps1" -Mode Test -Port !CDP_PORT!
  ping 127.0.0.1 -n 4 >nul
) else (
  echo [ENTRY] CDP ready on !CDP_PORT!.
)

echo Starting Streamlit port !PORT!
echo Browser URL: http://127.0.0.1:!PORT!/
set "STREAMLIT_WINDOW_HIDDEN=1"
if defined PICKER_STREAMLIT_WINDOW_HIDDEN set "STREAMLIT_WINDOW_HIDDEN=!PICKER_STREAMLIT_WINDOW_HIDDEN!"
if /i "!STREAMLIT_WINDOW_HIDDEN!"=="0" (
  "%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launch-StreamlitConsole.ps1" -PythonExe "!PYEXE!" -ProjectRoot "!ROOT!" -Port !PORT!
) else (
  "%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launch-StreamlitConsole.ps1" -PythonExe "!PYEXE!" -ProjectRoot "!ROOT!" -Port !PORT! -Hidden
)
if errorlevel 1 (
  echo [ERROR] Launch-StreamlitConsole.ps1 failed.
  goto :err
)

set "READY_TIMEOUT=150"
if defined STREAMLIT_READY_TIMEOUT_SEC set "READY_TIMEOUT=!STREAMLIT_READY_TIMEOUT_SEC!"
echo [launcher] Waiting for HTTP ^(max !READY_TIMEOUT!s^)...
set "READY_PORT="
for /f "delims=" %%U in ('!PS! -NoProfile -ExecutionPolicy Bypass -File "%~dp0Wait-StreamlitReady.ps1" -PrimaryPort !PORT! -MaxWaitSeconds !READY_TIMEOUT!') do set "READY_PORT=%%U"
if defined READY_PORT (
  echo [launcher] OK port !READY_PORT!
  "%PS%" -NoProfile -ExecutionPolicy Bypass -Command "Start-Process ('http://127.0.0.1:' + !READY_PORT! + '/')"
) else (
  echo [WARN] No HTTP in !READY_TIMEOUT!s; opening http://127.0.0.1:!PORT!/
  "%PS%" -NoProfile -ExecutionPolicy Bypass -Command "Start-Process 'http://127.0.0.1:!PORT!/'"
)

echo Done. Keep Streamlit window open.
pause
goto :eof

:err
echo [ERROR] Startup failed.
pause
exit /b 1
