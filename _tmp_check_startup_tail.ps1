$ErrorActionPreference = 'Stop'
$profilePath = 'C:\Users\ChristianGreuter\Downloads\app-skthun-divingeval-prod.PublishSettings'
[xml]$xml = Get-Content -Raw -Path $profilePath
$msdeployProfile = $xml.publishData.publishProfile | Where-Object { $_.publishMethod -eq 'MSDeploy' } | Select-Object -First 1
$pair = '{0}:{1}' -f $msdeployProfile.userName, $msdeployProfile.userPWD
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$headers = @{ Authorization = "Basic $basic" }
$content = Invoke-WebRequest -Uri 'https://app-skthun-divingeval-prod.scm.azurewebsites.net/api/vfs/home/site/startup_debug.log' -Headers $headers -UseBasicParsing | Select-Object -ExpandProperty Content
$lines = $content -split "`r?`n"
$tail = $lines | Select-Object -Last 50
$tail -join "`n"
