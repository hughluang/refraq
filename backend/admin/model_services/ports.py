"""Bound catalog-embed job port. Composition injects metadata implementation."""

from __future__ import annotations

from typing import Protocol


class CatalogEmbedJobsPort(Protocol):
    def mint(
        self,
        *,
        service_id: str,
        display_name: str,
        generation: int,
        actor_user_id: str,
    ) -> str: ...

    def cancel_active(self) -> None: ...

    def clear_index(self) -> None: ...

    def latest_status(self) -> str | None: ...


_port: CatalogEmbedJobsPort | None = None


def bind_catalog_embed_jobs(port: CatalogEmbedJobsPort | None) -> None:
    global _port
    _port = port


def catalog_embed_jobs() -> CatalogEmbedJobsPort:
    if _port is None:
        raise RuntimeError("catalog embed jobs port is not bound")
    return _port
