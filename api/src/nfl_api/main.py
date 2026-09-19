"""App factory. `app` at module level is what uvicorn serves; tests call create_app(settings)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from . import config
from .auth import require_api_key
from .config import Settings
from .db import get_repository, make_pool
from .repository import PostgresRepository, Repository
from .routers import dimensions, games, ops
from .schemas import Health


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or config.settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = make_pool(s)
        pool.open(wait=False)
        app.state.repository = PostgresRepository(pool)
        try:
            yield
        finally:
            pool.close()

    app = FastAPI(
        title="NFL warehouse API",
        version="0.1.0",
        description="Read-only access to the nfl.* marts and ops.* run history.",
        lifespan=lifespan,
    )
    app.state.settings = s

    if s.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(s.cors_origins),
            allow_methods=["GET"],
            allow_headers=["X-API-Key"],
        )

    protected = APIRouter(dependencies=[Depends(require_api_key)])
    protected.include_router(dimensions.router, tags=["dimensions"])
    protected.include_router(games.router, tags=["games"])
    protected.include_router(ops.router, tags=["ops"])
    app.include_router(protected)

    @app.get("/health", response_model=Health, responses={503: {"model": Health}}, tags=["ops"])
    def health(repo: Annotated[Repository, Depends(get_repository)]):
        h = repo.health()
        if h.status != "ok":
            return JSONResponse(status_code=503, content=h.model_dump(mode="json"))
        return h

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(PoolTimeout)
    async def _db_unavailable(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "database unavailable"})

    @app.exception_handler(psycopg.errors.QueryCanceled)
    async def _query_timeout(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=504, content={"detail": "query timed out"})

    return app


app = create_app()
