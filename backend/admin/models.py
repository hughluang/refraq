"""SQLAlchemy ORM models for Management Foundation User and Role."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.db import Base
from backend.core.time import UtcDateTime


class RoleRow(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    permissions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    users: Mapped[list[UserRow]] = relationship(back_populates="role")


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en-US")
    display_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    role_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    identity_source: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    role: Mapped[RoleRow | None] = relationship(back_populates="users")
    pats: Mapped[list[UserPatRow]] = relationship(back_populates="user")


class IdentityProviderRow(Base):
    __tablename__ = "identity_providers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    protocol: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    issuer: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class FederatedIdentityRow(Base):
    __tablename__ = "user_external_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_external_identity_issuer_subject"),
        UniqueConstraint("user_id", name="uq_external_identity_user"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("identity_providers.id", ondelete="SET NULL"), nullable=True
    )
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class PendingFederationRow(Base):
    __tablename__ = "pending_federated_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_pending_federation_issuer_subject"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("identity_providers.id", ondelete="SET NULL"), nullable=True
    )
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    account_hint: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    groups: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    admission_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    claims: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_attempt_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class UserPatRow(Base):
    __tablename__ = "user_pats"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    user: Mapped[UserRow] = relationship(back_populates="pats")


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    actor_token_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class SystemParameterRow(Base):
    __tablename__ = "system_parameters"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[object] = mapped_column(JSONB, nullable=False)
    previous_value: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
