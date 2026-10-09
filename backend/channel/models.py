"""ORM for Data Channel definitions and immutable versions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.db import Base
from backend.core.time import UtcDateTime


class ChannelRow(Base):
    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    draft_graph: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class ChannelVersionRow(Base):
    __tablename__ = "channel_versions"

    channel_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("channels.id", ondelete="CASCADE"),
        primary_key=True,
    )
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    published_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
