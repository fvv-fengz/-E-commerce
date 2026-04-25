@echo off
chcp 65001 >nul
REM ============================================================
REM  双击或在资源管理器地址栏输入本文件名即可打开「已激活 douyin-compass」的 cmd。
REM  若激活失败，请把下面 CONDA_ROOT 改成你机器上 Anaconda 的安装目录
REM  （例如 D:\ProgramData\Anaconda3 或 C:\Users\xxx\anaconda3）
REM ============================================================

set "CONDA_ROOT=D:\ProgramData\Anaconda3"

if not exist "%CONDA_ROOT%\Scripts\activate.bat" (
    echo [ERROR] 找不到 activate.bat：%CONDA_ROOT%
    echo 请右键编辑本文件，修改 CONDA_ROOT= 为你的 Anaconda 路径。
    pause
    exit /b 1
)

call "%CONDA_ROOT%\Scripts\activate.bat" douyin-compass
cd /d "%~dp0.."
echo.
echo 已激活环境：douyin-compass
echo 当前目录：%CD%
echo.
cmd /k
