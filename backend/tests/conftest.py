"""Pytest defaults: memory Store Backend only (no silent persistent fallback)."""

from __future__ import annotations

import os

# Must run before backend.main / Settings are imported by test modules.
os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
# Explicit broker for Celery app construction in memory/eager tests (no invented default in core).
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
# Canonical Console host so OIDC redirect_uri is not taken from request Host.
os.environ.setdefault("REFRAQ_BROWSER_FACING_HOST", "127.0.0.1:3000")

import pytest

from backend.admin.system_parameters import reset_system_parameters
from backend.admin.branding.service import reset_branding_cache
from backend.admin.branding.store import reset_branding_store
from backend.core.config import reset_settings_cache
from backend.core.db import reset_db_singletons
from backend.core.redis_client import reset_redis_singleton
from backend.core.time import reset_clock
from backend.admin.audit_store import reset_audit_store
from backend.admin.role_store import reset_role_store
from backend.admin.session_store import reset_session_store
from backend.admin.token_store import reset_token_store
from backend.admin.user_store import reset_user_store
from backend.admin.federation.binding_store import reset_binding_store
from backend.admin.federation.handoff_store import reset_handoff_store
from backend.admin.federation.pending_store import reset_pending_store
from backend.admin.federation.provider_store import reset_provider_store
from backend.admin.federation.protocols.oidc.jwks import reset_jwks_cache
from backend.jobs.store import reset_job_store
from backend.metadata.business_domains.store import reset_business_domain_store
from backend.metadata.catalog.store import reset_catalog_store
from backend.metadata.catalog.kind_locks import reset_kind_execution_locks_for_tests
from backend.metadata.sources.store import reset_source_store
from backend.metadata.structure_diffs.store import reset_structure_diff_store
from backend.metadata.type_mappings.store import reset_type_mapping_store
from backend.worker.schedules import reset_schedule_store

reset_settings_cache()
reset_system_parameters()
reset_clock()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: tests that require local Compose Postgres and Redis",
    )


@pytest.fixture(autouse=True)
def _reset_foundation_singletons() -> None:
    reset_settings_cache()
    reset_system_parameters()
    reset_clock()
    reset_user_store()
    reset_branding_store()
    reset_branding_cache()
    reset_provider_store()
    reset_binding_store()
    reset_pending_store()
    reset_handoff_store()
    reset_jwks_cache()
    reset_role_store()
    reset_session_store()
    reset_token_store()
    reset_audit_store()
    reset_job_store()
    reset_source_store()
    reset_catalog_store()
    reset_structure_diff_store()
    reset_business_domain_store()
    reset_type_mapping_store()
    reset_schedule_store()
    reset_kind_execution_locks_for_tests()
    reset_db_singletons()
    reset_redis_singleton()
    yield
    reset_user_store()
    reset_branding_store()
    reset_branding_cache()
    reset_provider_store()
    reset_binding_store()
    reset_pending_store()
    reset_handoff_store()
    reset_jwks_cache()
    reset_role_store()
    reset_session_store()
    reset_token_store()
    reset_audit_store()
    reset_job_store()
    reset_source_store()
    reset_catalog_store()
    reset_structure_diff_store()
    reset_business_domain_store()
    reset_type_mapping_store()
    reset_schedule_store()
    reset_kind_execution_locks_for_tests()
    reset_db_singletons()
    reset_redis_singleton()
    reset_system_parameters()
    reset_settings_cache()
    reset_clock()
