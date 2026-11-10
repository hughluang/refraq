"""Model Service records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

SUPPORTED_PURPOSES = frozenset({"embedding"})
SUPPORTED_PROTOCOLS = frozenset({"openai_compat"})
CURRENT_PROCESSING_CONTRACT = "prefix-1024-l2-v1"


@dataclass
class ModelServiceRecord:
    id: str
    purpose: str
    protocol: str
    display_name: str
    url: str
    model: str
    timeout_sec: int
    secret: str | None
    created_at: datetime
    updated_at: datetime
    batch_limit: int = 32


@dataclass
class PurposeState:
    purpose: str
    in_use_id: str | None
    closed: bool
    ready: bool
    generation: int
    control_revision: int = 0
    processing_contract: str = CURRENT_PROCESSING_CONTRACT


@dataclass(frozen=True)
class EmbedScheduleView:
    id: str
    enabled: bool
    cron: str | None
    interval_seconds: int | None
    next_run_at: datetime | None


@dataclass(frozen=True)
class CatalogIndexView:
    """Catalog-owned index. Ready here is not Model Service health."""

    ready: bool = False
    generation_last_swept: int | None = None
    objects_written: int = 0
    columns_written: int = 0
    objects_failed: int = 0
    columns_failed: int = 0
    objects_attempted: int = 0
    columns_attempted: int = 0
    progress: str | None = None
    failure_summary: str | None = None
    rebuild_owed: bool = False


@dataclass(frozen=True)
class EntityIndexView:
    """Entity-owned index. Ready here is not Catalog readiness."""

    ready: bool = False
    generation: int | None = None
    written: int = 0
    failed: int = 0
    attempted: int = 0
    progress: str | None = None
    failure_summary: str | None = None
    rebuild_owed: bool = False


@dataclass(frozen=True)
class EmbeddingRuntime:
    service_id: str
    url: str
    model: str
    secret: str | None
    timeout_sec: int
    batch_limit: int
    closed: bool
    ready: bool
    generation: int
    control_revision: int = 0
