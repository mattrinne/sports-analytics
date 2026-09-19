#!/usr/bin/env bash
# Read-only role for the API: SELECT on nfl.* and ops.* only. Runs on first boot after
# 01-create-dbs.sh, and is idempotent so it can be applied to an existing volume by hand:
#   docker compose exec -T postgres bash /docker-entrypoint-initdb.d/02-reader-role.sh
# Default privileges are set FOR ROLE nfl (the owner) so grants survive dbt dropping and
# recreating a mart and the pipeline creating ops.* later.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname nfl <<'SQL'
    DO $$ BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'nfl_reader') THEN
            CREATE ROLE nfl_reader LOGIN PASSWORD 'nfl_reader';
        END IF;
    END $$;
    ALTER ROLE nfl_reader SET default_transaction_read_only = on;
    ALTER ROLE nfl_reader SET statement_timeout = '15s';
    GRANT CONNECT ON DATABASE nfl TO nfl_reader;
    GRANT USAGE ON SCHEMA nfl, ops TO nfl_reader;
    GRANT SELECT ON ALL TABLES IN SCHEMA nfl, ops TO nfl_reader;
    ALTER DEFAULT PRIVILEGES FOR ROLE nfl IN SCHEMA nfl GRANT SELECT ON TABLES TO nfl_reader;
    ALTER DEFAULT PRIVILEGES FOR ROLE nfl IN SCHEMA ops GRANT SELECT ON TABLES TO nfl_reader;
SQL
