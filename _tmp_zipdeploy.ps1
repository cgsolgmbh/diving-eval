$ErrorActionPreference = 'Stop'

$repo = 'c:\Users\ChristianGreuter\OneDrive - Greuter\Dokumente\GitHub\diving-eval-v2'
$profilePath = 'C:\Users\ChristianGreuter\Downloads\app-skthun-divingeval-prod.PublishSettings'

[xml]$xml = Get-Content -Raw -Path $profilePath
$msdeployProfile = $xml.publishData.publishProfile | Where-Object { $_.publishMethod -eq 'MSDeploy' } | Select-Object -First 1
if (-not $msdeployProfile) {
    throw 'MSDeploy profile not found'
}

$pair = '{0}:{1}' -f $msdeployProfile.userName, $msdeployProfile.userPWD
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$headers = @{ Authorization = "Basic $basic" }

$zipPath = Join-Path $repo 'deploy_package.zip'
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Compress-Archive -Path (Join-Path $repo 'deploy_package\*') -DestinationPath $zipPath -Force

$response = Invoke-WebRequest -Method Post -Uri 'https://app-skthun-divingeval-prod.scm.azurewebsites.net/api/zipdeploy' -Headers $headers -InFile $zipPath -ContentType 'application/octet-stream' -UseBasicParsing
$response.Content
