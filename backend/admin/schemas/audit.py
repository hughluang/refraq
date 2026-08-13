"""Management audit API schemas."""

from __future__ import annotations

from backend.core.time import Instant
from typing import Any

from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    id: str
    created_at: Instant
    actor_user_id: str | None
    actor_token_id: str | None
    resource_type: str
    resource_id: str
    action: str
    result: str
    detail: dict[str, Any] = Field(default_factory=dict)


class AuditEventListResponse(BaseModel):
    items: list[AuditEvent]
    next_cursor: str | None = None


class AuditEventResponse(BaseModel):
    event: AuditEvent
