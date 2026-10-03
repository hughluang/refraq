"""Bound catalog-embed job port. Composition injects metadata implementation."""

from __future__ import annotations

from typing import Protocol

from backend.admin.model_services.records import EmbedScheduleView


class CatalogEmbedJobsPort(Protocol):
    def trigger_run(
        self, *, actor_user_id: str, actor_token_id: str | None
    ) -> str: ...

    def has_active(self) -> bool: ...

    def clear_index(self) -> None: ...

    def latest_sweep_status(self) -> str | None: ...

    def schedule_view(self) -> EmbedScheduleView | None: ...


_port: CatalogEmbedJobsPort | None = None


def bind_catalog_embed_jobs(port: CatalogEmbedJobsPort | None) -> None:
    global _port
    _port = port


def catalog_embed_jobs() -> CatalogEmbedJobsPort:
    if _port is None:
        raise RuntimeError("catalog embed jobs port is not bound")
    return _port
