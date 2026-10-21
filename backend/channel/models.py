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
    failure_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


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


class ChannelRunRow(Base):
    __tablename__ = "channel_runs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    target: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    draft_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    graph: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    trigger_node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ignore_checkpoints: Mapped[bool] = mapped_column(Boolean, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    failed_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stopped_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stop_at_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skipped_node_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class WebhookRow(Base):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_delivery_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_delivery_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class EmailAccountRow(Base):
    __tablename__ = "email_accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    encryption: Mapped[str] = mapped_column(String(16), nullable=False)
    username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    password_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_address: Mapped[str] = mapped_column(String(254), nullable=False)
    tls_skip_verify: Mapped[bool] = mapped_column(Boolean, nullable=False)
    last_delivery_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_delivery_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class ChannelVariableRow(Base):
    __tablename__ = "channel_variables"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class ChannelNodeExecutionRow(Base):
    __tablename__ = "channel_node_executions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("channel_runs.job_id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    output: Mapped[Any] = mapped_column(JSONB, nullable=True)
    output_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
