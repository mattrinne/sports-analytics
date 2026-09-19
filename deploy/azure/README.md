# Deploying the warehouse to Azure

Cheapest shape that keeps the design intact: one always-on managed Postgres and a container that
runs the pipeline on a cron trigger, billed by the second, inside the free grant. Every run ends by
truncating staging, so the database holds only `clean.*` and the small schemas. The laptop
compose stack stays the dev environment.

```
docker build/push (by hand, for now) ──▶ ghcr.io/<owner>/nfl-pipeline:<tag>   (public package, free)
                                   │
Azure Container Apps Job  nfl-refresh   cron 0 14 * * 2,3 UTC   → nfl-pipeline refresh
                          nfl-manual    on demand                → nfl-pipeline backfill / transform / …
                                   │  NFL_DATABASE_URL (secret, ?sslmode=require)
Azure Database for PostgreSQL Flexible Server  B1ms, 32 GiB   staging / clean / reference / nfl / ops
```

## Monthly cost (East US, pay-as-you-go, list prices Sept 2026; check the pricing calculator)

| item | USD/month |
|---|---|
| Postgres Flexible Server B1ms (1 vCore, 2 GiB), always on | ~12–13 |
| Postgres storage 32 GiB (minimum) + backups up to storage size | ~4 |
| Container Apps Jobs: ~8 runs × ≤15 min × 1 vCPU / 2 GiB | 0 (free grant: 180k vCPU-s, 360k GiB-s) |
| Container Apps environment (consumption) | 0 |
| Log Analytics, ≤5 GB, 30-day retention | 0 |
| GitHub Container Registry, public package | 0 |
| **Total** | **~17** |

Levers: the server can be stopped for up to 7 days at a time (`az postgres flexible-server stop`),
which halves the bill while nothing reads it; storage cannot shrink, so keep 32 GiB.

## Runbook

Requirements: `az` CLI logged in (`az login`), the `containerapp` extension
(`az extension add -n containerapp`), and the image pushed once to GHCR with the package set to
**Public** (GitHub → Packages → nfl-pipeline → Package settings):

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u <owner> --password-stdin   # token with write:packages
docker build --platform linux/amd64 -t ghcr.io/<owner>/nfl-pipeline:$(git rev-parse --short HEAD) ./warehouse
docker push ghcr.io/<owner>/nfl-pipeline:$(git rev-parse --short HEAD)
```

A CI build on push is deferred; when it comes back it replaces these three lines.

```bash
source deploy/azure/env.sh
export PG_SERVER=nfl-pg-<something-unique>      # pin the random default
export PG_PASSWORD='<long random>'
export IMAGE=ghcr.io/<owner>/nfl-pipeline:latest  # or a :<sha> tag
export NFL_ALERT_WEBHOOK_URL=https://ntfy.sh/<topic>   # optional

./deploy/azure/01-infra.sh          # prints the NFL_DATABASE_URL to use next
export NFL_DATABASE_URL='postgresql://nfladmin:<password>@<host>:5432/nfl?sslmode=require'
./deploy/azure/02-job.sh            # scheduled refresh
./deploy/azure/03-manual-job.sh     # manual job for backfills

# first load: hours on B1ms. Either from Azure …
az containerapp job start -g "$AZ_RG" -n "$JOB_MANUAL" --args backfill --start 2010 --workers 2
# … or from the laptop (firewall rule for your IP exists):
NFL_DATABASE_URL="$NFL_DATABASE_URL" uv run --project warehouse nfl-pipeline backfill --start 2010
```

Watch a run:

```bash
az containerapp job execution list -g "$AZ_RG" -n "$JOB_REFRESH" -o table
az containerapp job logs show -g "$AZ_RG" -n "$JOB_REFRESH" --container "$JOB_REFRESH" --follow
psql "$NFL_DATABASE_URL" -c "select run_id, command, status, started_at, finished_at, error from ops.runs order by 1 desc limit 5"
```

A deploy is good when a small manual run succeeds end to end:

```bash
az containerapp job start -g "$AZ_RG" -n "$JOB_MANUAL" --args refresh -d teams
az containerapp job execution list -g "$AZ_RG" -n "$JOB_MANUAL" -o table   # newest row: Status Succeeded
psql "$NFL_DATABASE_URL" -Atc "select command, status from ops.runs order by run_id desc limit 1"   # refresh|success
```

Roll a new image: build and push a new tag as above, then `IMAGE=ghcr.io/<owner>/nfl-pipeline:<sha> ./deploy/azure/02-job.sh`
(and `03-manual-job.sh`). Change the schedule with `REFRESH_CRON`. Tear everything down with `04-teardown.sh`.

## Notes

- Cron is UTC. `0 14 * * 2,3` is 09:00 Chicago in summer and 08:00 in winter; nflverse publishes
  overnight, so the hour of drift does not matter.
- `--replica-retry-limit 0`: retries happen inside the command (`--retries 2`, 30 s / 60 s). A job
  that exits 1 shows as Failed in the execution list and, with a webhook set, sends one message.
- Staging is truncated after every green dbt build, so the 32 GiB volume holds only `clean.*`
  (~2.5 GB for 2010+). Full-refresh rules: `warehouse/CLAUDE.md` (dbt conventions).
- Memory: a pbp season peaks around 0.5 GB in the loader; the default 4 workers fit in 2 GiB for a
  refresh. Use `--workers 2` for backfills in the container.
- Firewall: `--public-access 0.0.0.0` allows Azure services (the job) plus the laptop rule. Tighten
  later by replacing it with the environment's outbound IPs if you move to a workload-profile env.
- Early-September runs before nflverse publishes week 1 fail on pbp and alert once. Expected.
