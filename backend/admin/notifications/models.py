"""Management persistence owned by Foundation notifications."""

from datetime import datetime

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.db import Base
from backend.core.time import UtcDateTime


class NotificationChannelRow(Base):
    __tablename__ = "notification_channel"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    revision: Mapped[str] = mapped_column(String(64), nullable=False)
    routes_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    responder: Mapped[str] = mapped_column(String(128), nullable=False)
    delivery_state: Mapped[dict] = mapped_column(JSON, nullable=False)
    last_test_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    last_fault_code: Mapped[str | None] = mapped_column(String(64))
    test_operation_id: Mapped[str | None] = mapped_column(String(64))


class NotificationEventRow(Base):
    __tablename__ = "notification_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    channel_revision: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    route: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    outcomes: Mapped[dict] = mapped_column(JSON, nullable=False)
    attempt_history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    last_fault_code: Mapped[str | None] = mapped_column(String(64))
