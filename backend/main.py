"""refraq FastAPI application entry point."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.admin.errors import AuthError
from backend.admin.security import hash_password
from backend.core.config import Settings, get_settings
from backend.repositories.role_store import SUPER_ADMIN_KEY, get_role_store
from backend.repositories.user_store import get_user_store
from backend.routers.auth import router as auth_router_instance
from backend.routers.console import router as console_router
from backend.routers.health import router as health_router
from backend.routers.roles import router as roles_router
from backend.routers.settings import router as settings_router
from backend.routers.users import router as users_router
from backend.schemas.auth import ErrorResponse

settings = get_settings()


def _bootstrap_site(target_settings: Settings) -> None:
    """Site Bootstrap: empty-store seed only. Does not align System Role permissions."""
    if os.getenv("REFRAQ_SKIP_SEED") == "1":
        return
    roles = get_role_store()
    roles.seed_defaults()
    users = get_user_store()
    if users.count() > 0:
        return
    super_admin = roles.get_by_key(SUPER_ADMIN_KEY)
    if super_admin is None:
        return
    password_hash = hash_password(target_settings.initial_admin_password)
    users.create_user(
        account=target_settings.initial_admin_account,
        display_name=target_settings.initial_admin_account,
        password_hash=password_hash,
        role_id=super_admin.id,
        status="active",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _bootstrap_site(settings)
    yield


app = FastAPI(
    title="refraq Backend",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(AuthError)
async def auth_error_handler(_: Request, exc: AuthError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content=ErrorResponse(code=exc.code, message=exc.message).model_dump(),
    )


app.include_router(health_router)
app.include_router(auth_router_instance)
app.include_router(users_router)
app.include_router(roles_router)
app.include_router(console_router)
app.include_router(settings_router)
