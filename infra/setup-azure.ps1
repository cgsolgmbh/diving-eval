# =============================================================================
# Azure Infrastructure Setup — diving-eval v2  (PowerShell version)
# Organisation : SKThun (skthun.ch)
# Tenant ID    : d64867f2-5502-4dd1-81bd-5d0d663af5f3
#
# Usage:
#   .\infra\setup-azure.ps1
#   .\infra\setup-azure.ps1 -SqlAdminPassword "YourStr0ng!Pw"
# =============================================================================

param(
    [string]$SqlAdminPassword = ""
)

# "Continue" so az CLI warnings on stderr don't abort the script
$ErrorActionPreference = "Continue"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
$TenantId       = "d64867f2-5502-4dd1-81bd-5d0d663af5f3"
$Location       = "switzerlandnorth"
$LocationShort  = "chn"
$AppLocation    = "westeurope"     # Free F1 not available in switzerlandnorth
$AppLocationShort = "weu"

$Workload       = "divingeval"
$Org            = "skthun"
$Env            = "prod"

$RgName         = "rg-$Workload-$Env-$LocationShort"
$SqlServerName  = "sql-$Org-$Workload-$Env"
$SqlDbName      = "sqldb-$Workload-$Env"
$SqlAdminUser   = "sqladmin"
$KeyVaultName   = "kv-$Org-deval-$Env"
$AppPlanName    = "asp-$Workload-$Env-$AppLocationShort"
$AppName        = "app-$Org-$Workload-$Env"

function Write-Info    ($msg) { Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Write-Success ($msg) { Write-Host "[OK]    $msg" -ForegroundColor Green }
function Write-Warn    ($msg) { Write-Host "[WARN]  $msg" -ForegroundColor Yellow }

# ---------------------------------------------------------------------------
# 0. Login & subscription
# ---------------------------------------------------------------------------
Write-Info "Checking Azure login..."
try {
    $currentTenant = az account show --query tenantId -o tsv 2>$null
} catch { $currentTenant = "" }

if ($currentTenant -ne $TenantId) {
    Write-Warn "Not logged in to correct tenant. Running az login..."
    az login --tenant $TenantId | Out-Null
}

$SubscriptionId = az account list `
    --query "[?tenantId=='$TenantId'].id" -o tsv |
    Select-Object -First 1

if (-not $SubscriptionId) {
    throw "No subscription found in tenant $TenantId. Create one in Azure Portal first."
}
az account set --subscription $SubscriptionId | Out-Null
Write-Success "Subscription: $SubscriptionId"

# Prompt for SQL password if not provided
if (-not $SqlAdminPassword) {
    $SecurePassword = Read-Host "SQL admin password (min 12 chars, upper+lower+digit+special)" -AsSecureString
    $SqlAdminPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword))
}

# ---------------------------------------------------------------------------
# 1. Register required resource providers (needed on new subscriptions)
# ---------------------------------------------------------------------------
Write-Info "Registering required resource providers..."
@("Microsoft.KeyVault", "Microsoft.Sql", "Microsoft.Web") | ForEach-Object {
    $state = az provider show --namespace $_ --query "registrationState" -o tsv 2>$null
    if ($state -ne "Registered") {
        Write-Info "  Registering $_ ..."
        az provider register --namespace $_ --wait --output none
        Write-Success "  $_ registered"
    } else {
        Write-Info "  $_ already registered"
    }
}

# ---------------------------------------------------------------------------
# 2. Resource Group
# ---------------------------------------------------------------------------
Write-Info "Creating resource group: $RgName..."
az group create `
    --name $RgName `
    --location $Location `
    --tags workload=$Workload environment=$Env organisation=$Org `
    --output none
Write-Success "Resource group: $RgName"

# Helper: run az command ignoring errors (for existence checks)
function Az-Exists { $ErrorActionPreference = "Continue"; $r = (& az @args 2>$null); $ErrorActionPreference = "Stop"; return $r }

# ---------------------------------------------------------------------------
# 3. Key Vault
# ---------------------------------------------------------------------------
$kvExists = Az-Exists keyvault show --name $KeyVaultName --resource-group $RgName --query name -o tsv
if ($kvExists) {
    Write-Info "Key Vault already exists: $KeyVaultName (skipping)"
} else {
    Write-Info "Creating Key Vault: $KeyVaultName..."
    az keyvault create `
        --name $KeyVaultName `
        --resource-group $RgName `
        --location $Location `
        --sku standard `
        --enable-rbac-authorization true `
        --tags workload=$Workload environment=$Env `
        --output none
    Write-Success "Key Vault: $KeyVaultName"
}

