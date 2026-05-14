#!/usr/bin/env bash
# =============================================================================
# Azure Infrastructure Setup — diving-eval v2
# Organisation : SKThun (skthun.ch)
# Tenant ID    : d64867f2-5502-4dd1-81bd-5d0d663af5f3
# Domain       : skthun.onmicrosoft.com / skthun.ch
#
# Naming convention (Microsoft CAF):
#   {type}-{workload}-{env}[-{region-short}]
#   Globally unique resources also carry org prefix: skthun
#
# Resources created:
#   rg-divingeval-prod-chn         Resource Group
#   kv-skthun-divingeval-prod      Key Vault
#   sql-skthun-divingeval-prod     Azure SQL Server
#   sqldb-divingeval-prod          Azure SQL Database (free serverless)
#   asp-divingeval-prod-chn        App Service Plan (Free F1, Linux)
#   app-skthun-divingeval-prod     Web App (Python 3.11 / Streamlit)
#
# Prerequisites:
#   az cli installed: https://aka.ms/installazurecliwindows
#   Run first: az login --tenant d64867f2-5502-4dd1-81bd-5d0d663af5f3
#
# Usage (bash / Git Bash / WSL):
#   bash infra/setup-azure.sh
#   SQL_ADMIN_PASSWORD="YourStr0ng!Pw" bash infra/setup-azure.sh
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TENANT_ID="d64867f2-5502-4dd1-81bd-5d0d663af5f3"
LOCATION="switzerlandnorth"
LOCATION_SHORT="chn"

WORKLOAD="divingeval"
ORG="skthun"
ENV="prod"

