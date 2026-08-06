"""Pytest defaults: memory Store Backend only (no silent persistent fallback)."""

from __future__ import annotations

import os

# Must run before backend.main / Settings are imported by test modules.
os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)

import pytest

from backend.admin.settings_override import reset_settings_override
from backend.core.config import reset_settings_cache
from backend.core.db import reset_db_singletons
from backend.core.redis_client import reset_redis_singleton
from backend.repositories.audit_store import reset_audit_store
from backend.repositories.role_store import reset_role_store
from backend.repositories.session_store import reset_session_store
from backend.repositories.token_store import reset_token_store
from backend.repositories.user_store import reset_user_store
from backend.metadata.jobs import reset_job_store
from backend.worker.schedules import reset_schedule_store

reset_settings_cache()
reset_settings_override()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: tests that require local Compose Postgres and Redis",
    )


@pytest.fixture(autouse=True)
def _reset_foundation_singletons() -> None:
    reset_settings_cache()
    reset_settings_override()
    reset_user_store()
    reset_role_store()
    reset_session_store()
    reset_token_store()
    reset_audit_store()
    reset_job_store()
    reset_schedule_store()
    reset_db_singletons()
    reset_redis_singleton()
    yield
    reset_user_store()
    reset_role_store()
    reset_session_store()
    reset_token_store()
    reset_audit_store()
    reset_job_store()
    reset_schedule_store()
    reset_db_singletons()
    reset_redis_singleton()
    reset_settings_override()
    reset_settings_cache()