# ---------------------------------------------------------------------------
# 4. Azure SQL Server
# ---------------------------------------------------------------------------
$sqlExists = Az-Exists sql server show --name $SqlServerName --resource-group $RgName --query name -o tsv
if ($sqlExists) {
    Write-Info "SQL Server already exists: $SqlServerName (skipping)"
} else {
    Write-Info "Creating SQL Server: $SqlServerName..."
    az sql server create `
        --name $SqlServerName `
        --resource-group $RgName `
        --location $Location `
        --admin-user $SqlAdminUser `
        --admin-password $SqlAdminPassword `
        --output none
    Write-Success "SQL Server: $SqlServerName.database.windows.net"
}

# Firewall: allow Azure services (upsert — safe to run multiple times)
az sql server firewall-rule create `
    --name "AllowAzureServices" `
    --resource-group $RgName `
    --server $SqlServerName `
    --start-ip-address 0.0.0.0 `
    --end-ip-address 0.0.0.0 `
    --output none

# Firewall: allow developer's current IP
$MyIp = (Invoke-RestMethod -Uri "https://api.ipify.org").Trim()
Write-Info "Adding firewall rule for developer IP: $MyIp..."
az sql server firewall-rule create `
    --name "AllowDeveloperIP" `
    --resource-group $RgName `
    --server $SqlServerName `
    --start-ip-address $MyIp `
    --end-ip-address $MyIp `
    --output none
Write-Success "SQL firewall configured"

# ---------------------------------------------------------------------------
# 5. Azure SQL Database — free serverless
# ---------------------------------------------------------------------------
$dbExists = Az-Exists sql db show --name $SqlDbName --resource-group $RgName --server $SqlServerName --query name -o tsv
if ($dbExists) {
    Write-Info "SQL Database already exists: $SqlDbName (skipping)"
} else {
    Write-Info "Creating SQL Database: $SqlDbName (free serverless)..."
    az sql db create `
        --name $SqlDbName `
        --resource-group $RgName `
        --server $SqlServerName `
        --edition GeneralPurpose `
        --compute-model Serverless `
        --family Gen5 `
        --capacity 1 `
        --min-capacity 0.5 `
        --auto-pause-delay 60 `
        --use-free-limit `
        --free-limit-exhaustion-behavior AutoPause `
        --backup-storage-redundancy Local `
        --tags workload=$Workload environment=$Env `
        --output none
    Write-Success "SQL Database: $SqlDbName (free serverless)"
}

# ---------------------------------------------------------------------------
# 6. Store secrets in Key Vault
# ---------------------------------------------------------------------------
$ConnStr = "Driver={ODBC Driver 18 for SQL Server};" +
           "Server=tcp:$SqlServerName.database.windows.net,1433;" +
           "Database=$SqlDbName;" +
           "Uid=$SqlAdminUser;" +
           "Pwd=$SqlAdminPassword;" +
           "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"

Write-Info "Storing secrets in Key Vault..."

# Grant current user Secrets Officer role (required with RBAC-enabled vault)
$CurrentUserId = az ad signed-in-user show --query id -o tsv
$KvResourceId  = az keyvault show --name $KeyVaultName --resource-group $RgName --query id -o tsv
az role assignment create `
    --assignee $CurrentUserId `
    --role "Key Vault Secrets Officer" `
    --scope $KvResourceId `
    --output none 2>$null
Write-Info "Waiting 15s for RBAC propagation..."
Start-Sleep -Seconds 15

az keyvault secret set --vault-name $KeyVaultName --name "SqlConnectionString" --value $ConnStr --output none
az keyvault secret set --vault-name $KeyVaultName --name "SqlAdminPassword"    --value $SqlAdminPassword --output none
az keyvault secret set --vault-name $KeyVaultName --name "SqlServerHost"       --value "$SqlServerName.database.windows.net" --output none
az keyvault secret set --vault-name $KeyVaultName --name "SqlDatabase"         --value $SqlDbName --output none
Write-Success "Secrets stored in Key Vault"

