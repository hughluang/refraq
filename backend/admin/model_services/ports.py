"""Bound embed-job ports. Composition injects each consumer's implementation."""

from __future__ import annotations

from typing import Protocol

from backend.admin.model_services.records import (
    CatalogIndexView,
    EmbedScheduleView,
    EntityIndexView,
)


class CatalogEmbedJobsPort(Protocol):
    def trigger_run(
        self, *, actor_user_id: str, actor_token_id: str | None
    ) -> str: ...

    def has_active(self) -> bool: ...

    def clear_index(self) -> None: ...

    def latest_sweep_status(self) -> str | None: ...

    def schedule_view(self) -> EmbedScheduleView | None: ...

    def index_view(self) -> CatalogIndexView: ...

    def clear_index_ready(self, *, rebuild_owed: bool) -> None: ...


_port: CatalogEmbedJobsPort | None = None


def bind_catalog_embed_jobs(port: CatalogEmbedJobsPort | None) -> None:
    global _port
    _port = port


def catalog_embed_jobs() -> CatalogEmbedJobsPort:
    if _port is None:
        raise RuntimeError("catalog embed jobs port is not bound")
    return _port


class EntityEmbedJobsPort(Protocol):
    def owns_schedule(self, key: str) -> bool: ...

    def trigger_run(
        self, *, actor_user_id: str, actor_token_id: str | None
    ) -> str: ...

    def has_active(self) -> bool: ...

    def clear_index(self) -> None: ...

    def latest_sweep_status(self) -> str | None: ...

    def schedule_view(self) -> EmbedScheduleView | None: ...

    def index_view(self) -> EntityIndexView: ...

    def clear_index_ready(self, *, rebuild_owed: bool) -> None: ...


_entity_port: EntityEmbedJobsPort | None = None


def bind_entity_embed_jobs(port: EntityEmbedJobsPort | None) -> None:
    global _entity_port
    _entity_port = port


def entity_embed_jobs() -> EntityEmbedJobsPort:
    if _entity_port is None:
        raise RuntimeError("entity embed jobs port is not bound")
    return _entity_port


def entity_embed_owns(key: str) -> bool:
    if _entity_port is None:
        return False
    return _entity_port.owns_schedule(key)
