"""ORM for Entity access policy in the metadata database."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.db import Base
from backend.core.time import UtcDateTime


class PresentationLadderRow(Base):
    __tablename__ = "entity_presentation_ladders"

    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("business_entities.id", ondelete="CASCADE"), primary_key=True
    )
    attribute_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    levels: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class AccessProfileRow(Base):
    __tablename__ = "entity_access_profiles"
    __table_args__ = (
        UniqueConstraint("entity_id", "key", name="uq_entity_access_profiles_key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("business_entities.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(63), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    columns: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class AccessGrantRow(Base):
    __tablename__ = "entity_access_grants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("business_entities.id", ondelete="CASCADE"), nullable=False
    )
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("entity_access_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    row_rule: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    actions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class AccessRestrictionRow(Base):
    __tablename__ = "entity_access_restrictions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("business_entities.id", ondelete="CASCADE"), nullable=False
    )
    applies_to: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    row_rule: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    deny_columns: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    ceilings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    actions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class PolicyRevisionRow(Base):
    __tablename__ = "entity_access_revisions"

    entity_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("business_entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    views_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ProfileViewBindingRow(Base):
    __tablename__ = "entity_profile_view_bindings"

    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("business_entities.id", ondelete="CASCADE"), primary_key=True
    )
    shape_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    head_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    combo_key: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    view_name: Mapped[str] = mapped_column(String(63), nullable=False)
    columns: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    ddl_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    sql: Mapped[str] = mapped_column(Text, nullable=False)


class EntityAccessLogRow(Base):
    __tablename__ = "entity_access_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    pat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    verb: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_grant_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    narrowing: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    view_name: Mapped[str | None] = mapped_column(String(63), nullable=True)
    policy_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome_code: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_subject_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
