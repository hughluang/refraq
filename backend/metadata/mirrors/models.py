"""Management-only mirror registry, references and durable command intent."""

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.db import Base


class MirrorRow(Base):
    __tablename__ = "source_mirrors"
    __table_args__ = (UniqueConstraint("source_id", "table_identity", name="uq_source_mirror_binding"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False)
    table_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state: Mapped[dict] = mapped_column(JSON, nullable=False)


class MirrorReferenceRow(Base):
    __tablename__ = "source_mirror_references"

    channel_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mirror_id: Mapped[str] = mapped_column(String(64), ForeignKey("source_mirrors.id", ondelete="RESTRICT"), primary_key=True)
    channel_version: Mapped[int] = mapped_column(Integer, nullable=False)


class MirrorOperationRow(Base):
    __tablename__ = "source_mirror_operations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mirror_id: Mapped[str] = mapped_column(String(64), ForeignKey("source_mirrors.id", ondelete="CASCADE"), nullable=False, index=True)
    command: Mapped[dict] = mapped_column(JSON, nullable=False)


class MirrorPublicationRow(Base):
    __tablename__ = "source_mirror_publications"

    channel_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel_version: Mapped[int] = mapped_column(Integer, nullable=False)
    object_ids: Mapped[list] = mapped_column(JSON, nullable=False)


class MirrorIntentReceiptRow(Base):
    __tablename__ = "source_mirror_intent_receipts"

    operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request: Mapped[dict] = mapped_column(JSON, nullable=False)
    result: Mapped[list] = mapped_column(JSON, nullable=False)
