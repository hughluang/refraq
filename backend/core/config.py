"""Environment-driven settings for the Management Foundation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from backend.core.browser_host import valid_browser_host
from backend.core.runtime import current_process_role

StoreBackend = Literal["memory", "persistent"]

# backend/core/config.py -> repo root (cwd-independent for debug / alternate launches)
_REPO_ROOT = Path(__file__).resolve().parents[2]
# Later files override earlier ones — backend/.env wins over repo-root .env.
_ENV_FILES = tuple(
    str(path)
    for path in (_REPO_ROOT / ".env", _REPO_ROOT / "backend" / ".env")
    if path.is_file()
)


class NotificationDeliverySettings(BaseModel):
    """Deployer-approved bounds; no production capacity is inferred."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    max_attempts_per_route: int = Field(gt=0, strict=True)
    retry_delays_seconds: tuple[float, ...]
    timeout_seconds: float = Field(gt=0)
    batch_size: int = Field(gt=0, strict=True)
    interval_seconds: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def _validate_retry_delays(self) -> NotificationDeliverySettings:
        if (
            len(self.retry_delays_seconds) != self.max_attempts_per_route - 1
            or any(delay <= 0 for delay in self.retry_delays_seconds)
        ):
            raise ValueError("Explicit notification retry delays must match attempts")
        return self


