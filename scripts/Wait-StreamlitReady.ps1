#Requires -Version 5.1
<#
.SYNOPSIS
  Poll until Streamlit responds on PrimaryPort or nearby ports (Streamlit may shift if busy).
  Prints the winning port as a single line to stdout for .bat to capture.
#>
param(
    [Parameter(Mandatory)][int]$PrimaryPort,
    [Parameter()][int]$MaxWaitSeconds = 150,
    [Parameter()][int]$PortSpan = 12
)

$ErrorActionPreference = 'SilentlyContinue'
$deadline = (Get-Date).AddSeconds($MaxWaitSeconds)
$ports = $PrimaryPort..([Math]::Min($PrimaryPort + $PortSpan, 65535))
$paths = @('/', '/_stcore/health', '/healthz')

while ((Get-Date) -lt $deadline) {
    foreach ($port in $ports) {
        foreach ($p in $paths) {
            try {
                $r = Invoke-WebRequest -UseBasicParsing -Uri ("http://127.0.0.1:{0}{1}" -f $port, $p) -TimeoutSec 2
                if ([int]$r.StatusCode -ge 200 -and [int]$r.StatusCode -lt 400) {
                    Write-Output $port
                    exit 0
                }
            } catch {}
        }
        try {
            $tc = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue
            if ($tc) {
                # 某些机器上首页探测会短暂失败，但端口已监听，避免误报启动失败
                Write-Output $port
                exit 0
            }
        } catch {}
    }
    Start-Sleep -Milliseconds 400
}

exit 1
