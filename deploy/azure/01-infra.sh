#!/usr/bin/env bash
# Resource group, Postgres Flexible Server (+ database, firewall), Log Analytics, Container Apps env.
# Requires: az login; source deploy/azure/env.sh; PG_PASSWORD set.
set -euo pipefail
: "${PG_PASSWORD:?set PG_PASSWORD in your shell}"

az group create --name "$AZ_RG" --location "$AZ_LOCATION" --output none

if ! az postgres flexible-server show -g "$AZ_RG" -n "$PG_SERVER" --output none 2>/dev/null; then
  # Public endpoint + firewall. Private VNet access needs a VNet-integrated environment, delegated
  # subnets and private DNS, and would block psql/DBeaver from the laptop.
  az postgres flexible-server create -g "$AZ_RG" -n "$PG_SERVER" -l "$AZ_LOCATION" \
    --tier Burstable --sku-name "$PG_SKU" --storage-size "$PG_STORAGE_GB" --version "$PG_VERSION" \
    --admin-user "$PG_ADMIN" --admin-password "$PG_PASSWORD" \
    --public-access 0.0.0.0 --backup-retention 7 --yes --output none
fi
az postgres flexible-server db create -g "$AZ_RG" -s "$PG_SERVER" -d "$PG_DB" --output none 2>/dev/null || true

# Your current IP, so psql / DBeaver / a laptop-run backfill can reach the server.
MYIP=$(curl -fsS https://api.ipify.org)
az postgres flexible-server firewall-rule create -g "$AZ_RG" -n "$PG_SERVER" \
  --rule-name laptop --start-ip-address "$MYIP" --end-ip-address "$MYIP" --output none

az monitor log-analytics workspace create -g "$AZ_RG" -n "$LAW" -l "$AZ_LOCATION" \
  --retention-time 30 --output none
LAW_ID=$(az monitor log-analytics workspace show -g "$AZ_RG" -n "$LAW" --query customerId -o tsv)
LAW_KEY=$(az monitor log-analytics workspace get-shared-keys -g "$AZ_RG" -n "$LAW" --query primarySharedKey -o tsv)

if ! az containerapp env show -g "$AZ_RG" -n "$CAE" --output none 2>/dev/null; then
  az containerapp env create -g "$AZ_RG" -n "$CAE" -l "$AZ_LOCATION" \
    --logs-workspace-id "$LAW_ID" --logs-workspace-key "$LAW_KEY" --output none
fi

HOST=$(az postgres flexible-server show -g "$AZ_RG" -n "$PG_SERVER" --query fullyQualifiedDomainName -o tsv)
echo "NFL_DATABASE_URL=postgresql://${PG_ADMIN}:<password>@${HOST}:5432/${PG_DB}?sslmode=require"
echo "Optional, once, with psql: ALTER DATABASE ${PG_DB} SET search_path TO nfl, reference, clean, staging, metadata, ops, public;"
