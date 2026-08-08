"""Mechanism Job API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    input: dict[str, Any]
    created_by_user_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None


class JobListResponse(BaseModel):
    items: list[JobOut]


class JobResponse(BaseModel):
    job: JobOut
