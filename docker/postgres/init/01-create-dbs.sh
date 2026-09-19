#!/usr/bin/env bash
# Runs once, on first boot of an empty postgres volume. Creates the NFL warehouse database, its
# role and schemas. (ops.* tables are created by the pipeline itself on first run.)
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-SQL
    CREATE USER nfl WITH PASSWORD 'nfl';
    CREATE DATABASE nfl OWNER nfl;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname nfl <<-SQL
    CREATE SCHEMA IF NOT EXISTS staging AUTHORIZATION nfl;
    CREATE SCHEMA IF NOT EXISTS clean AUTHORIZATION nfl;
    CREATE SCHEMA IF NOT EXISTS reference AUTHORIZATION nfl;
    CREATE SCHEMA IF NOT EXISTS nfl AUTHORIZATION nfl;
    CREATE SCHEMA IF NOT EXISTS ops AUTHORIZATION nfl;
    ALTER DATABASE nfl SET search_path TO nfl, reference, clean, staging, ops, public;
SQL
