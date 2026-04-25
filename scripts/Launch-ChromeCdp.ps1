#Requires -Version 5.1
<#
.SYNOPSIS
    Start Chrome with remote debugging for CDP (run_template_trial, etc.).
#>
param(
    [ValidateSet('Test')]
    [string]$Mode = 'Test',
    [int]$Port = 9222
)

$ErrorActionPreference = 'Stop'

function Get-ChromePath {
    foreach ($name in @('CHROME_CDP_EXE', 'CHROME_EXE')) {
        $raw = [Environment]::GetEnvironmentVariable($name, 'Process')
        if (-not $raw) { $raw = [Environment]::GetEnvironmentVariable($name, 'User') }
        if (-not $raw) { $raw = [Environment]::GetEnvironmentVariable($name, 'Machine') }
        if ($raw) {
            $p = $raw.Trim().Trim('"')
            if (Test-Path -LiteralPath $p) { return (Get-Item -LiteralPath $p).FullName }
        }
    }
    $pf86 = ${env:ProgramFiles(x86)}
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $pf86 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) { return (Get-Item -LiteralPath $c).FullName }
    }
    foreach ($hive in @('HKLM:\', 'HKCU:\')) {
        $key = Join-Path $hive 'Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe'
        if (Test-Path -LiteralPath $key) {
            try {
                $v = (Get-ItemProperty -LiteralPath $key -ErrorAction Stop).'(default)'
                if ($v -and (Test-Path -LiteralPath $v)) { return $v.Trim() }
            } catch {}
        }
    }
    return $null
}

$chrome = Get-ChromePath
if (-not $chrome) {
    Write-Host ''
    Write-Host '[ERROR] chrome.exe not found. Install Chrome or set CHROME_CDP_EXE / CHROME_EXE.' -ForegroundColor Red
    Write-Host ''
    exit 1
}

$userData = Join-Path $env:TEMP 'chrome-cdp-verify-fff'
if (-not (Test-Path -LiteralPath $userData)) {
    New-Item -ItemType Directory -Path $userData -Force | Out-Null
}

Write-Host ''
Write-Host '========== Launch Chrome (CDP) =========='
Write-Host "  EXE          : $chrome"
Write-Host "  Port         : $Port"
Write-Host "  UserDataDir  : $userData"
Write-Host '=========================================='
Write-Host ''

$argList = @(
    "--remote-debugging-port=$Port",
    '--remote-debugging-address=127.0.0.1',
    '--remote-allow-origins=*',
    "--user-data-dir=$userData"
)

Start-Process -FilePath $chrome -ArgumentList $argList
Write-Host 'Chrome started. Log in to Douyin / Compass / Qianchuan in that window. Keep it open for Python scripts.'
Write-Host "Check CDP: http://127.0.0.1:$Port/json/version"
Write-Host ''
exit 0
