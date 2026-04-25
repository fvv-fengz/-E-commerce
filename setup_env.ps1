# Run in PowerShell from project folder after: conda activate douyin-compass
$ErrorActionPreference = "Stop"
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) {
    Write-Host "Activate env first: conda activate douyin-compass"
    exit 1
}
Set-Location $PSScriptRoot
python -m pip install -r requirements.txt
# Optional: only needed if you use bundled Chromium fallback:
# python -m playwright install chromium
Write-Host "Done. Install Google Chrome; run playwright install chromium only if fallback is used."
