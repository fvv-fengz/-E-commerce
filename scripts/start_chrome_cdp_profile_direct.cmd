@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM Pure cmd: starts chrome.exe with CDP flags. NOT default browser.
REM If you set CHROME_CDP_EXE wrongly, open cmd and run:  set CHROME_CDP_EXE=

REM --- Resolve CHROME path ---
if defined CHROME_CDP_EXE (
    set "_TRY=!CHROME_CDP_EXE!"
    REM strip accidental surrounding quotes
    set "_TRY=!_TRY:"=!"
    if not exist "!_TRY!" (
        echo [ERROR] CHROME_CDP_EXE points to a missing file:
        echo   "!_TRY!"
        echo Must be full path to chrome.exe ^(not a folder^). Clear bad value:  set CHROME_CDP_EXE=
        exit /b 1
    )
    set "CHROME=!_TRY!"
) else (
    set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not exist "!CHROME!" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    REM Per-user install (common on some PCs)
    if not exist "!CHROME!" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
    if not exist "!CHROME!" (
        for /f "tokens=2*" %%A in ('reg query "HKLM\Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe" /ve 2^>nul') do set "CHROME=%%B"
    )
    if not exist "!CHROME!" (
        for /f "tokens=2*" %%A in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe" /ve 2^>nul') do set "CHROME=%%B"
    )
    if not exist "!CHROME!" (
        echo [ERROR] chrome.exe not found. Checked:
        echo   - "C:\Program Files\Google\Chrome\Application\chrome.exe"
        echo   - "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        echo   - "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
        echo   - Registry App Paths\chrome.exe
        echo.
        echo Fix: install Google Chrome, OR set full path before this script:
        echo   set "CHROME_CDP_EXE=C:\YourPath\chrome.exe"
        echo   call "%~f0"
        exit /b 1
    )
)

if not defined PROFN set "PROFN=Default"
set "UD=%LOCALAPPDATA%\Google\Chrome\User Data"
if not defined CDP_PORT set "CDP_PORT=9222"

echo.
echo ========== Direct Chrome launch ==========
echo EXE: "!CHROME!"
echo Port: !CDP_PORT!
echo UserDataDir: "%UD%"
echo Profile: !PROFN!
echo ==========================================
echo.

start "ChromeCDP" "!CHROME!" --remote-debugging-port=!CDP_PORT! --remote-debugging-address=127.0.0.1 "--remote-allow-origins=*" --user-data-dir="%UD%" --profile-directory="!PROFN!"

echo Started. Wait a few seconds, then in THIS Chrome open:
echo   http://127.0.0.1:!CDP_PORT!/json/version
echo Or run diagnose_cdp.bat
endlocal
exit /b 0
