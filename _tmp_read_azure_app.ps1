$ErrorActionPreference='Stop'
$profilePath='C:\Users\ChristianGreuter\Downloads\app-skthun-divingeval-prod.PublishSettings'
[xml]$xml=Get-Content -Raw -Path $profilePath
$msdeployProfile=$xml.publishData.publishProfile | Where-Object { $_.publishMethod -eq 'MSDeploy' } | Select-Object -First 1
$pair=('{0}:{1}' -f $msdeployProfile.userName,$msdeployProfile.userPWD)
$basic=[Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$headers=@{Authorization="Basic $basic"}
$bytes = (Invoke-WebRequest -Uri 'https://app-skthun-divingeval-prod.scm.azurewebsites.net/api/vfs/site/wwwroot/app.py' -Headers $headers -UseBasicParsing).Content
$content = [Text.Encoding]::UTF8.GetString($bytes)
$content | Select-String -Pattern 'Verletzt|talentcard_values|soc_df\["injured"\]' -Context 3,3
