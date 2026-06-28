$ErrorActionPreference = 'Stop'

$profilePath = 'C:\Users\ChristianGreuter\Downloads\app-skthun-divingeval-prod.PublishSettings'
[xml]$xml = Get-Content -Raw -Path $profilePath
$msdeployProfile = $xml.publishData.publishProfile | Where-Object { $_.publishMethod -eq 'MSDeploy' } | Select-Object -First 1
if (-not $msdeployProfile) { throw 'MSDeploy profile not found' }

$pair = '{0}:{1}' -f $msdeployProfile.userName, $msdeployProfile.userPWD
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$headers = @{ Authorization = "Basic $basic"; 'Content-Type' = 'application/json' }
$command = 'bash -lc "pkill -f /home/site/wwwroot/app.py || true; pkill -f streamlit || true; ps -ef | grep -E ''streamlit|app.py'' | grep -v grep || true"'
$body = @{ command = $command } | ConvertTo-Json
Invoke-WebRequest -Method Post -Uri 'https://app-skthun-divingeval-prod.scm.azurewebsites.net/api/command' -Headers $headers -Body $body -UseBasicParsing | Select-Object -ExpandProperty Content
