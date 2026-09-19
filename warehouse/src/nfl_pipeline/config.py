"""Runtime settings, read from environment variables (docker compose passes them from .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    start_season: int
    data_dir: Path  # curated inputs: data/coaching_staff_overrides.csv, data/seeds/*.csv
    dbt_dir: Path  # dbt project: clean + nfl layers
    staging_schema: str = "staging"  # landing zone, truncatable; clean is the durable copy
    clean_schema: str = "clean"
    analytics_schema: str = "nfl"


def settings() -> Settings:
    root = Path(__file__).resolve().parents[2]
    return Settings(
        database_url=os.environ.get("NFL_DATABASE_URL", "postgresql://nfl:nfl@localhost:5432/nfl"),
        start_season=int(os.environ.get("NFL_START_SEASON", "2010")),
        data_dir=Path(os.environ.get("NFL_DATA_DIR", root / "data")),
        dbt_dir=Path(os.environ.get("NFL_DBT_DIR", root / "dbt")),
    )
