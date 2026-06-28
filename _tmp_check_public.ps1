$ErrorActionPreference = 'Stop'
try {
    $resp = Invoke-WebRequest -Uri 'https://app-skthun-divingeval-prod.azurewebsites.net/' -UseBasicParsing -TimeoutSec 20
    Write-Output ("status=" + [int]$resp.StatusCode)
    Write-Output ("length=" + $resp.Content.Length)
} catch {
    Write-Output ("public_error=" + $_.Exception.Message)
}
