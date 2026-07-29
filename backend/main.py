from __future__ import annotations

from fastapi import FastAPI

from .config import get_settings

settings = get_settings()

app = FastAPI(
    title="refraq Backend",
    version="0.1.0",
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "env": settings.refraq_env}


# Future routers:
# app.include_router(...)
