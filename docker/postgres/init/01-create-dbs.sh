#!/usr/bin/env bash
# Runs once, on first boot of an empty postgres volume. Creates the Airflow metadata database and
# the NFL warehouse database with its schemas.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-SQL
    CREATE USER airflow WITH PASSWORD 'airflow';
    CREATE DATABASE airflow OWNER airflow;

    CREATE USER nfl WITH PASSWORD 'nfl';
    CREATE DATABASE nfl OWNER nfl;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname nfl <<-SQL
    CREATE SCHEMA IF NOT EXISTS staging AUTHORIZATION nfl;
    CREATE SCHEMA IF NOT EXISTS clean AUTHORIZATION nfl;
    CREATE SCHEMA IF NOT EXISTS nfl AUTHORIZATION nfl;
    CREATE SCHEMA IF NOT EXISTS metadata AUTHORIZATION nfl;
    ALTER DATABASE nfl SET search_path TO nfl, clean, staging, metadata, public;
SQL
