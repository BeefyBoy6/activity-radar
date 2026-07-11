# Deploy Activity Radar to the Gandi server from this Windows machine.
# Requires working ssh/scp auth (ssh-agent with the key loaded, or you'll
# be prompted for the passphrase a few times).
#
#   .\deploy\deploy.ps1
#
param(
    [string]$Target = "ubuntu@92.243.27.215"
)
$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot   # youth-activity-tracker/

Write-Host "== packaging =="
$staging = Join-Path $env:TEMP "activity-radar-deploy"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Force $staging | Out-Null
robocopy $project $staging /E /XD .venv data __pycache__ .git /XF .env /NFL /NDL /NJH /NJS | Out-Null
$tar = Join-Path $env:TEMP "activity-radar.tar.gz"
tar -czf $tar -C (Split-Path $staging) (Split-Path $staging -Leaf)

Write-Host "== uploading to $Target =="
scp $tar "${Target}:/tmp/activity-radar.tar.gz"

Write-Host "== remote setup =="
ssh $Target "rm -rf /tmp/activity-radar && mkdir -p /tmp/activity-radar && tar -xzf /tmp/activity-radar.tar.gz -C /tmp --transform 's/^activity-radar-deploy/activity-radar/' 2>/dev/null || (cd /tmp && tar -xzf activity-radar.tar.gz && mv activity-radar-deploy activity-radar); bash /tmp/activity-radar/deploy/setup-server.sh"

Write-Host "== done =="
