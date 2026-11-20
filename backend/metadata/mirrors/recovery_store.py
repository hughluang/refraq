"""Durable recovery journal, serialized by the owning Source lock."""

from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.db import Base
from backend.metadata.mirrors.errors import MirrorError
from backend.metadata.models import SourceRow


class RecoveryRow(Base):
    __tablename__ = "source_mirror_recoveries"
    __table_args__ = (UniqueConstraint("source_id", "identity", name="uq_mirror_recovery_identity"),)

    operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False)
    mirror_id: Mapped[str] = mapped_column(String(64), ForeignKey("source_mirrors.id", ondelete="RESTRICT"), nullable=False)
    identity: Mapped[str] = mapped_column(String(64), nullable=False)
    journal: Mapped[dict] = mapped_column(JSON, nullable=False)


def lock_source(session, source_id):
    row = session.scalar(select(SourceRow).where(SourceRow.id == source_id).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise MirrorError("MIRROR_NOT_FOUND", 404)
    return row
