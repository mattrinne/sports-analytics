"""Refresh dbt/models/clean/<model>.yml from the built table.

dbt contracts (which the primary-key constraints depend on) require every column declared with
its data_type. Rather than hand-typing ~370 pbp columns, this reads the built clean.<model> table
and rewrites the column list in the model's yml (creating the yml, with the primary key from
scripts/gen_clean_models.py, when it does not exist yet):

  * data_type comes from Postgres (format_type), so it always matches the SQL;
  * existing column entries keep their hand-written description / tests / constraints;
  * new columns get no description (system columns excepted); write one by hand if wanted;
  * columns no longer in the table are removed.

Usage (after `dbt build` of the model, with contracts off or already matching):
    uv run python scripts/gen_dbt_columns.py            # all clean models
    uv run python scripts/gen_dbt_columns.py plays games
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg
import yaml

from nfl_pipeline.config import settings

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "dbt" / "models" / "clean"

sys.path.insert(0, str(ROOT / "scripts"))
from gen_clean_models import PRIMARY_KEYS

RESERVED = {"desc", "time"}
SYSTEM_COLUMNS = {
    "_loaded_at": "When this row was loaded into staging. Drives incremental upserts into clean.",
    "_row_id": "md5 of the identifying columns; surrogate primary key for tables whose source key "
    "is not unique or contains NULLs.",
}


def table_columns(conn: psycopg.Connection, schema: str, table: str) -> list[tuple[str, str]]:
    return conn.execute(
        """
        SELECT a.attname, format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute a
        WHERE a.attrelid = format('%%I.%%I', %s::text, %s::text)::regclass AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        (schema, table),
    ).fetchall()


def describe(column: str) -> str | None:
    return SYSTEM_COLUMNS.get(column)


def skeleton(model: str) -> dict:
    pk = PRIMARY_KEYS.get(model) or ["_row_id"]
    return {
        "name": model,
        "description": f"Typed copy of staging.{model}: every column, same names, types fixed. "
        "Upserted by primary key on every load.",
        "config": {"unique_key": pk},
        "constraints": [{"type": "primary_key", "columns": pk}],
        "columns": [],
    }


def load_yml(path: Path, model: str) -> dict:
    if path.exists():
        return yaml.safe_load(path.read_text()) or {"version": 2, "models": []}
    return {"version": 2, "models": [skeleton(model)]}


def refresh(conn: psycopg.Connection, model: str) -> int:
    path = MODELS / f"{model}.yml"
    doc = load_yml(path, model)
    entry = next((m for m in doc["models"] if m["name"] == model), None)
    if entry is None:
        entry = skeleton(model)
        doc["models"].append(entry)
    existing = {c["name"]: c for c in entry.get("columns") or []}
    columns = []
    for name, data_type in table_columns(conn, settings().clean_schema, model):
        col = existing.get(name, {"name": name})
        col["data_type"] = data_type
        if name in RESERVED:  # dbt renders contract DDL unquoted; these need quoting in Postgres
            col["quote"] = True
        if not col.get("description"):
            desc = describe(name)
            if desc:
                col["description"] = desc
        # keep key order stable: name, data_type, description, then the rest
        ordered = {k: col[k] for k in ("name", "data_type", "description") if k in col}
        ordered.update({k: v for k, v in col.items() if k not in ordered})
        columns.append(ordered)
    entry["columns"] = columns
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))
    return len(columns)


def main(argv: list[str]) -> None:
    models = argv or sorted(p.stem for p in MODELS.glob("*.sql"))
    with psycopg.connect(settings().database_url) as conn:
        for model in models:
            n = refresh(conn, model)
            print(f"{model}: {n} columns -> {MODELS / (model + '.yml')}")


if __name__ == "__main__":
    main(sys.argv[1:])
