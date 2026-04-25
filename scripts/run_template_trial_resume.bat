@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

cd /d "%~dp0\.."

REM ---------- 断点文件（可改）----------
set "CHECKPOINT=log\template_trial_checkpoint.json"
REM 续写同一 Excel：先 set TEMPLATE_TRIAL_EXCEL_OUT=上次 .xlsx 完整路径（须已存在），再运行本 bat

REM ---------- Conda 环境名：可用环境变量覆盖 ----------
set "CONDA_ENV=douyin-compass"
if defined PICKER_CONDA_ENV set "CONDA_ENV=!PICKER_CONDA_ENV!"
if defined TEMPLATE_TRIAL_CONDA_ENV set "CONDA_ENV=!TEMPLATE_TRIAL_CONDA_ENV!"

echo ============================================
echo 从断点继续运行（--checkpoint + --resume）
echo 断点文件: !CD!\%CHECKPOINT%
echo 将跳过其中已完成的（店铺 x 页面）。
echo Conda 环境: !CONDA_ENV! （改环境请设 PICKER_CONDA_ENV 或 TEMPLATE_TRIAL_CONDA_ENV，或设 PICKER_PYTHON）
echo 请先启动带远程调试的 Chrome 并已登录抖店（如 scripts\start_chrome_cdp_test.bat）。
echo 附加参数会传给脚本，例如: --cdp http://127.0.0.1:9222
echo 续写已有 Excel: set TEMPLATE_TRIAL_EXCEL_OUT=output\template_trial_某时间戳.xlsx
echo ============================================
pause

REM ---------- 解析 Python：优先 PICKER_PYTHON，再常见 Anaconda 路径 ----------
set "PY_EXE="
if defined PICKER_PYTHON if exist "!PICKER_PYTHON!" set "PY_EXE=!PICKER_PYTHON!"
if defined TEMPLATE_TRIAL_PYTHON if not defined PY_EXE if exist "!TEMPLATE_TRIAL_PYTHON!" set "PY_EXE=!TEMPLATE_TRIAL_PYTHON!"

if not defined PY_EXE if exist "%ProgramData%\Anaconda3\envs\!CONDA_ENV!\python.exe" (
  set "PY_EXE=%ProgramData%\Anaconda3\envs\!CONDA_ENV!\python.exe"
)
if not defined PY_EXE if exist "D:\ProgramData\Anaconda3\envs\!CONDA_ENV!\python.exe" (
  set "PY_EXE=D:\ProgramData\Anaconda3\envs\!CONDA_ENV!\python.exe"
)
if not defined PY_EXE if exist "%UserProfile%\Anaconda3\envs\!CONDA_ENV!\python.exe" (
  set "PY_EXE=%UserProfile%\Anaconda3\envs\!CONDA_ENV!\python.exe"
)
if not defined PY_EXE if exist "%UserProfile%\Miniconda3\envs\!CONDA_ENV!\python.exe" (
  set "PY_EXE=%UserProfile%\Miniconda3\envs\!CONDA_ENV!\python.exe"
)
if not defined PY_EXE if exist "%LocalAppData%\miniconda3\envs\!CONDA_ENV!\python.exe" (
  set "PY_EXE=%LocalAppData%\miniconda3\envs\!CONDA_ENV!\python.exe"
)

if defined PY_EXE (
  echo 使用 Python: !PY_EXE!
  if defined TEMPLATE_TRIAL_EXCEL_OUT (
    "!PY_EXE!" scripts\run_template_trial.py --checkpoint "%CHECKPOINT%" --resume --excel-out "!TEMPLATE_TRIAL_EXCEL_OUT!" %*
  ) else (
    "!PY_EXE!" scripts\run_template_trial.py --checkpoint "%CHECKPOINT%" --resume %*
  )
  set "EXITCODE=!ERRORLEVEL!"
  goto :finish
)

REM ---------- 尝试 conda activate.bat ----------
for %%A in (
  "%ProgramData%\Anaconda3\Scripts\activate.bat"
  "D:\ProgramData\Anaconda3\Scripts\activate.bat"
  "%UserProfile%\Anaconda3\Scripts\activate.bat"
  "%UserProfile%\Miniconda3\Scripts\activate.bat"
) do (
  if exist %%~A (
    echo 尝试通过 activate 激活环境: !CONDA_ENV!
    call %%~A !CONDA_ENV!
    if defined TEMPLATE_TRIAL_EXCEL_OUT (
      python scripts\run_template_trial.py --checkpoint "%CHECKPOINT%" --resume --excel-out "!TEMPLATE_TRIAL_EXCEL_OUT!" %*
    ) else (
      python scripts\run_template_trial.py --checkpoint "%CHECKPOINT%" --resume %*
    )
    set "EXITCODE=!ERRORLEVEL!"
    goto :finish
  )
)

REM ---------- PATH 上的 python（需 3.8+，供 playwright）----------
echo 未在常见路径找到 !CONDA_ENV! 的 python.exe，尝试使用 PATH 中的 python …
where python >nul 2>&1
if errorlevel 1 (
  echo 未找到 python 命令。
  echo.
  echo 请设置环境变量 PICKER_PYTHON 为已安装 playwright 的 python.exe 完整路径，例如：
  echo   D:\ProgramData\Anaconda3\envs\!CONDA_ENV!\python.exe
  set "EXITCODE=9009"
  goto :finish_err
)
python -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 8) else 1)" 2>nul
if errorlevel 1 (
  echo [错误] 当前 PATH 里的 Python 版本过低（需要 3.8 及以上以运行 Playwright）。
  set "EXITCODE=1"
  goto :finish_err
)
if defined TEMPLATE_TRIAL_EXCEL_OUT (
  python scripts\run_template_trial.py --checkpoint "%CHECKPOINT%" --resume --excel-out "!TEMPLATE_TRIAL_EXCEL_OUT!" %*
) else (
  python scripts\run_template_trial.py --checkpoint "%CHECKPOINT%" --resume %*
)
set "EXITCODE=%ERRORLEVEL%"
goto :finish

:finish_err
goto :finish

:finish
if not "!EXITCODE!"=="0" (
  echo.
  echo ---------- 排错提示 ----------
  echo 选项 A - 设置用户环境变量 PICKER_PYTHON 指向已 pip install playwright 的 python.exe
  echo 选项 B - 设置 PICKER_CONDA_ENV 为你的环境名（默认本脚本为 douyin-compass）
  echo 选项 C - 打开 Anaconda Prompt，执行 conda activate 你的环境 后进入项目目录再运行:
  echo         python scripts\run_template_trial.py --checkpoint log\template_trial_checkpoint.json --resume
  echo.
)
if not "!EXITCODE!"=="0" echo 退出码: !EXITCODE!
pause
exit /b !EXITCODE!
