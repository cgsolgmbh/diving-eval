$ErrorActionPreference = 'Stop'

$profilePath = 'C:\Users\ChristianGreuter\Downloads\app-skthun-divingeval-prod.PublishSettings'
[xml]$xml = Get-Content -Raw -Path $profilePath
$msdeployProfile = $xml.publishData.publishProfile | Where-Object { $_.publishMethod -eq 'MSDeploy' } | Select-Object -First 1
if (-not $msdeployProfile) {
    throw 'MSDeploy profile not found'
}

$pair = '{0}:{1}' -f $msdeployProfile.userName, $msdeployProfile.userPWD
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$headers = @{ Authorization = "Basic $basic"; 'If-Match' = '*' }
$baseUrl = 'https://app-skthun-divingeval-prod.scm.azurewebsites.net/api/vfs/site/wwwroot'

$files = @(
    @{ Source = 'C:\Users\ChristianGreuter\OneDrive - Greuter\Dokumente\GitHub\diving-eval-v2\app.py'; Target = 'app.py' }
)

$version = '46c8288-wsfix1'
Set-Content -Path 'C:\Users\ChristianGreuter\OneDrive - Greuter\Dokumente\GitHub\diving-eval-v2\app_version.txt' -Value $version -Encoding UTF8
$files += @{ Source = 'C:\Users\ChristianGreuter\OneDrive - Greuter\Dokumente\GitHub\diving-eval-v2\app_version.txt'; Target = 'app_version.txt' }
Set-Content -Path 'C:\Users\ChristianGreuter\OneDrive - Greuter\Dokumente\GitHub\diving-eval-v2\.app_version' -Value $version -Encoding UTF8
$files += @{ Source = 'C:\Users\ChristianGreuter\OneDrive - Greuter\Dokumente\GitHub\diving-eval-v2\.app_version'; Target = '.app_version' }

foreach ($file in $files) {
    $uri = "$baseUrl/$($file.Target)"
    Invoke-WebRequest -Method Put -Uri $uri -Headers $headers -InFile $file.Source -ContentType 'application/octet-stream' -UseBasicParsing | Out-Null
    Write-Output "UPLOADED $($file.Target)"
}

Write-Output "VERSION=$version"
