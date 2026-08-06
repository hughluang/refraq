"""ORM for Source, Connection, and Catalog tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.db import Base


class SourceRow(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    database_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    schema_filter: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    connection: Mapped[ConnectionRow | None] = relationship(
        back_populates="source",
        uselist=False,
    )
    catalog_objects: Mapped[list[CatalogObjectRow]] = relationship(
        back_populates="source",
    )


class ConnectionRow(Base):
    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("source_id", name="uq_connections_source_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    engine: Mapped[str] = mapped_column(String(64), nullable=False)
    host: Mapped[str] = mapped_column(String(512), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    source: Mapped[SourceRow] = relationship(back_populates="connection")


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
    collected_from_connection_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_name: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    ddl: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    business_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    business_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_structure_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    source: Mapped[SourceRow] = relationship(back_populates="catalog_objects")
    columns: Mapped[list[CatalogColumnRow]] = relationship(
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
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_type: Mapped[str] = mapped_column(String(256), nullable=False)
    nullable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    business_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    business_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    object: Mapped[CatalogObjectRow] = relationship(back_populates="columns")
