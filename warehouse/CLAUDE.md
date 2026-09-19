# warehouse — working notes for Claude

The data layer: nflverse + Wikipedia → Postgres via `nfl-pipeline` → dbt. This folder is its own uv
project; run `uv ...` from here and `docker compose ...` from the repo root. The root `CLAUDE.md`
has the rules that span components; `README.md` here lists the datasets and points to the same
topic docs as this file. Nothing below repeats them: read the doc for the task before working.

| before you touch | read |
|---|---|
| anything under `dbt/`, a new mart, view or column | `docs/layers.md` — which schema may hold what, contracts, generated clean models, the incremental pattern, when a full refresh is allowed |
| a name, code, id or a new entity | `docs/identity.md` — mappings → identities → dimensions, how ids are minted, never auto-merge, the known data quirks |
| the loader, the registry, `refresh`/`backfill`, `ops`, alerts | `docs/loading.md` — code path, skip vs failure, staging truncation, never add cross-cutting steps to `refresh` |
| running, testing or verifying | `docs/commands.md` — the CLI, connection variables, and the end-to-end verification recipe |
| what a dataset is and how it is partitioned | `README.md`, Datasets |

Before reporting a change done, run the verification recipe at the end of `docs/commands.md`.
Commit only when asked. Paths in this file are relative to `warehouse/`.
