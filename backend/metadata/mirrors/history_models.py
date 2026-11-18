"""Management invalidation authority; these records are not consumer cursors."""

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.db import Base


class HistoryGateRow(Base):
    __tablename__ = "source_mirror_history_gates"
    __table_args__ = (
        CheckConstraint("status IN ('available', 'invalidating')"),
        CheckConstraint("lower_commit_seq >= 0 AND lower_entry_seq >= 0"),
    )

    mirror_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("source_mirrors.id", ondelete="RESTRICT"), primary_key=True
    )
    history_epoch: Mapped[str] = mapped_column(String(64), nullable=False)
    lower_commit_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lower_entry_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)


class HistoryInvalidationRow(Base):
    __tablename__ = "source_mirror_history_invalidations"

    operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    transitions: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
