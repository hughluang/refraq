"""Model Service records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

SUPPORTED_PURPOSES = frozenset({"embedding"})
SUPPORTED_PROTOCOLS = frozenset({"openai_compat"})


@dataclass
class ModelServiceRecord:
    id: str
    purpose: str
    protocol: str
    display_name: str
    url: str
    model: str
    secret: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class PurposeState:
    purpose: str
    in_use_id: str | None
    closed: bool
    ready: bool
    generation: int


@dataclass(frozen=True)
class EmbeddingRuntime:
    service_id: str
    url: str
    model: str
    secret: str | None
    closed: bool
    ready: bool
    generation: int
