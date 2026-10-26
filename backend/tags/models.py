"""ORM for the platform Tag vocabulary (metadata database)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.db import Base
from backend.core.time import UtcDateTime


class TagRow(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("name_key", name="uq_tags_name_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    name_key: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class TagAssignmentRow(Base):
    """One Tag carried by one subject. Subjects are entity or channel ids."""

    __tablename__ = "tag_assignments"
    __table_args__ = (
        CheckConstraint(
            "subject_kind IN ('entity', 'channel')",
            name="ck_tag_assignments_kind",
        ),
        Index("ix_tag_assignments_tag_id", "tag_id"),
        Index("ix_tag_assignments_kind_tag", "subject_kind", "tag_id"),
    )

    subject_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tag_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tags.id"), primary_key=True
    )


class TagSubjectRevisionRow(Base):
    """Revision of one subject's Tag set. Absence means revision 1 and an empty set."""

    __tablename__ = "tag_subject_revisions"
    __table_args__ = (
        CheckConstraint(
            "subject_kind IN ('entity', 'channel')",
            name="ck_tag_subject_revisions_kind",
        ),
    )

    subject_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
