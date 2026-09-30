"""HTTP request and response shapes for Dictionarys."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_serializer

from backend.core.pagination import OffsetPage
from backend.core.time import Instant


class DictionaryEntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label: str | None = None
    active: bool = True


class DictionaryEntryOut(BaseModel):
    code: str
    label: str | None = None
    active: bool

    @model_serializer(mode="wrap")
    def _omit_empty_label(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if data.get("label") is None:
            data.pop("label", None)
        return data


class DictionaryUsageOut(BaseModel):
    entity_id: str
    entity_name: str
    table_name: str
    attribute_name: str
    version_id: str
    version: int
    publish_status: str
    behind: bool


class DictionaryOut(BaseModel):
    id: str
    name: str
    display_name: str
    description: str | None = None
    revision: int
    deprecated_at: Instant | None = None
    entry_count: int
    entries: list[DictionaryEntryOut] | None = None
    usages: list[DictionaryUsageOut] | None = None
    created_at: Instant
    updated_at: Instant

    @model_serializer(mode="wrap")
    def _omit_detail_when_absent(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if data.get("entries") is None:
            data.pop("entries", None)
        if data.get("usages") is None:
            data.pop("usages", None)
        return data


class DictionaryResponse(BaseModel):
    dictionary: DictionaryOut


class DictionaryListResponse(OffsetPage[DictionaryOut]):
    pass


class DictionaryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str
    description: str | None = None
    entries: list[DictionaryEntryIn]


class DictionaryPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    description: str | None = None
    deprecated: bool | None = None
    entries: list[DictionaryEntryIn] | None = None
