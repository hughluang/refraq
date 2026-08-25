"""refraq FastAPI application entry point."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.admin.role_store import get_role_store
from backend.admin.roles import SUPER_ADMIN_KEY, seed_roles
from backend.admin.security import hash_password
from backend.admin.user_store import get_user_store
from backend.core.config import Settings, get_settings
from backend.core.errors import (
    CODE_INTERNAL_ERROR,
    CODE_REQUEST_INVALID,
    DETAIL_INTERNAL_ERROR,
    DETAIL_REQUEST_INVALID,
    AppError,
    http_status_problem_code,
    problem_response,
    validation_field_errors,
)
from backend.core.health import router as health_router
from backend.core.request_id import (
    RequestIdMiddleware,
    SCOPE_KEY,
    get_request_id,
    install_request_id_log_filter,
)

# Bind Celery before importing domain routers/tasks that use `@shared_task`.
import backend.worker.app as _celery_runtime  # noqa: F401

from backend.admin.routers.account import router as account_router
from backend.admin.routers.audit import router as audit_router
from backend.admin.routers.auth import router as auth_router_instance
from backend.admin.branding.router import router as branding_router
from backend.admin.routers.console import router as console_router
from backend.admin.routers.roles import router as roles_router
from backend.admin.system_parameters.router import router as settings_router
from backend.admin.routers.tokens import router as tokens_router
from backend.admin.routers.users import router as users_router
from backend.admin.federation.router import router as federation_router
from backend.jobs.api import bind_schedule_name_store
from backend.jobs.routers.jobs import router as jobs_mechanism_router
from backend.worker.routers.schedules import router as schedules_mechanism_router
from backend.worker.schedules import get_schedule_store
from backend.metadata.routers.business_domains import router as business_domains_router
from backend.metadata.routers.catalog import router as metadata_catalog_router
from backend.metadata.routers.query import router as metadata_query_router
from backend.metadata.routers.schedules import router as metadata_schedules_router
from backend.metadata.routers.sources import router as sources_router
from backend.metadata.routers.structure_diffs import router as structure_diffs_router
from backend.metadata.routers.type_mappings import router as type_mappings_router
from backend.metadata.type_mappings.seeds import ensure_product_type_mappings
from backend.worker.api import ensure_system_schedules
from backend.worker.parameters import assemble_system_parameters

# Composition injects the Scheduled Task name adapter so jobs never imports worker.
bind_schedule_name_store(get_schedule_store)

settings = get_settings()
logger = logging.getLogger(__name__)
install_request_id_log_filter()


def _bootstrap_site(target_settings: Settings) -> None:
    """Site Bootstrap: empty-store seed only. Does not run Foundation Upgrade."""
    assemble_system_parameters()
    ensure_system_schedules()
    if os.getenv("REFRAQ_SKIP_SEED") == "1":
        return
    roles = get_role_store()
    seed_roles(roles)
    ensure_product_type_mappings()
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
async def app_error_handler(_request: Request, exc: AppError) -> object:
    return problem_response(
        status=exc.http_status,
        code=exc.code,
        detail=exc.message,
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    _request: Request, exc: RequestValidationError
) -> object:
    return problem_response(
        status=422,
        code=CODE_REQUEST_INVALID,
        detail=DETAIL_REQUEST_INVALID,
        details=validation_field_errors(exc.errors()),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> object:
    return problem_response(
        status=exc.status_code,
        code=http_status_problem_code(exc.status_code),
        detail=exc.detail,
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> object:
    logger.exception("Unhandled error: %s", exc)
    # FastAPI binds Exception to ServerErrorMiddleware, after RequestIdMiddleware resets ContextVar.
    rid = get_request_id()
    if not rid:
        scoped = request.scope.get(SCOPE_KEY)
        rid = scoped if isinstance(scoped, str) else ""
    return problem_response(
        status=500,
        code=CODE_INTERNAL_ERROR,
        detail=DETAIL_INTERNAL_ERROR,
        request_id=rid,
    )


app.include_router(health_router)
app.include_router(auth_router_instance)
app.include_router(account_router)
app.include_router(users_router)
app.include_router(federation_router)
app.include_router(roles_router)
app.include_router(console_router)
app.include_router(settings_router)
app.include_router(branding_router)
app.include_router(tokens_router)
app.include_router(audit_router)
app.include_router(sources_router)
app.include_router(metadata_catalog_router)
app.include_router(business_domains_router)
app.include_router(type_mappings_router)
app.include_router(metadata_schedules_router)
app.include_router(structure_diffs_router)
app.include_router(metadata_query_router)
app.include_router(jobs_mechanism_router)
app.include_router(schedules_mechanism_router)

app.add_middleware(RequestIdMiddleware)
