# Cloud deployment: thoughts on a future architecture

Status: notes carried over from the removed `deploy/azure/` runbook and the api design discussion
(2026-09-18), not a decision. Nothing in this file is deployed. A proper planning session will
replace it.

## What has to run

| piece | shape it needs | why |
|---|---|---|
| Postgres | one small always-on server, tens of GB at most | the only stateful part; `clean.*` for 2010+ is ~2.5 GB because staging is emptied after every run |
| `nfl-pipeline refresh` | a container that starts on a cron, runs for minutes, exits | one refresh a week in season, nothing between; `backfill` is the same image on demand |
| `api` | a container that scales to zero and wakes on request | one user, bursts of reads, idle the rest of the time |
| The Hook (UI) | static files or a scale-to-zero container next to the api | reads only the api |

Constraints that shape every option: one user pays, so idle cost must be near zero; data is
historical, so nothing needs to be up when nobody is looking; nothing downloaded at runtime may be
written to disk (images carry `dbt/` and `data/`, caches are off); one connection string is the only
secret the pipeline needs.

## The shape worked out so far (Azure)

Chosen as the first target because the free monthly grant for Container Apps covers the whole
compute side, leaving the database as the only real cost.

```
image (GHCR, public)  ──▶  Container Apps Job   nfl-refresh   cron  → nfl-pipeline refresh
                           Container Apps Job   nfl-manual    manual → backfill / transform
                           Container App        api           ingress, min replicas 0
                                       │  NFL_DATABASE_URL secret (?sslmode=require)
                           Azure Database for PostgreSQL Flexible Server  Burstable B1ms, 32 GiB
```

- **Database**: Flexible Server, Burstable B1ms (1 vCore, 2 GiB), 32 GiB storage (the minimum;
  storage cannot shrink), 7-day backups, public endpoint allowing Azure services plus a laptop
  firewall rule. Roughly USD 12–13 compute plus ~4 storage per month; can be stopped for up to 7
  days at a time to halve the bill when nothing reads it. A first backfill takes hours on this size.
- **Pipeline**: two Container Apps Jobs from the same image, 1 vCPU / 2 GiB. A scheduled one
  (cron in UTC; nflverse publishes overnight so the hour does not matter) and a manual one with a
  long timeout for backfills (`--workers 2` to fit 2 GiB). Platform retries off; the command retries
  itself. Secrets as Container Apps secrets referenced by env var, no Key Vault. Estimated ~8 runs a
  month at under 15 minutes stays inside the free grant (180k vCPU-s, 360k GiB-s).
- **Environment**: one consumption Container Apps environment with a Log Analytics workspace at
  30-day retention; both free at this usage.
- **Image**: built and pushed by hand to a public GHCR package (`docker build --platform linux/amd64`),
  so no registry credentials anywhere. A CI build would replace the manual push.
- **Total**: about USD 17 a month, all of it the database.

Idempotent `az` scripts for this shape existed in the repo (`deploy/azure/`, removed 2026-09-18,
recoverable from git history) and were exercised end to end: infra, scheduled job, manual job,
teardown.

## The api on the same shape

- A Container App in the same environment with external ingress and `min replicas 0`. Any request
  wakes a replica (a few seconds), which costs vCPU-seconds inside the same free grant.
- **Protecting it.** The optional API key in the app stops strangers running queries against the
  one-vCore database but does not stop wake-ups, because the key is checked inside the replica.
  Ingress IP restrictions are enforced by the platform proxy before a replica starts, so they are
  the only free way to prevent wake-ups; the trade-off is that only allowed IPs can reach the api,
  which rules out a hosted UI outside those IPs unless it runs in the same environment. Built-in
  auth (Easy Auth) runs as a sidecar and wakes the app like the key does. The likely combination is
  the key for data protection plus IP restriction while the UI is laptop-only.
- The image follows the same GHCR pattern and the same single `database-url` secret, pointing at
  a read-only role rather than the admin user.
- The UI can be served as static files from the api container, so one scale-to-zero app instead
  of two.

## Open questions

- **Which cloud.** Azure is the worked example; a managed Postgres elsewhere (a serverless
  Postgres with scale-to-zero, or a small VM running compose) plus a scheduled GitHub Actions run
  for `refresh` could remove the always-on database cost entirely. Not evaluated.
- **CI build** of the images on push, replacing the manual GHCR push.
- **Database firewall**: the public endpoint with a service allow-list versus a workload-profile
  environment with fixed outbound IPs.
- **The reader role in the cloud**: the init scripts only run on a fresh volume, so
  `docker/postgres/init/02-reader-role.sh` would be applied by hand against the managed server.
