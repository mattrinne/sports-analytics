#!/usr/bin/env bash
# Deletes everything in the resource group, including the database and its backups. Irreversible.
set -euo pipefail
read -r -p "Delete resource group $AZ_RG and all data? type the group name to confirm: " answer
[[ "$answer" == "$AZ_RG" ]] || { echo "aborted"; exit 1; }
az group delete --name "$AZ_RG" --yes --no-wait
echo "deleting $AZ_RG in the background"
