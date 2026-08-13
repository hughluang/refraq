"""ORM for Source and Catalog tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.db import Base
from backend.core.time import UtcDateTime


class BusinessDomainRow(Base):
    __tablename__ = "business_domains"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class SourceRow(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    locator_key: Mapped[str] = mapped_column(
        String(512), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine: Mapped[str | None] = mapped_column(String(64), nullable=True)
    access_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_updated_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    catalog_objects: Mapped[list[CatalogObjectRow]] = relationship(
        back_populates="source",
    )


class CatalogObjectRow(Base):
    __tablename__ = "catalog_objects"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "schema_name",
            "name",
            "object_type",
            name="uq_catalog_objects_natural_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    locator_key: Mapped[str] = mapped_column(
        String(1024), unique=True, nullable=False, index=True
    )
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_name: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    ddl: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_key_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    business_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    business_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grain_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_primary_key_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_domain_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("business_domains.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    evidence_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    open_questions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    semantic_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    business_semantics_ready: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    semantics_updated_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_structure_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    source: Mapped[SourceRow] = relationship(back_populates="catalog_objects")
    business_domain: Mapped[BusinessDomainRow | None] = relationship()
    columns: Mapped[list[CatalogColumnRow]] = relationship(
        back_populates="object",
        cascade="all, delete-orphan",
    )
    foreign_keys: Mapped[list[CatalogForeignKeyRow]] = relationship(
        back_populates="object",
        cascade="all, delete-orphan",
    )
    indexes: Mapped[list[CatalogIndexRow]] = relationship(
        back_populates="object",
        cascade="all, delete-orphan",
    )


class CatalogColumnRow(Base):
    __tablename__ = "catalog_columns"
    __table_args__ = (
        UniqueConstraint(
            "object_id",
            "name",
            name="uq_catalog_columns_object_name",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    object_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("catalog_objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    locator_key: Mapped[str] = mapped_column(
        String(1024), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_type: Mapped[str] = mapped_column(String(256), nullable=False)
    nullable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    business_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    business_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    column_semantics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    enum_catalog_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    semantic_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    field_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="column")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    object: Mapped[CatalogObjectRow] = relationship(back_populates="columns")


class CatalogForeignKeyRow(Base):
    __tablename__ = "catalog_foreign_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    object_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("catalog_objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    columns_json: Mapped[str] = mapped_column(Text, nullable=False)
    ref_schema: Mapped[str] = mapped_column(String(256), nullable=False)
    ref_table: Mapped[str] = mapped_column(String(256), nullable=False)
    ref_columns_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    object: Mapped[CatalogObjectRow] = relationship(back_populates="foreign_keys")


class CatalogIndexRow(Base):
    __tablename__ = "catalog_indexes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    object_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("catalog_objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    columns_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_unique: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    object: Mapped[CatalogObjectRow] = relationship(back_populates="indexes")


class CatalogJoinRow(Base):
    __tablename__ = "catalog_joins"
    __table_args__ = (
        UniqueConstraint(
            "from_column_id",
            "to_column_id",
            name="uq_catalog_joins_from_to",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    from_column_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("catalog_columns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    to_column_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("catalog_columns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    join_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="INNER")
    join_expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="human")
    created_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
