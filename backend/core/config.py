"""Environment-driven settings for the Management Foundation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

StoreBackend = Literal["memory", "persistent"]

# backend/core/config.py -> repo root (cwd-independent for debug / alternate launches)
_REPO_ROOT = Path(__file__).resolve().parents[2]
# Later files override earlier ones — backend/.env wins over repo-root .env.
_ENV_FILES = tuple(
    str(path)
    for path in (_REPO_ROOT / ".env", _REPO_ROOT / "backend" / ".env")
    if path.is_file()
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES or None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    refraq_env: str = Field(default="dev", validation_alias="REFRAQ_ENV")
    refraq_api_host: str = Field(default="127.0.0.1", validation_alias="REFRAQ_API_HOST")
    refraq_api_port: int = Field(default=8000, validation_alias="REFRAQ_API_PORT")
    store_backend: StoreBackend = Field(
        default="persistent",
        validation_alias="REFRAQ_STORE_BACKEND",
    )
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    redis_url: str | None = Field(default=None, validation_alias="REDIS_URL")
    admin_session_secret: str = Field(
        default="change-me",
        validation_alias="ADMIN_SESSION_SECRET",
    )
    admin_session_ttl_hours: int = Field(
        default=8,
        validation_alias="ADMIN_SESSION_TTL_HOURS",
    )
    initial_admin_account: str = Field(
        default="root",
        validation_alias="INITIAL_ADMIN_ACCOUNT",
    )
    initial_admin_password: str = Field(
        default="change-me",
        validation_alias="INITIAL_ADMIN_PASSWORD",
    )
    refraq_secrets_master_key: str | None = Field(
        default=None,
        validation_alias="REFRAQ_SECRETS_MASTER_KEY",
    )
    celery_broker_url: str | None = Field(
        default=None,
        validation_alias="CELERY_BROKER_URL",
    )
    refraq_job_worker_concurrency: int = Field(
        default=1,
        validation_alias="REFRAQ_JOB_WORKER_CONCURRENCY",
    )
    refraq_job_running_timeout_sec: int = Field(
        default=3600,
        validation_alias="REFRAQ_JOB_RUNNING_TIMEOUT_SEC",
    )
    refraq_catalog_fail_safe_threshold: float = Field(
        default=0.75,
        validation_alias="REFRAQ_CATALOG_FAIL_SAFE_THRESHOLD",
    )
    refraq_query_timeout_sec: int = Field(
        default=30,
        validation_alias="REFRAQ_QUERY_TIMEOUT_SEC",
    )
    refraq_query_max_rows: int = Field(
        default=1000,
        validation_alias="REFRAQ_QUERY_MAX_ROWS",
    )

    @model_validator(mode="after")
    def _require_backing_urls_when_persistent(self) -> Settings:
        if self.store_backend == "persistent":
            missing: list[str] = []
            if not self.database_url:
                missing.append("DATABASE_URL")
            if not self.redis_url:
                missing.append("REDIS_URL")
            if missing:
                raise ValueError(
                    "persistent Store Backend requires "
                    + ", ".join(missing)
                    + "; memory mode is for automated tests only"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
