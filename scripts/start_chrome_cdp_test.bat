@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo Chrome CDP launcher (recommended port 9222)
echo ============================================================
echo - UserDataDir: %%TEMP%%\chrome-cdp-verify-fff
echo - First time: log in to Douyin, Compass, Qianchuan in that Chrome window.
echo - Close other Chrome windows first if you want, then press a key.
echo - For your daily Chrome profile: start_chrome_cdp_profile_direct.cmd
echo ============================================================
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launch-ChromeCdp.ps1" -Mode Test -Port 9222
echo.
pause
