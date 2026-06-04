"""Liveness + readiness."""
from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from ..db import get_engine
from ..observability.metrics import db_up

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
def readyz(request: Request, response: Response) -> dict[str, object]:
    pg_ok = False
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            pg_ok = True
    except Exception:
        pg_ok = False

    cache = getattr(request.app.state, "policy_cache", None)
    cache_loaded = cache is not None and cache.is_loaded

    db_up.set(1 if pg_ok else 0)
    is_ready = pg_ok and cache_loaded

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if is_ready else "degraded",
        "postgres": pg_ok,
        "policy_cache": cache_loaded,
    }
