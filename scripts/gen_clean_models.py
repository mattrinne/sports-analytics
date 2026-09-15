"""Generate dbt/models/clean/<table>.sql: a typed copy of every staging table.

The clean layer is a column-for-column copy of `staging` (nothing dropped, nothing derived) with
the types nflverse's parquet files lose fixed: 0/1 doubles -> boolean, whole-number doubles and
bigints -> smallint/integer, ISO text dates -> date/timestamptz. Every model is an incremental
merge on a primary key (natural key where the data has one, otherwise a `_row_id` hash), so
staging can be truncated after a load without losing anything.

Run against a populated staging schema (0/1 flags are detected from pg_stats):

    uv run python scripts/gen_clean_models.py            # every table in staging
    uv run python scripts/gen_clean_models.py pbp teams

Then `uv run python scripts/gen_dbt_columns.py` to refresh the column yml, and
`dbt build --full-refresh` if any type changed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from nfl_pipeline.config import settings

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "dbt" / "models" / "clean"

# Primary key per table. A list = natural key; None = md5 hash of the *_ROW_ID_COLS columns.
PRIMARY_KEYS: dict[str, list[str] | None] = {
    "schedules": ["game_id"],
    "teams": ["team_abbr"],
    "players": ["gsis_id"],
    "pbp": ["game_id", "play_id"],
    "participation": ["nflverse_game_id", "play_id"],
    "team_stats_week": ["season", "week", "team"],
    "officials": ["game_id", "official_id"],
    # no NULL-free natural key in the source -> hashed _row_id
    "player_stats_week": None,  # 67 rows/season have NULL player_id (team placeholders)
    "rosters": None,  # a few rows without gsis_id
    "rosters_weekly": None,
    "depth_charts": None,  # two formats, neither unique on its obvious key
    "coaching_staff": None,  # start_date is NULL for season-long holders
}
# Columns hashed into _row_id when PRIMARY_KEYS[table] is None. "*" = every column except
# _loaded_at (exact duplicate rows collapse, anything else survives).
ROW_ID_COLS: dict[str, list[str] | str] = {
    "player_stats_week": ["season", "week", "team", "player_id", "player_display_name", "position"],
    # a player can appear twice in a week (e.g. status TRD then RES) and rows can differ only in
    # secondary columns, so hash everything: the copy stays exact, only true duplicates collapse
    "rosters": "*",
    "rosters_weekly": "*",
    "depth_charts": "*",  # two formats, ~1.7k exact duplicates, no stable natural key
    "coaching_staff": ["season", "team", "role", "coach", "start_date"],
}

# Type fixes by column name (applied to every table that has the column).
DATE_COLS = {"gameday", "game_date", "birth_date"}
TIMESTAMPTZ_COLS = {"time_of_day", "dt", "drive_real_start_time", "end_clock_time"}
TIME_COLS = {"gametime"}
INTEGER_COLS = {
    "play_id",
    "quarter_seconds_remaining",
    "half_seconds_remaining",
    "game_seconds_remaining",
    "drive_play_id_started",
    "drive_play_id_ended",
    "gsis",
    "pff",
    "ftn",
}
# bigint/whole-number double columns that fit smallint get smallint; the rest integer.
# Yards and other counts that can exceed 32767 over a game never do, but ids can -> integer.
SMALLINT_MAX = 32767
# Columns that pg_stats sees as {0,1} but are measures, not flags.
NOT_FLAGS = {
    "comp_air_epa",
    "comp_yac_epa",
    "air_wpa",
    "comp_air_wpa",
    "comp_yac_wpa",
    "fumble_recovery_1_yards",
    "fumble_recovery_2_yards",
    "play_clock",
    "depth_team",
    "pos_rank",
    "pos_slot",
    "week",
    "down",
    "qtr",
}
KEEP_TEXT = {"desc", "time", "yrdln", "start_time", "play_clock", "jersey_number"}


def q(name: str) -> str:
    return f'"{name}"' if name in {"desc", "time"} else name


def columns(conn, schema, table):
    return conn.execute(
        """
        select column_name, data_type
        from information_schema.columns
        where table_schema = %s and table_name = %s
        order by ordinal_position
        """,
        (schema, table),
    ).fetchall()


BIGINT_FLAGS = {"overtime", "div_game"}


def flag_columns(conn, schema, table, cols) -> set[str]:
    """Double-precision columns whose every non-null value is 0 or 1 (nflfastR encodes flags that
    way), plus the few bigint flags named in BIGINT_FLAGS. Checked against the data, not pg_stats."""
    cands = [c for c, t in cols if t == "double precision" and c not in NOT_FLAGS]
    if not cands:
        return set()
    checks = ", ".join(f"bool_and({q(c)} in (0, 1)) and count({q(c)}) > 0" for c in cands)
    row = conn.execute(f"select {checks} from {schema}.{table}").fetchone()
    flags = {c for c, ok in zip(cands, row) if ok}
    return flags | {c for c, t in cols if t == "bigint" and c in BIGINT_FLAGS}


def whole_number_doubles(conn, schema, table, cols) -> dict[str, int]:
    """Double columns that hold only whole numbers -> their max abs value (for smallint/integer)."""
    doubles = [c for c, t in cols if t == "double precision"]
    if not doubles:
        return {}
    checks = ", ".join(
        f"bool_and({q(c)} = floor({q(c)})) as f_{i}, max(abs({q(c)})) as m_{i}"
        for i, c in enumerate(doubles)
    )
    row = conn.execute(f"select {checks} from {schema}.{table}").fetchone()
    out = {}
    for i, c in enumerate(doubles):
        whole, mx = row[2 * i], row[2 * i + 1]
        if whole:
            out[c] = int(mx or 0)
    return out


def max_abs_bigints(conn, schema, table, cols) -> dict[str, int]:
    ints = [c for c, t in cols if t == "bigint"]
    if not ints:
        return {}
    row = conn.execute(
        f"select {', '.join(f'max(abs({q(c)}))' for c in ints)} from {schema}.{table}"
    ).fetchone()
    return {c: int(v or 0) for c, v in zip(ints, row)}


def cast_for(col, dtype, flags, whole_doubles, big_max) -> tuple[str, str]:
    """Return (expression, target type) for one column."""
    if col in KEEP_TEXT and dtype == "text":
        return q(col), "text"
    if col in flags:
        return f"({col} = 1)", "boolean"
    if dtype == "text" and col in DATE_COLS:
        return f"{col}::date", "date"
    if dtype == "text" and col in TIMESTAMPTZ_COLS:
        return f"{col}::timestamptz", "timestamptz"
    if dtype == "text" and col in TIME_COLS:
        return f"{col}::time", "time"
    if dtype == "double precision" and col in whole_doubles:
        t = "integer" if col in INTEGER_COLS or whole_doubles[col] > SMALLINT_MAX else "smallint"
        return f"{col}::{t}", t
    if dtype == "bigint":
        t = "integer" if col in INTEGER_COLS or big_max.get(col, 0) > SMALLINT_MAX else "smallint"
        return f"{col}::{t}", t
    if dtype == "double precision" and col in {"height", "weight"}:
        return f"round({col})::smallint", "smallint"
    return q(col), dtype


def render(table, cols, flags, whole_doubles, big_max) -> str:
    pk = PRIMARY_KEYS[table]
    lines = []
    if pk is None:
        key_cols = ROW_ID_COLS[table]
        if key_cols == "*":
            key_cols = [c for c, _ in cols if c != "_loaded_at"]
        parts = ", ".join(f"coalesce({q(c)}::text, '')" for c in key_cols)
        lines.append(f"    md5(concat_ws('|', {parts})) as _row_id,")
    for col, dtype in cols:
        expr, _ = cast_for(col, dtype, flags, whole_doubles, big_max)
        lines.append(f"    {expr:<46s} as {col}," if expr != col else f"    {col},")
    lines[-1] = lines[-1].rstrip(",")
    body = "\n".join(lines)
    dedupe = ""
    if pk is None:
        dedupe = (
            "\n-- the source key is not unique for every row: keep the latest copy of each _row_id"
        )
        select = "select distinct on (_row_id)"
        order = "\norder by _row_id, _loaded_at desc"
    else:
        select = "select"
        order = ""
    return f"""-- Typed copy of staging.{table}: every column, same names, types fixed. Generated by
-- scripts/gen_clean_models.py; edit the rules there rather than this file.{dedupe}
{select}
{body}
from {{{{ source('staging', '{table}') }}}}
where true
{{{{ only_new('_loaded_at') }}}}{order}
"""


def main(argv):
    cfg = settings()
    with psycopg.connect(cfg.database_url) as conn:
        tables = argv or [
            r[0]
            for r in conn.execute(
                "select table_name from information_schema.tables where table_schema = %s order by 1",
                (cfg.staging_schema,),
            )
        ]
        for table in tables:
            if table not in PRIMARY_KEYS:
                raise SystemExit(f"{table}: add a PRIMARY_KEYS entry first")
            cols = columns(conn, cfg.staging_schema, table)
            flags = flag_columns(conn, cfg.staging_schema, table, cols)
            whole = whole_number_doubles(conn, cfg.staging_schema, table, cols)
            big = max_abs_bigints(conn, cfg.staging_schema, table, cols)
            sql = render(table, cols, flags, whole, big)
            (MODELS / f"{table}.sql").write_text(sql)
            print(
                f"{table}: {len(cols)} columns, {len(flags)} flags, {len(whole)} whole-number doubles"
            )


if __name__ == "__main__":
    main(sys.argv[1:])
