#!/usr/bin/env bash
# A manually triggered job for backfills and one-off commands (same image and secrets).
#   az containerapp job start -g $AZ_RG -n $JOB_MANUAL --args backfill --start 2010 --workers 2
#   az containerapp job start -g $AZ_RG -n $JOB_MANUAL --args transform --full-refresh
# B1ms burst credits make a full 2010+ backfill slow (hours); scale up for the day if you like:
#   az postgres flexible-server update -g $AZ_RG -n $PG_SERVER --sku-name Standard_B2s   (and back)
# Or run the backfill from the laptop with NFL_DATABASE_URL pointing at Azure (firewall rule exists).
set -euo pipefail
: "${NFL_DATABASE_URL:?set NFL_DATABASE_URL in your shell}"

SECRETS=("database-url=$NFL_DATABASE_URL")
ENV_VARS=(NFL_DATABASE_URL=secretref:database-url)
if [[ -n "${NFL_ALERT_WEBHOOK_URL:-}" ]]; then
  SECRETS+=("webhook-url=$NFL_ALERT_WEBHOOK_URL")
  ENV_VARS+=(NFL_ALERT_WEBHOOK_URL=secretref:webhook-url)
fi
COMMON=(
  --image "$IMAGE" --cpu "$JOB_CPU" --memory "$JOB_MEMORY"
  --secrets "${SECRETS[@]}" --env-vars "${ENV_VARS[@]}"
)

if az containerapp job show -g "$AZ_RG" -n "$JOB_MANUAL" --output none 2>/dev/null; then
  az containerapp job update -g "$AZ_RG" -n "$JOB_MANUAL" "${COMMON[@]}" --args --help --output none
else
  az containerapp job create -g "$AZ_RG" -n "$JOB_MANUAL" --environment "$CAE" \
    --trigger-type Manual --replica-timeout 14400 --replica-retry-limit 0 \
    --parallelism 1 --replica-completion-count 1 "${COMMON[@]}" --args --help --output none
fi
echo "job $JOB_MANUAL ready. Start with: az containerapp job start -g $AZ_RG -n $JOB_MANUAL --args <command> ..."
