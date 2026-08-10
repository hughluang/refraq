"""refraq FastAPI application entry point."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.admin.role_store import get_role_store
from backend.admin.roles import SUPER_ADMIN_KEY, seed_roles
from backend.admin.schemas.auth import ErrorResponse
from backend.admin.security import hash_password
from backend.admin.user_store import get_user_store
from backend.core.config import Settings, get_settings
from backend.core.errors import AppError
from backend.core.health import router as health_router

# Bind Celery before importing domain routers/tasks that use `@shared_task`.
import backend.worker.app as _celery_runtime  # noqa: F401

from backend.admin.routers.account import router as account_router
from backend.admin.routers.audit import router as audit_router
from backend.admin.routers.auth import router as auth_router_instance
from backend.admin.routers.console import router as console_router
from backend.admin.routers.roles import router as roles_router
from backend.admin.routers.settings import router as settings_router
from backend.admin.routers.tokens import router as tokens_router
from backend.admin.routers.users import router as users_router
from backend.jobs.routers.jobs import router as jobs_mechanism_router
from backend.metadata.routers.business_domains import router as business_domains_router
from backend.metadata.routers.catalog import router as metadata_catalog_router
from backend.metadata.routers.jobs import router as metadata_jobs_router
from backend.metadata.routers.query import router as metadata_query_router
from backend.metadata.routers.sources import router as sources_router

settings = get_settings()


def _bootstrap_site(target_settings: Settings) -> None:
    """Site Bootstrap: empty-store seed only. Does not align System Role permissions."""
    if os.getenv("REFRAQ_SKIP_SEED") == "1":
        return
    roles = get_role_store()
    seed_roles(roles)
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


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content=ErrorResponse(code=exc.code, message=exc.message).model_dump(),
    )


app.include_router(health_router)
app.include_router(auth_router_instance)
app.include_router(account_router)
app.include_router(users_router)
app.include_router(roles_router)
app.include_router(console_router)
app.include_router(settings_router)
app.include_router(tokens_router)
app.include_router(audit_router)
app.include_router(sources_router)
app.include_router(metadata_catalog_router)
app.include_router(business_domains_router)
app.include_router(metadata_jobs_router)
app.include_router(metadata_query_router)
app.include_router(jobs_mechanism_router)
