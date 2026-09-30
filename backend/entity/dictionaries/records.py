"""In-memory records for Dictionarys."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

__all__ = ["DictionaryEntryRecord", "DictionaryRecord"]


@dataclass(frozen=True, slots=True)
class DictionaryEntryRecord:
    code: str
    label: str | None
    active: bool
    position: int


@dataclass
class DictionaryRecord:
    id: str
    name: str
    display_name: str
    description: str | None
    revision: int
    deprecated_at: datetime | None
    entries: tuple[DictionaryEntryRecord, ...]
    created_at: datetime
    updated_at: datetime
