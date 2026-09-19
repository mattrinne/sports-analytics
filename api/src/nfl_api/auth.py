"""Optional API key: when Settings.api_key is set, protected routes require X-API-Key."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(request: Request, key: Annotated[str | None, Security(_header)]) -> None:
    expected: str | None = request.app.state.settings.api_key
    if expected is None:
        return
    if key is None or not secrets.compare_digest(key.encode(), expected.encode()):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or missing X-API-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
