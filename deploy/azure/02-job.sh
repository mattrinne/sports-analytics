#!/usr/bin/env bash
# The scheduled refresh job. Re-run to roll a new image tag (set IMAGE) or change the schedule.
# Requires: 01-infra.sh done; source deploy/azure/env.sh; NFL_DATABASE_URL set (with ?sslmode=require).
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

if az containerapp job show -g "$AZ_RG" -n "$JOB_REFRESH" --output none 2>/dev/null; then
  az containerapp job update -g "$AZ_RG" -n "$JOB_REFRESH" "${COMMON[@]}" \
    --cron-expression "$REFRESH_CRON" --args refresh --output none
else
  # Retries live inside the command (--retries), so the platform does not retry the whole job.
  az containerapp job create -g "$AZ_RG" -n "$JOB_REFRESH" --environment "$CAE" \
    --trigger-type Schedule --cron-expression "$REFRESH_CRON" \
    --replica-timeout 3600 --replica-retry-limit 0 --parallelism 1 --replica-completion-count 1 \
    "${COMMON[@]}" --args refresh --output none
fi
echo "job $JOB_REFRESH: $IMAGE, cron '$REFRESH_CRON' UTC"
echo "run now:   az containerapp job start -g $AZ_RG -n $JOB_REFRESH"
echo "history:   az containerapp job execution list -g $AZ_RG -n $JOB_REFRESH -o table"
