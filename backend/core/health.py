"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.core.config import get_settings
from backend.core.db import ping_database
from backend.core.redis_client import ping_redis


router = APIRouter(tags=["health"])

@router.get("/healthz")
def healthz() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "env": settings.refraq_env}

@router.get("/readyz")
def readyz() -> JSONResponse:
    settings = get_settings()
    if settings.store_backend == "memory":
        return JSONResponse(status_code=200, content={"status": "ready", "backend": "memory"})
    try:

        ping_database()
        ping_redis()
    except Exception as exc:  # noqa: BLE001 — readiness must surface dependency errors
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "detail": str(exc)},
        )
    return JSONResponse(
        status_code=200,
        content={"status": "ready", "backend": "persistent"},
    )
