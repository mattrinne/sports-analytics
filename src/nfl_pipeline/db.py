"""Postgres helpers: schema-on-write from Polars frames via COPY, idempotent partition replace."""

from __future__ import annotations

import io
import logging
from collections.abc import Iterable, Sequence
from pathlib import Path

import polars as pl
import psycopg
from psycopg import sql

from .config import settings

log = logging.getLogger(__name__)

# Postgres type for each Polars dtype we expect from nflverse files. Ints are always BIGINT so a
# season whose file happens to carry Int64 never overflows a column created from an Int32 season.
_TEXT = "text"
_BIGINT = "bigint"
_DOUBLE = "double precision"
_BOOL = "boolean"
_DATE = "date"
_TIMESTAMPTZ = "timestamp with time zone"
_TIMESTAMP = "timestamp without time zone"

# When an existing column's type differs from an incoming frame's, the column is widened to the
# higher-ranked type. Equal rank but different type (e.g. date vs bigint) falls back to text.
_WIDEN_RANK = {_BOOL: 0, _BIGINT: 1, _DATE: 1, _TIMESTAMP: 1, _TIMESTAMPTZ: 1, _DOUBLE: 2, _TEXT: 9}


def pg_type(dtype: pl.DataType) -> str:
    if dtype.is_integer():
        return _BIGINT
    if dtype.is_float() or isinstance(dtype, pl.Decimal):
        return _DOUBLE
    if dtype == pl.Boolean:
        return _BOOL
    if dtype == pl.Date:
        return _DATE
    if isinstance(dtype, pl.Datetime):
        return _TIMESTAMPTZ if dtype.time_zone else _TIMESTAMP
    if dtype in (pl.String, pl.Utf8, pl.Categorical, pl.Null) or isinstance(dtype, pl.Enum):
        return _TEXT
    raise TypeError(f"No Postgres mapping for Polars dtype {dtype!r}")


def widened_type(existing: str, incoming: str) -> str | None:
    """Return the type the existing column should become, or None if no ALTER is needed."""
    if existing == incoming:
        return None
    er, ir = _WIDEN_RANK.get(existing, 9), _WIDEN_RANK.get(incoming, 9)
    if ir > er:
        return incoming
    if ir == er:
        return _TEXT
    return None  # incoming is narrower; COPY's text parsing handles it (e.g. int into double)


def connect() -> psycopg.Connection:
    return psycopg.connect(settings().database_url)


def lock_table(conn: psycopg.Connection, schema: str, table: str) -> None:
    """Transaction-scoped advisory lock keyed on the table name. Released at commit/rollback."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{schema}.{table}",))


def ensure_schema(conn: psycopg.Connection, schema: str) -> None:
    conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))


def table_columns(conn: psycopg.Connection, schema: str, table: str) -> dict[str, str]:
    """Column name -> Postgres data type for an existing table; empty dict if it does not exist."""
    rows = conn.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    ).fetchall()
    return {name: dtype for name, dtype in rows}


def ensure_table(conn: psycopg.Connection, schema: str, table: str, df: pl.DataFrame) -> None:
    """Create the table from the frame's schema, or add/widen columns so the frame fits."""
    existing = table_columns(conn, schema, table)
    fq = sql.Identifier(schema, table)
    if not existing:
        cols = sql.SQL(", ").join(
            sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(pg_type(t)))
            for c, t in zip(df.columns, df.dtypes)
        )
        conn.execute(sql.SQL("CREATE TABLE {} ({})").format(fq, cols))
        log.info("created %s.%s with %d columns", schema, table, df.width)
        return
    for col, dtype in zip(df.columns, df.dtypes):
        incoming = pg_type(dtype)
        if col not in existing:
            conn.execute(
                sql.SQL("ALTER TABLE {} ADD COLUMN {} {}").format(
                    fq, sql.Identifier(col), sql.SQL(incoming)
                )
            )
            log.info("added column %s.%s.%s %s", schema, table, col, incoming)
            continue
        target = widened_type(existing[col], incoming)
        if target:
            conn.execute(
                sql.SQL("ALTER TABLE {} ALTER COLUMN {} TYPE {}").format(
                    fq, sql.Identifier(col), sql.SQL(target)
                )
            )
            log.info("widened %s.%s.%s %s -> %s", schema, table, col, existing[col], target)


def copy_df(conn: psycopg.Connection, schema: str, table: str, df: pl.DataFrame) -> int:
    """Bulk-insert via COPY ... FROM STDIN (CSV). Polars' CSV is COPY-compatible: unquoted empty
    is NULL, "" is empty string, NaN/inf parse into double precision."""
    if df.height == 0:
        return 0
    buf = io.BytesIO()
    df.write_csv(buf, include_header=False)
    buf.seek(0)
    cols = sql.SQL(", ").join(sql.Identifier(c) for c in df.columns)
    stmt = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv)").format(
        sql.Identifier(schema, table), cols
    )
    with conn.cursor() as cur, cur.copy(stmt) as copy:
        while chunk := buf.read(1 << 20):
            copy.write(chunk)
    return df.height


def replace_partition(
    conn: psycopg.Connection, schema: str, table: str, df: pl.DataFrame, key: str, value: object
) -> int:
    """Delete the partition then insert the frame. Caller owns the transaction."""
    conn.execute(
        sql.SQL("DELETE FROM {} WHERE {} = %s").format(
            sql.Identifier(schema, table), sql.Identifier(key)
        ),
        (value,),
    )
    return copy_df(conn, schema, table, df)


def replace_all(conn: psycopg.Connection, schema: str, table: str, df: pl.DataFrame) -> int:
    conn.execute(sql.SQL("TRUNCATE {}").format(sql.Identifier(schema, table)))
    return copy_df(conn, schema, table, df)


def ensure_indexes(
    conn: psycopg.Connection,
    schema: str,
    table: str,
    indexes: Iterable[Sequence[str]],
    unique: Sequence[str] | None = None,
) -> None:
    for cols in indexes:
        name = f"ix_{table}_{'_'.join(cols)}"[:63]
        conn.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} ({})").format(
                sql.Identifier(name),
                sql.Identifier(schema, table),
                sql.SQL(", ").join(sql.Identifier(c) for c in cols),
            )
        )
    if unique:
        name = f"ux_{table}_{'_'.join(unique)}"[:63]
        conn.execute(
            sql.SQL("CREATE UNIQUE INDEX IF NOT EXISTS {} ON {} ({})").format(
                sql.Identifier(name),
                sql.Identifier(schema, table),
                sql.SQL(", ").join(sql.Identifier(c) for c in unique),
            )
        )


def apply_sql_dir(conn: psycopg.Connection, directory: Path) -> list[str]:
    """Execute every *.sql file in the directory in name order. Files must be idempotent."""
    applied = []
    for path in sorted(directory.glob("*.sql")):
        conn.execute(path.read_text())
        applied.append(path.name)
        log.info("applied %s", path)
    return applied


def truncate_tables(
    conn: psycopg.Connection, schema: str, tables: list[str] | None = None
) -> list[str]:
    """TRUNCATE the given tables in `schema` (all of them when None). Returns what was truncated."""
    names = tables or [
        r[0]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY 1",
            (schema,),
        )
    ]
    for name in names:
        conn.execute(sql.SQL("TRUNCATE TABLE {}").format(sql.Identifier(schema, name)))
    return names
