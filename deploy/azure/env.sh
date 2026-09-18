# Names, region and sizes for the Azure deployment. Source this before any script:
#   source deploy/azure/env.sh
# Everything is idempotent; re-running a script updates in place.

export AZ_LOCATION="${AZ_LOCATION:-eastus}"
export AZ_RG="${AZ_RG:-rg-nfl}"

# Postgres Flexible Server. B1ms (1 vCore, 2 GiB) + 32 GiB is the smallest tier; ~US$17/month.
export PG_SERVER="${PG_SERVER:-nfl-pg-$RANDOM}"        # must be globally unique; pin it in your shell
export PG_SKU="${PG_SKU:-Standard_B1ms}"
export PG_STORAGE_GB="${PG_STORAGE_GB:-32}"
export PG_VERSION="${PG_VERSION:-16}"
export PG_ADMIN="${PG_ADMIN:-nfladmin}"
export PG_DB="${PG_DB:-nfl}"
# export PG_PASSWORD=...                               # set in your shell, never in this file

# Container Apps (consumption plan: no fixed cost, generous free grant).
export LAW="${LAW:-law-nfl}"                             # Log Analytics workspace
export CAE="${CAE:-cae-nfl}"                             # Container Apps environment
export JOB_REFRESH="${JOB_REFRESH:-nfl-refresh}"
export JOB_MANUAL="${JOB_MANUAL:-nfl-manual}"
export JOB_CPU="${JOB_CPU:-1.0}"
export JOB_MEMORY="${JOB_MEMORY:-2Gi}"
# UTC. 14:00 = 09:00 CDT / 08:00 CST. nflverse publishes overnight, so later is safer than earlier.
export REFRESH_CRON="${REFRESH_CRON:-0 14 * * 2,3}"

# Image on GitHub Container Registry (public package). Built and pushed by hand for now:
#   docker build --platform linux/amd64 -t ghcr.io/<owner>/nfl-pipeline:<tag> . && docker push ghcr.io/<owner>/nfl-pipeline:<tag>
export IMAGE="${IMAGE:-ghcr.io/CHANGE-ME/nfl-pipeline:latest}"

# Optional webhook for failure alerts (Slack / Discord / ntfy). Blank disables it.
export NFL_ALERT_WEBHOOK_URL="${NFL_ALERT_WEBHOOK_URL:-}"