# ---------------------------------------------------------------------------
# 7. App Service Plan (Free F1, Linux)
# ---------------------------------------------------------------------------
$planExists = Az-Exists appservice plan show --name $AppPlanName --resource-group $RgName --query name -o tsv
if ($planExists) {
    Write-Info "App Service Plan already exists: $AppPlanName (skipping)"
} else {
    Write-Info "Creating App Service Plan: $AppPlanName (Free F1)..."
    az appservice plan create `
        --name $AppPlanName `
        --resource-group $RgName `
        --location $AppLocation `
        --sku F1 `
        --is-linux `
        --tags workload=$Workload environment=$Env `
        --output none
    Write-Success "App Service Plan: $AppPlanName"
}

# ---------------------------------------------------------------------------
# 8. Web App — Python 3.11 / Streamlit
# ---------------------------------------------------------------------------
$appExists = Az-Exists webapp show --name $AppName --resource-group $RgName --query name -o tsv
if ($appExists) {
    Write-Info "Web App already exists: $AppName (skipping create)"
} else {
    Write-Info "Creating Web App: $AppName..."
    az webapp create `
        --name $AppName `
        --resource-group $RgName `
        --plan $AppPlanName `
        --runtime "PYTHON:3.11" `
        --tags workload=$Workload environment=$Env `
        --output none
}

az webapp config set `
    --name $AppName `
    --resource-group $RgName `
    --startup-file "python -m streamlit run app.py --server.port 8000 --server.address 0.0.0.0" `
    --output none

az webapp config appsettings set `
    --name $AppName `
    --resource-group $RgName `
    --settings `
        "SQL_CONNECTION_STRING=@Microsoft.KeyVault(VaultName=$KeyVaultName;SecretName=SqlConnectionString)" `
        "SCM_DO_BUILD_DURING_DEPLOYMENT=true" `
        "WEBSITES_PORT=8000" `
    --output none

Write-Success "Web App: https://$AppName.azurewebsites.net"

# ---------------------------------------------------------------------------
# 9. Managed identity — Web App → Key Vault
# ---------------------------------------------------------------------------
Write-Info "Enabling managed identity for Web App..."
az webapp identity assign --name $AppName --resource-group $RgName --output none

$AppPrincipalId = az webapp identity show `
    --name $AppName --resource-group $RgName `
    --query principalId -o tsv

$KvResourceId = az keyvault show `
    --name $KeyVaultName --resource-group $RgName `
    --query id -o tsv

Write-Info "Granting Key Vault Secrets User role to Web App identity..."
az role assignment create `
    --assignee $AppPrincipalId `
    --role "Key Vault Secrets User" `
    --scope $KvResourceId `
    --output none 2>$null
Write-Success "Managed identity → Key Vault access granted"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
$sep = '=' * 64
Write-Host ''
Write-Host $sep -ForegroundColor Green
Write-Host '  Setup complete - diving-eval v2 Azure infrastructure' -ForegroundColor Green
Write-Host $sep -ForegroundColor Green
Write-Host "  Tenant ID      : $TenantId"
Write-Host "  Subscription   : $SubscriptionId"
Write-Host "  Resource Group : $RgName"
Write-Host "  Region         : $Location"
Write-Host ''
Write-Host "  SQL Server     : $SqlServerName.database.windows.net"
Write-Host "  SQL Database   : $SqlDbName"
Write-Host "  Key Vault      : $KeyVaultName"
Write-Host "  Web App        : https://$AppName.azurewebsites.net"
Write-Host ''
Write-Host '  NEXT STEPS:' -ForegroundColor Cyan
Write-Host '  1. Run DDL script (sqlcmd or Azure Data Studio):'
Write-Host "     sqlcmd -S $SqlServerName.database.windows.net -d $SqlDbName -U $SqlAdminUser -i sqltables\create_tables_azure.sql"
Write-Host ''
Write-Host '  2. Deploy Streamlit app:'
Write-Host "     az webapp up --name $AppName --resource-group $RgName"
Write-Host $sep -ForegroundColor Green
