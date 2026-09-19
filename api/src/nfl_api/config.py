"""Runtime settings, read from environment variables (docker compose passes them from .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_key: str | None = None  # None = no auth; set NFL_API_KEY to require X-API-Key
    cors_origins: tuple[str, ...] = ()
    pool_min: int = 1
    pool_max: int = 4


def settings() -> Settings:
    return Settings(
        database_url=os.environ.get("NFL_DATABASE_URL", "postgresql://nfl:nfl@localhost:5432/nfl"),
        api_key=os.environ.get("NFL_API_KEY") or None,  # compose passes "" when unset
        cors_origins=tuple(
            o.strip() for o in os.environ.get("NFL_API_CORS_ORIGINS", "").split(",") if o.strip()
        ),
    )
