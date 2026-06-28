$ErrorActionPreference = 'Stop'
$profilePath = 'C:\Users\ChristianGreuter\Downloads\app-skthun-divingeval-prod.PublishSettings'
[xml]$xml = Get-Content -Raw -Path $profilePath
$msdeployProfile = $xml.publishData.publishProfile | Where-Object { $_.publishMethod -eq 'MSDeploy' } | Select-Object -First 1
$pair = '{0}:{1}' -f $msdeployProfile.userName, $msdeployProfile.userPWD
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$headers = @{ Authorization = "Basic $basic" }
$bytes = (Invoke-WebRequest -Uri 'https://app-skthun-divingeval-prod.scm.azurewebsites.net/api/vfs/site/wwwroot/app.py' -Headers $headers -UseBasicParsing | Select-Object -ExpandProperty Content)
$content = [Text.Encoding]::UTF8.GetString($bytes)
Write-Output ("length=" + $content.Length)
Write-Output ("has_session_reset=" + ($content -match 'reset_session_state_on_version_change'))
Write-Output ("has_year_selectbox=" + ($content -match 'selectbox\("Jahr"'))
Write-Output ("has_year_multiselect=" + ($content -match 'multiselect\("Jahr"'))
Write-Output ("has_verletzt_chart=" + ($content -match 'Verletzt' -and $content -match 'Verteilung Talentcard'))

$lines = $content -split "`r?`n"
for ($i = 0; $i -lt $lines.Length; $i++) {
	if ($lines[$i] -match 'selectbox\("Jahr"' -or $lines[$i] -match 'multiselect\("Jahr"' -or $lines[$i] -match 'Full PISTE Results SOC' -or $lines[$i] -match 'Verteilung Talentcard') {
		Write-Output (("{0}: {1}" -f ($i + 1), $lines[$i]))
	}
}
