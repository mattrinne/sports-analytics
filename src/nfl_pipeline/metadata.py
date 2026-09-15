"""Data dictionary and column labels for the clean schema, materialized into the metadata schema.

Inputs:
  data/metadata/tables.yaml     table docs + per-table defaults (see config.metadata_dir)
  data/metadata/labels.yaml     controlled vocabulary per axis
  data/metadata/rules.yaml      ordered regex rules assigning labels
  data/metadata/overrides.yaml  per-column descriptions and label corrections (win over everything)
  nflverse data dictionaries    downloaded from GitHub at build time, parsed in memory, never stored

Output tables: metadata.tables, metadata.columns, metadata.labels and the view metadata.column_labels.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl
import psycopg
import yaml
from psycopg import sql

from . import db
from .config import settings
from .datasets import REGISTRY

log = logging.getLogger(__name__)

AXES = ("role", "side", "entity", "category")

NFLVERSE_DICT_BASE = "https://raw.githubusercontent.com/nflverse/nflreadr/main/data-raw/"
NFLVERSE_DICT_FILES = (
    "dictionary_pbp.csv",
    "dictionary_schedules.csv",
    "dictionary_participation.csv",
    "dictionary_rosters.csv",
    "dictionary_players.csv",
    "dictionary_depth_charts.csv",
    "dictionary_player_stats.json",
    "dictionary_team_stats.json",
)

# Role assigned from the Postgres type when no rule says otherwise.
_ROLE_BY_TYPE = {
    "bigint": "measure",
    "integer": "measure",
    "smallint": "measure",
    "double precision": "measure",
    "real": "measure",
    "numeric": "measure",
    "boolean": "flag",
    "text": "dimension",
    "date": "time",
    "time without time zone": "time",
    "timestamp with time zone": "time",
    "timestamp without time zone": "time",
}


# ----------------------------------------------------------------------------- curated inputs


def _yaml(path: Path):
    with path.open() as f:
        return yaml.safe_load(f) or {}


def parse_dictionary(name: str, text: str) -> dict[str, tuple[str, str | None]]:
    """Normalize the three nflverse dictionary formats to {field: (description, source_type)}."""
    out: dict[str, tuple[str, str | None]] = {}
    if name.endswith(".json"):
        for row in json.loads(text):
            out[row["field"].strip().lower()] = (
                (row.get("description") or "").strip(),
                row.get("data_type"),
            )
        return out
    reader = csv.DictReader(io.StringIO(text))
    cols = {c.lower(): c for c in reader.fieldnames or []}
    f_col, d_col = cols["field"], cols["description"]
    t_col = cols.get("type") or cols.get("data_type")
    for row in reader:
        field_name = (row[f_col] or "").strip().lower()
        if field_name:
            out[field_name] = ((row[d_col] or "").strip(), row[t_col] if t_col else None)
    return out


def read_dictionary(path: Path) -> dict[str, tuple[str, str | None]]:
    return parse_dictionary(path.name, path.read_text())


def fetch_dictionaries(files: tuple[str, ...] = NFLVERSE_DICT_FILES) -> dict[str, str]:
    """Download the nflverse dictionaries into memory. Nothing is written to disk."""
    out: dict[str, str] = {}
    for fname in files:
        url = NFLVERSE_DICT_BASE + fname
        req = urllib.request.Request(
            url, headers={"User-Agent": "nfl-pipeline/0.1 (metadata build)"}
        )
        delay = 5
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    out[fname] = resp.read().decode()
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                if attempt == 3:
                    raise RuntimeError(f"could not download {url}: {exc}") from exc
                log.warning("download %s failed (%s); retrying in %ss", fname, exc, delay)
                time.sleep(delay)
                delay *= 2
    return out


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: re.Pattern
    tables: frozenset[str] | None  # None = all tables
    set: dict[str, str | None]  # axis -> label (None clears)
    tags: tuple[str, ...] = ()

    def matches(self, table: str, column: str) -> bool:
        return (self.tables is None or table in self.tables) and bool(self.pattern.search(column))


def load_rules(path: Path) -> list[Rule]:
    rules = []
    for i, raw in enumerate(_yaml(path).get("rules", [])):
        tables = raw.get("tables", "*")
        rules.append(
            Rule(
                id=str(raw.get("id") or f"rule_{i}"),
                pattern=re.compile(raw["match"]),
                tables=None if tables == "*" else frozenset(tables),
                set={k: v for k, v in (raw.get("set") or {}).items()},
                tags=tuple(raw.get("tags") or ()),
            )
        )
    return rules


@dataclass
class Override:
    tables: frozenset[str] | None
    column: str
    description: str | None = None
    set: dict[str, str | None] = field(default_factory=dict)
    tags: tuple[str, ...] = ()


def load_overrides(path: Path) -> list[Override]:
    out = []
    for raw in _yaml(path).get("columns", []):
        tables = raw.get("tables") or ([raw["table"]] if raw.get("table") else "*")
        out.append(
            Override(
                tables=None if tables == "*" else frozenset(tables),
                column=raw["column"],
                description=raw.get("description"),
                set=dict(raw.get("set") or {}),
                tags=tuple(raw.get("tags") or ()),
            )
        )
    return out


@dataclass
class Curated:
    tables: dict
    labels: dict[str, dict[str, str]]
    rules: list[Rule]
    overrides: list[Override]
    dictionaries: dict[str, dict[str, tuple[str, str | None]]]  # table -> merged dictionary

    @classmethod
    def load(cls, root: Path, dictionary_texts: dict[str, str]) -> Curated:
        """root = data/metadata; dictionary_texts = {nflverse file name: file contents}."""
        tables = _yaml(root / "tables.yaml")
        parsed = {name: parse_dictionary(name, text) for name, text in dictionary_texts.items()}
        dicts = {}
        for name, meta in tables.items():
            merged: dict[str, tuple[str, str | None]] = {}
            for fname in meta.get("dictionaries") or []:
                if fname not in parsed:
                    raise FileNotFoundError(
                        f"tables.yaml: {name} references unknown dictionary {fname!r}"
                    )
                merged.update(parsed[fname])
            dicts[name] = merged
        return cls(
            tables=tables,
            labels=_yaml(root / "labels.yaml"),
            rules=load_rules(root / "rules.yaml"),
            overrides=load_overrides(root / "overrides.yaml"),
            dictionaries=dicts,
        )

    def validate_vocabulary(self) -> list[str]:
        problems = []
        for rule in self.rules:
            for axis, label in rule.set.items():
                if axis not in AXES:
                    problems.append(f"rule {rule.id}: unknown axis {axis!r}")
                elif label is not None and label not in self.labels.get(axis, {}):
                    problems.append(f"rule {rule.id}: unknown {axis} label {label!r}")
        for ov in self.overrides:
            for axis, label in ov.set.items():
                if axis not in AXES:
                    problems.append(f"override {ov.column}: unknown axis {axis!r}")
                elif label is not None and label not in self.labels.get(axis, {}):
                    problems.append(f"override {ov.column}: unknown {axis} label {label!r}")
            if ov.tables:
                for t in ov.tables - set(self.tables):
                    problems.append(f"override {ov.column}: unknown table {t!r}")
        for name in REGISTRY:
            if REGISTRY[name].table not in self.tables:
                problems.append(
                    f"tables.yaml: missing entry for registry table {REGISTRY[name].table!r}"
                )
        return problems


# ----------------------------------------------------------------------------- labeling


@dataclass
class ColumnMeta:
    table: str
    column: str
    ordinal: int
    data_type: str
    null_fraction: float | None = None
    description: str | None = None
    description_source: str | None = None
    labels: dict[str, str | None] = field(default_factory=lambda: dict.fromkeys(AXES))
    tags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def label_column(col: ColumnMeta, curated: Curated) -> ColumnMeta:
    """Defaults -> rules in order -> overrides. Mutates and returns col."""
    table_meta = curated.tables.get(col.table, {})
    col.labels["role"] = _ROLE_BY_TYPE.get(col.data_type)
    col.labels["entity"] = table_meta.get("default_entity")

    dictionary = curated.dictionaries.get(col.table, {})
    if col.column in dictionary and dictionary[col.column][0]:
        col.description, col.description_source = dictionary[col.column][0], "nflverse"

    for rule in curated.rules:
        if rule.matches(col.table, col.column):
            col.labels.update(rule.set)
            for t in rule.tags:
                if t not in col.tags:
                    col.tags.append(t)
            col.sources.append(f"rule:{rule.id}")

    for ov in curated.overrides:
        if ov.column == col.column and (ov.tables is None or col.table in ov.tables):
            if ov.description:
                col.description, col.description_source = ov.description, "curated"
            col.labels.update(ov.set)
            for t in ov.tags:
                if t not in col.tags:
                    col.tags.append(t)
            col.sources.append("override")
    return col


# ----------------------------------------------------------------------------- introspection


def introspect_columns(conn: psycopg.Connection, schema: str) -> list[ColumnMeta]:
    rows = conn.execute(
        """
        SELECT c.table_name, c.column_name, c.ordinal_position, c.data_type, s.null_frac
        FROM information_schema.columns c
        LEFT JOIN pg_stats s
               ON s.schemaname = c.table_schema AND s.tablename = c.table_name
              AND s.attname = c.column_name
        WHERE c.table_schema = %s
        ORDER BY c.table_name, c.ordinal_position
        """,
        (schema,),
    ).fetchall()
    return [
        ColumnMeta(
            table=t,
            column=c,
            ordinal=o,
            data_type=d,
            null_fraction=float(n) if n is not None else None,
        )
        for t, c, o, d, n in rows
    ]


def table_stats(
    conn: psycopg.Connection, schema: str, table: str
) -> tuple[int, dt.datetime | None]:
    fq = sql.Identifier(schema, table)
    count = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(fq)).fetchone()[0]
    has_loaded = conn.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND column_name='_loaded_at'",
        (schema, table),
    ).fetchone()
    loaded = None
    if has_loaded:
        loaded = conn.execute(sql.SQL("SELECT max(_loaded_at) FROM {}").format(fq)).fetchone()[0]
    return count, loaded


# ----------------------------------------------------------------------------- build


_DDL = {
    "labels": """
        CREATE TABLE {schema}.labels (
            axis text NOT NULL,
            label text NOT NULL,
            description text,
            sort_order integer,
            PRIMARY KEY (axis, label)
        )""",
    "tables": """
        CREATE TABLE {schema}.tables (
            table_schema text NOT NULL,
            table_name text NOT NULL,
            dataset text,
            description text,
            grain text,
            default_entity text,
            partitioned boolean,
            partition_key text,
            min_season integer,
            loader text,
            source text,
            source_url text,
            column_count integer,
            row_count bigint,
            last_loaded_at timestamptz,
            refreshed_at timestamptz NOT NULL,
            PRIMARY KEY (table_schema, table_name)
        )""",
    "columns": """
        CREATE TABLE {schema}.columns (
            table_schema text NOT NULL,
            table_name text NOT NULL,
            column_name text NOT NULL,
            ordinal_position integer NOT NULL,
            data_type text NOT NULL,
            description text,
            description_source text,
            role text,
            side text,
            entity text,
            category text,
            tags text[] NOT NULL DEFAULT '{{}}',
            label_source text,
            null_fraction double precision,
            refreshed_at timestamptz NOT NULL,
            PRIMARY KEY (table_schema, table_name, column_name)
        )""",
}


def _pg_array(items: list[str]) -> str:
    return "{" + ",".join('"' + i.replace('"', '\\"') + '"' for i in items) + "}"


def assemble(
    conn: psycopg.Connection, curated: Curated, schema: str
) -> tuple[list[ColumnMeta], dict]:
    cols = [label_column(c, curated) for c in introspect_columns(conn, schema)]
    tables = sorted({c.table for c in cols})
    stats = {t: table_stats(conn, schema, t) for t in tables}
    return cols, stats


def build_metadata() -> dict:
    cfg = settings()
    curated = Curated.load(cfg.metadata_dir, fetch_dictionaries())
    problems = curated.validate_vocabulary()
    if problems:
        raise ValueError("metadata vocabulary errors:\n  " + "\n  ".join(problems))

    now = dt.datetime.now(dt.UTC)
    with db.connect() as conn:
        conn.execute("ANALYZE")  # refresh pg_stats null fractions; cheap at this size
        cols, stats = assemble(conn, curated, cfg.clean_schema)
        by_table = {REGISTRY[n].table: REGISTRY[n] for n in REGISTRY}

        labels_df = pl.DataFrame(
            [
                {"axis": axis, "label": label, "description": desc, "sort_order": i}
                for axis, labels in curated.labels.items()
                for i, (label, desc) in enumerate(labels.items())
            ]
        )
        tables_df = pl.DataFrame(
            [
                {
                    "table_schema": cfg.clean_schema,
                    "table_name": t,
                    "dataset": by_table[t].name if t in by_table else None,
                    "description": curated.tables.get(t, {}).get("description"),
                    "grain": curated.tables.get(t, {}).get("grain"),
                    "default_entity": curated.tables.get(t, {}).get("default_entity"),
                    "partitioned": by_table[t].partitioned if t in by_table else None,
                    "partition_key": "season"
                    if t in by_table and by_table[t].partitioned
                    else None,
                    "min_season": by_table[t].min_season if t in by_table else None,
                    "loader": f"nflreadpy.{by_table[t].loader}" if t in by_table else None,
                    "source": curated.tables.get(t, {}).get("source"),
                    "source_url": curated.tables.get(t, {}).get("source_url"),
                    "column_count": sum(1 for c in cols if c.table == t),
                    "row_count": stats[t][0],
                    "last_loaded_at": stats[t][1],
                    "refreshed_at": now,
                }
                for t in sorted(stats)
            ]
        )
        columns_df = pl.DataFrame(
            [
                {
                    "table_schema": cfg.clean_schema,
                    "table_name": c.table,
                    "column_name": c.column,
                    "ordinal_position": c.ordinal,
                    "data_type": c.data_type,
                    "description": c.description,
                    "description_source": c.description_source,
                    "role": c.labels["role"],
                    "side": c.labels["side"],
                    "entity": c.labels["entity"],
                    "category": c.labels["category"],
                    "tags": _pg_array(c.tags),
                    "label_source": ",".join(c.sources) or None,
                    "null_fraction": c.null_fraction,
                    "refreshed_at": now,
                }
                for c in cols
            ]
        )

        db.lock_table(conn, cfg.metadata_schema, "columns")
        db.ensure_schema(conn, cfg.metadata_schema)
        for name in ("labels", "tables", "columns"):
            conn.execute(
                sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                    sql.Identifier(cfg.metadata_schema, name)
                )
            )
            conn.execute(_DDL[name].format(schema=cfg.metadata_schema))
        db.copy_df(conn, cfg.metadata_schema, "labels", labels_df)
        db.copy_df(conn, cfg.metadata_schema, "tables", tables_df)
        db.copy_df(conn, cfg.metadata_schema, "columns", columns_df)
        db.apply_sql_dir(conn, cfg.sql_dir / "metadata")
        conn.commit()

    summary = coverage(cols)
    log.info("metadata built: %s", summary)
    return summary


def coverage(cols: list[ColumnMeta]) -> dict:
    return {
        "tables": len({c.table for c in cols}),
        "columns": len(cols),
        "missing_description": sum(1 for c in cols if not c.description),
        "missing_role": sum(1 for c in cols if not c.labels["role"]),
        "missing_entity": sum(1 for c in cols if not c.labels["entity"]),
        "missing_category": sum(1 for c in cols if not c.labels["category"]),
        "missing_side": sum(1 for c in cols if not c.labels["side"]),
    }


def lint_metadata() -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors: vocabulary problems, columns without role/entity,
    overrides pointing at columns that don't exist. Warnings: missing description/category/side."""
    cfg = settings()
    curated = Curated.load(cfg.metadata_dir, fetch_dictionaries())
    errors = curated.validate_vocabulary()
    with db.connect() as conn:
        cols, _ = assemble(conn, curated, cfg.clean_schema)
    existing = {(c.table, c.column) for c in cols}
    tables = {c.table for c in cols}
    for ov in curated.overrides:
        targets = ov.tables or tables
        for t in targets:
            if t in tables and (t, ov.column) not in existing:
                errors.append(f"override {t}.{ov.column}: column does not exist")
    warnings = []
    for c in cols:
        if not c.labels["role"]:
            errors.append(f"{c.table}.{c.column}: no role")
        if not c.labels["entity"] and c.labels["role"] != "system":
            errors.append(f"{c.table}.{c.column}: no entity")
        if not c.description:
            warnings.append(f"{c.table}.{c.column}: no description")
        if not c.labels["category"]:
            warnings.append(f"{c.table}.{c.column}: no category")
    return errors, warnings