class MirrorTargetSettings(BaseModel):
    """Explicit protected target identities and bounded connection policy."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    gateway_url: SecretStr
    applier_url: SecretStr
    timeout_ms: int = Field(gt=0, le=2147483647, strict=True)
    connect_timeout_seconds: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def _validate_target_identities(self) -> MirrorTargetSettings:
        try:
            urls = [make_url(value.get_secret_value()) for value in (self.gateway_url, self.applier_url)]
            for url, role in zip(urls, ("refraq_mirror_gateway", "refraq_mirror_applier"), strict=True):
                if (
                    url.drivername != "postgresql+psycopg" or url.username != role
                    or not url.password or not url.host or not url.database
                    or url.query.get("sslmode") != "verify-full"
                    or set(url.query) - {"sslmode", "sslrootcert"}
                ):
                    raise ValueError
            if _database_target(str(urls[0])) != _database_target(str(urls[1])):
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("Mirror target requires distinct restricted identities on one verified TLS PostgreSQL database") from None
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES or None,
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    refraq_env: str = Field(default="dev", validation_alias="REFRAQ_ENV")
    refraq_api_host: str = Field(default="127.0.0.1", validation_alias="REFRAQ_API_HOST")
    refraq_api_port: int = Field(default=8000, validation_alias="REFRAQ_API_PORT")
    refraq_mcp_host: str = Field(default="127.0.0.1", validation_alias="REFRAQ_MCP_HOST")
    refraq_mcp_port: int = Field(default=8001, validation_alias="REFRAQ_MCP_PORT")
    refraq_entity_mcp_host: str = Field(
        default="127.0.0.1", validation_alias="REFRAQ_ENTITY_MCP_HOST"
    )
    refraq_entity_mcp_port: int = Field(
        default=8002, validation_alias="REFRAQ_ENTITY_MCP_PORT"
    )
    store_backend: StoreBackend = Field(
        default="persistent",
        validation_alias="REFRAQ_STORE_BACKEND",
    )
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    entity_database_url: str | None = Field(
        default=None, validation_alias="ENTITY_DATABASE_URL"
    )
    entity_reader_database_url: str | None = Field(
        default=None, validation_alias="ENTITY_READER_DATABASE_URL"
    )
    entity_signer_database_url: str | None = Field(
        default=None, validation_alias="ENTITY_SIGNER_DATABASE_URL"
    )
    redis_url: str | None = Field(default=None, validation_alias="REDIS_URL")
    admin_session_secret: str = Field(
        default="change-me",
        validation_alias="ADMIN_SESSION_SECRET",
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
    refraq_browser_facing_host: str | None = Field(
        default=None,
        validation_alias="REFRAQ_BROWSER_FACING_HOST",
    )
    refraq_prometheus_url: str = Field(
        default="http://prometheus:9090",
        validation_alias="REFRAQ_PROMETHEUS_URL",
    )
    mirror_target: MirrorTargetSettings | None = Field(
        default=None, validation_alias="REFRAQ_MIRROR_TARGET", repr=False,
    )
    notification_reviewed_origins: dict[str, str] = Field(
        default_factory=dict,
        validation_alias="REFRAQ_NOTIFICATION_REVIEWED_ORIGINS",
        repr=False,
    )
    notification_delivery: NotificationDeliverySettings | None = Field(
        default=None,
        validation_alias="REFRAQ_NOTIFICATION_DELIVERY",
        repr=False,
    )

    @field_validator("notification_reviewed_origins")
    @classmethod
    def _validate_notification_origins(cls, value: dict[str, str]) -> dict[str, str]:
        for origin, domain in value.items():
            try:
                parsed = urlsplit(origin)
                host = (parsed.hostname or "").lower()
                if ":" in host:
                    host = f"[{host}]"
                canonical = f"https://{host}"
                if parsed.port and parsed.port != 443:
                    canonical += f":{parsed.port}"
                if (
                    not host or origin != canonical or not domain.strip()
                    or domain != domain.strip()
                    or any(ord(char) <= 32 or ord(char) >= 127 for char in origin)
                    or "\\" in origin
                ):
                    raise ValueError
            except ValueError:
                raise ValueError("Notification policy requires canonical HTTPS origins and reviewed failure domains") from None
        return value

    @field_validator("refraq_browser_facing_host", mode="before")
    @classmethod
    def _normalize_browser_facing_host(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("REFRAQ_BROWSER_FACING_HOST must be a host or host:port")
        cleaned = value.strip()
        if not cleaned:
            return None
        if not valid_browser_host(cleaned):
            raise ValueError("REFRAQ_BROWSER_FACING_HOST must be a host or host:port")
        return cleaned

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


def require_entity_database_url(url: str | None) -> str:
    """Persistent API and worker require a usable entity-database URL to open the pool.

    Not a Settings constructor rule. MCP and Beat do not open the entity pool.
    Persistent API startup fail-fasts when the variable is missing.
    """
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError(
            "persistent Store Backend requires ENTITY_DATABASE_URL "
            "to open the entity pool"
        )
    return cleaned


def require_entity_reader_database_url(
    url: str | None, *, owner_url: str | None
) -> str:
    """Persistent API reads Entity data as the reader role, in the owner's database.

    ``owner_url`` None skips the same-database comparison. Entity MCP does that
    when ``ENTITY_DATABASE_URL`` is unset, so that process does not need the
    owner credential.
    """
    cleaned = (url or "").strip()
    if not cleaned:
        if current_process_role() == "entity_mcp":
            raise ValueError(
                "Entity MCP requires ENTITY_READER_DATABASE_URL "
                "to open the entity reader pool"
            )
        raise ValueError(
            "persistent API requires ENTITY_READER_DATABASE_URL "
            "to open the entity reader pool"
        )
    if owner_url is not None and _database_target(cleaned) != _database_target(
        owner_url
    ):
        raise ValueError(
            "ENTITY_READER_DATABASE_URL must name the same database as "
            "ENTITY_DATABASE_URL"
        )
    return cleaned


def require_entity_signer_database_url(url: str | None, *, reader_url: str) -> str:
    """Entity MCP loads the signing key as the signer role, in the reader's database."""
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError(
            "Entity MCP requires ENTITY_SIGNER_DATABASE_URL "
            "to open the entity signer pool"
        )
    if _database_target(cleaned) != _database_target(reader_url):
        raise ValueError(
            "ENTITY_SIGNER_DATABASE_URL must name the same database as "
            "ENTITY_READER_DATABASE_URL"
        )
    return cleaned


def require_distinct_entity_database(entity_url: str, metadata_url: str | None) -> None:
    """The entity database may share a server, never the metadata database itself."""
    if metadata_url and _database_target(entity_url) == _database_target(metadata_url):
        raise ValueError(
            "ENTITY_DATABASE_URL must name a database other than DATABASE_URL"
        )


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _database_target(url: str) -> tuple[str, int, str]:
    parsed = make_url(url)
    host = (parsed.host or "localhost").lower()
    if host in _LOOPBACK_HOSTS:
        host = "localhost"
    return host, int(parsed.port or 5432), parsed.database or ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
