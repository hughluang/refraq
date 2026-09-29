"""ORM for Business Entity definition tables (metadata database)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.db import Base
from backend.core.time import UtcDateTime


class BusinessEntityRow(Base):
    __tablename__ = "business_entities"
    __table_args__ = (
        UniqueConstraint("table_name", name="uq_business_entities_table_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(63), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    deprecated_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class EntityVersionRow(Base):
    __tablename__ = "entity_versions"
    __table_args__ = (
        UniqueConstraint("entity_id", "version", name="uq_entity_versions_entity_version"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("business_entities.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    attributes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    materialized_attributes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    publish_status: Mapped[str] = mapped_column(String(16), nullable=False)
    latest_reconcile_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
