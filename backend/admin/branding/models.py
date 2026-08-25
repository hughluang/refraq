"""SQLAlchemy models for site branding."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.db import Base
from backend.core.time import UtcDateTime


class SiteBrandingAssetRow(Base):
    __tablename__ = "site_branding_assets"
    __table_args__ = (
        CheckConstraint("kind IN ('logo', 'favicon')", name="ck_branding_asset_kind"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class SiteBrandingRow(Base):
    __tablename__ = "site_branding"
    __table_args__ = (
        CheckConstraint("id = 'site'", name="ck_site_branding_singleton"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    brand_names: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    taglines: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    primary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    primary_shades: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    show_logo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    show_brand_name_with_logo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_by_user_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
