"""Domain Job facade request schemas; catalog shapes live in schemas.catalog."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from backend.metadata.schemas.catalog import (  # noqa: F401 — re-export for callers
    CatalogColumnOut,
    CatalogDdlResponse,
    CatalogObjectListResponse,
    CatalogObjectOut,
    CatalogObjectResponse,
)

__all__ = [
    "CatalogColumnOut",
    "CatalogDdlResponse",
    "CatalogObjectListResponse",
    "CatalogObjectOut",
    "CatalogObjectResponse",
    "EnqueueStructureJobRequest",
]


class EnqueueStructureJobRequest(BaseModel):
    kind: Literal["structure"] = "structure"