RG_NAME="rg-${WORKLOAD}-${ENV}-${LOCATION_SHORT}"
SQL_SERVER_NAME="sql-${ORG}-${WORKLOAD}-${ENV}"
SQL_DB_NAME="sqldb-${WORKLOAD}-${ENV}"
SQL_ADMIN_USER="sqladmin"
SQL_ADMIN_PASSWORD="${SQL_ADMIN_PASSWORD:-}"
ADMIN_LOGIN_PASSWORD="${ADMIN_LOGIN_PASSWORD:-}"
ALLOWED_LOGIN_EMAILS="${ALLOWED_LOGIN_EMAILS:-chris@greuters.com,christian.greuter@outlook.com,christian.greuter@cgsol.ch,christian.greuter@swiss-aquatics.ch,christian.finger@swiss-aquatics.ch}"
ADMIN_ENTRA_GROUP_IDS="${ADMIN_ENTRA_GROUP_IDS:-}"
KEYVAULT_NAME="kv-${ORG}-${WORKLOAD}-${ENV}"
APP_PLAN_NAME="asp-${WORKLOAD}-${ENV}-${LOCATION_SHORT}"
APP_NAME="app-${ORG}-${WORKLOAD}-${ENV}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()    { echo -e "\033[36m[INFO]\033[0m  $*"; }
success() { echo -e "\033[32m[OK]\033[0m    $*"; }
warn()    { echo -e "\033[33m[WARN]\033[0m  $*"; }
err()     { echo -e "\033[31m[ERROR]\033[0m $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 0. Login & subscription
# ---------------------------------------------------------------------------
info "Checking Azure login..."
CURRENT_TENANT=$(az account show --query tenantId -o tsv 2>/dev/null || true)

if [[ "$CURRENT_TENANT" != "$TENANT_ID" ]]; then
  warn "Not logged in to correct tenant. Running az login..."
  az login --tenant "$TENANT_ID"
fi

SUBSCRIPTION_ID=$(az account list \
  --query "[?tenantId=='${TENANT_ID}'].id" -o tsv | head -1)
[[ -z "$SUBSCRIPTION_ID" ]] && \
  err "No subscription found in tenant $TENANT_ID. Create one in Azure Portal first."

az account set --subscription "$SUBSCRIPTION_ID"
success "Subscription: $SUBSCRIPTION_ID"

# Prompt for SQL password if not set via env
if [[ -z "$SQL_ADMIN_PASSWORD" ]]; then
  echo ""
  read -s -r -p "SQL admin password (min 12 chars, upper+lower+digit+special): " \
    SQL_ADMIN_PASSWORD
  echo ""
fi

if [[ -z "$ADMIN_LOGIN_PASSWORD" ]]; then
  echo ""
  read -s -r -p "App login password (ADMIN_PASSWORD): " \
    ADMIN_LOGIN_PASSWORD
  echo ""
fi

# ---------------------------------------------------------------------------
# 1. Resource Group
# ---------------------------------------------------------------------------
info "Creating resource group: $RG_NAME..."
az group create \
  --name          "$RG_NAME" \
  --location      "$LOCATION" \
  --tags workload="$WORKLOAD" environment="$ENV" organisation="$ORG" \
  --output none
success "Resource group: $RG_NAME"

# ---------------------------------------------------------------------------
# 2. Key Vault
# ---------------------------------------------------------------------------
info "Creating Key Vault: $KEYVAULT_NAME..."
az keyvault create \
  --name                      "$KEYVAULT_NAME" \
  --resource-group            "$RG_NAME" \
  --location                  "$LOCATION" \
  --sku                       standard \
  --enable-rbac-authorization true \
  --tags workload="$WORKLOAD" environment="$ENV" \
  --output none
success "Key Vault: $KEYVAULT_NAME"

# ---------------------------------------------------------------------------
# 3. Azure SQL Server
# ---------------------------------------------------------------------------
info "Creating SQL Server: $SQL_SERVER_NAME..."
az sql server create \
  --name                 "$SQL_SERVER_NAME" \
  --resource-group       "$RG_NAME" \
  --location             "$LOCATION" \
  --admin-user           "$SQL_ADMIN_USER" \
  --admin-password       "$SQL_ADMIN_PASSWORD" \
  --enable-public-network true \
  --output none
success "SQL Server: ${SQL_SERVER_NAME}.database.windows.net"

# Allow Azure services (App Service → SQL)
az sql server firewall-rule create \
  --name             "AllowAzureServices" \
  --resource-group   "$RG_NAME" \
  --server           "$SQL_SERVER_NAME" \
  --start-ip-address 0.0.0.0 \
  --end-ip-address   0.0.0.0 \
  --output none

# Allow developer's current IP (for running DDL scripts locally)
MY_IP=$(curl -s https://api.ipify.org)
info "Adding firewall rule for developer IP: $MY_IP..."
az sql server firewall-rule create \
  --name             "AllowDeveloperIP" \
  --resource-group   "$RG_NAME" \
  --server           "$SQL_SERVER_NAME" \
  --start-ip-address "$MY_IP" \
  --end-ip-address   "$MY_IP" \
  --output none
success "SQL firewall configured"

# ---------------------------------------------------------------------------
# 4. Azure SQL Database — free serverless tier
#    32 GB storage, 100k vCore-seconds/month, auto-pause after 60 min idle
# ---------------------------------------------------------------------------
info "Creating SQL Database: $SQL_DB_NAME (free serverless)..."
az sql db create \
  --name                          "$SQL_DB_NAME" \
  --resource-group                "$RG_NAME" \
  --server                        "$SQL_SERVER_NAME" \
  --edition                       GeneralPurpose \
  --compute-model                 Serverless \
  --family                        Gen5 \
  --capacity                      1 \
  --min-capacity                  0.5 \
  --auto-pause-delay              60 \
  --use-free-limit                \
  --free-limit-exhaustion-behavior AutoPause \
  --backup-storage-redundancy     Local \
  --tags workload="$WORKLOAD" environment="$ENV" \
  --output none
success "SQL Database: $SQL_DB_NAME (free serverless)"

# ---------------------------------------------------------------------------
# 5. Store secrets in Key Vault
# ---------------------------------------------------------------------------
CONN_STR="Driver={ODBC Driver 18 for SQL Server};\
Server=tcp:${SQL_SERVER_NAME}.database.windows.net,1433;\
Database=${SQL_DB_NAME};\
Uid=${SQL_ADMIN_USER};\
Pwd=${SQL_ADMIN_PASSWORD};\
Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"

info "Storing secrets in Key Vault..."
az keyvault secret set \
  --vault-name "$KEYVAULT_NAME" --name "SqlConnectionString" \
  --value "$CONN_STR" --output none
az keyvault secret set \
  --vault-name "$KEYVAULT_NAME" --name "SqlAdminPassword" \
  --value "$SQL_ADMIN_PASSWORD" --output none
az keyvault secret set \
  --vault-name "$KEYVAULT_NAME" --name "SqlServerHost" \
  --value "${SQL_SERVER_NAME}.database.windows.net" --output none
az keyvault secret set \
  --vault-name "$KEYVAULT_NAME" --name "SqlDatabase" \
  --value "$SQL_DB_NAME" --output none
az keyvault secret set \
  --vault-name "$KEYVAULT_NAME" --name "AdminLoginPassword" \
  --value "$ADMIN_LOGIN_PASSWORD" --output none
az keyvault secret set \
  --vault-name "$KEYVAULT_NAME" --name "AllowedLoginEmails" \
  --value "$ALLOWED_LOGIN_EMAILS" --output none
success "Secrets stored in Key Vault"

# ---------------------------------------------------------------------------
# 6. App Service Plan (Free F1, Linux)
# ---------------------------------------------------------------------------
info "Creating App Service Plan: $APP_PLAN_NAME (Free F1)..."
az appservice plan create \
  --name           "$APP_PLAN_NAME" \
  --resource-group "$RG_NAME" \
  --location       "$LOCATION" \
  --sku            F1 \
  --is-linux \
  --tags workload="$WORKLOAD" environment="$ENV" \
  --output none
success "App Service Plan: $APP_PLAN_NAME"

# ---------------------------------------------------------------------------
# 7. Web App — Python 3.11 for Streamlit
# ---------------------------------------------------------------------------
info "Creating Web App: $APP_NAME..."
az webapp create \
  --name           "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --plan           "$APP_PLAN_NAME" \
  --runtime        "PYTHON:3.11" \
  --tags workload="$WORKLOAD" environment="$ENV" \
  --output none

# Streamlit startup command (port 8000 required by App Service)
az webapp config set \
  --name         "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --startup-file "python -m streamlit run app.py --server.port 8000 --server.address 0.0.0.0" \
  --output none

# App settings — connection string referenced from Key Vault
az webapp config appsettings set \
  --name           "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --settings \
    SQL_CONNECTION_STRING="@Microsoft.KeyVault(VaultName=${KEYVAULT_NAME};SecretName=SqlConnectionString)" \
    ADMIN_PASSWORD="@Microsoft.KeyVault(VaultName=${KEYVAULT_NAME};SecretName=AdminLoginPassword)" \
    ALLOWED_LOGIN_EMAILS="@Microsoft.KeyVault(VaultName=${KEYVAULT_NAME};SecretName=AllowedLoginEmails)" \
    ADMIN_ENTRA_GROUP_IDS="${ADMIN_ENTRA_GROUP_IDS}" \
    SCM_DO_BUILD_DURING_DEPLOYMENT=true \
    WEBSITES_PORT=8000 \
  --output none

success "Web App: https://${APP_NAME}.azurewebsites.net"

# ---------------------------------------------------------------------------
# 8. Managed identity — Web App → Key Vault
# ---------------------------------------------------------------------------
info "Enabling system-assigned managed identity for Web App..."
az webapp identity assign \
  --name "$APP_NAME" --resource-group "$RG_NAME" --output none

APP_PRINCIPAL_ID=$(az webapp identity show \
  --name "$APP_NAME" --resource-group "$RG_NAME" \
  --query principalId -o tsv)

KV_RESOURCE_ID=$(az keyvault show \
  --name "$KEYVAULT_NAME" --resource-group "$RG_NAME" \
  --query id -o tsv)

info "Granting Key Vault Secrets User role to Web App identity..."
az role assignment create \
  --assignee "$APP_PRINCIPAL_ID" \
  --role     "Key Vault Secrets User" \
  --scope    "$KV_RESOURCE_ID" \
  --output none
success "Managed identity → Key Vault access granted"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Setup complete — diving-eval v2 Azure infrastructure        ║"
echo "╠══════════════════════════════════════════════════════════════╣"
printf "║  %-20s %s\n" "Tenant:"          "$TENANT_ID  ║"
printf "║  %-20s %s\n" "Subscription:"    "$SUBSCRIPTION_ID  ║"
printf "║  %-20s %s\n" "Resource Group:"  "$RG_NAME  ║"
printf "║  %-20s %s\n" "Region:"          "$LOCATION  ║"
echo "╠══════════════════════════════════════════════════════════════╣"
printf "║  %-20s %s\n" "SQL Server:"      "${SQL_SERVER_NAME}.database.windows.net  ║"
printf "║  %-20s %s\n" "SQL Database:"    "$SQL_DB_NAME  ║"
printf "║  %-20s %s\n" "Key Vault:"       "$KEYVAULT_NAME  ║"
printf "║  %-20s %s\n" "Web App:"         "https://${APP_NAME}.azurewebsites.net  ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  NEXT STEPS:                                                 ║"
echo "║  1. Create tables (requires sqlcmd or Azure Data Studio):    ║"
echo "║     sqlcmd -S ${SQL_SERVER_NAME}.database.windows.net        ║"
echo "║            -d $SQL_DB_NAME -U $SQL_ADMIN_USER                ║"
echo "║            -i sqltables/create_tables_azure.sql              ║"
echo "║                                                              ║"
echo "║  2. Deploy Streamlit app:                                    ║"
echo "║     az webapp up --name $APP_NAME \\                         ║"
echo "║       --resource-group $RG_NAME                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
