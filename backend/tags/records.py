"""In-memory Tag record. The comparison form is not an HTTP field."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TagRecord:
    id: str
    name: str
    name_key: str
    description: str | None
    created_at: datetime
    updated_at: datetime
