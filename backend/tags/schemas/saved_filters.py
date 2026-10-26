"""HTTP shapes for Saved Filters."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from backend.core.pagination import OffsetPage
from backend.core.time import Instant

SavedFilterListName = Literal["entities", "channels"]


class SavedFilterOut(BaseModel):
    id: str
    list: str
    name: str
    query: dict[str, Any]
    created_at: Instant
    updated_at: Instant


class SavedFilterResponse(BaseModel):
    saved_filter: SavedFilterOut


class SavedFilterListResponse(OffsetPage[SavedFilterOut]):
    pass


class SavedFilterCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    list: SavedFilterListName
    name: str
    query: dict[str, Any]


class SavedFilterPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    query: dict[str, Any] | None = None


class SavedFilterDefaultOut(BaseModel):
    list: str
    saved_filter_id: str | None


class SavedFilterDefaultPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    list: SavedFilterListName
    saved_filter_id: str | None
