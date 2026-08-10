"""Source application service — CRUD, public projection, full access."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from backend.metadata.errors import (
    SourceAccessRequired,
    SourceEngineUnsupported,
    SourceKindUnsupported,
    SourceNotDisabled,
    SourceNotFound,
    SourceValidationError,
)
from backend.metadata.sources.access import (
    SUPPORTED_ENGINES,
    decrypt_access_blob,
    project_access,
    seal_access,
)
from backend.metadata.locators import format_source_locator
from backend.metadata.sources.store import (
    SUPPORTED_KINDS,
    SourceRecord,
    get_source_store,
    new_source_id,
)


def require_source(source_id: str) -> SourceRecord:
    record = get_source_store().get_source(source_id)
    if record is None:
        raise SourceNotFound()
    return record


def public_view(record: SourceRecord) -> dict[str, Any]:
    access = None
    if record.engine and record.access_ciphertext:
        access = project_access(
            record.engine,
            decrypt_access_blob(record.access_ciphertext),
        )
    return {
        "id": record.id,
        "key": record.key,
        "locator_key": record.locator_key,
        "name": record.name,
        "kind": record.kind,
        "status": record.status,
        "description": record.description,
        "database_name": record.database_name,
        "schema_filter": record.schema_filter,
        "engine": record.engine,
        "access": access,
        "has_access": record.has_access,
        "access_updated_at": record.access_updated_at,
    }


def full_access(record: SourceRecord) -> dict[str, Any]:
    if not record.access_ciphertext:
        raise SourceAccessRequired("Source has no access configuration")
    return decrypt_access_blob(record.access_ciphertext)


def create_source(
    *,
    key: str,
    name: str,
    kind: str,
    description: str | None,
    database_name: str | None,
    schema_filter: str | None,
    engine: str | None,
    access: dict[str, Any] | None,
) -> SourceRecord:
    if kind not in SUPPORTED_KINDS:
        raise SourceKindUnsupported()
    ciphertext: str | None = None
    access_updated_at: datetime | None = None
    if kind == "database":
        if not database_name:
            raise SourceValidationError("database_name is required for database Sources")
        if not engine or access is None:
            raise SourceAccessRequired()
        ciphertext = seal_access(engine, access)
        access_updated_at = datetime.utcnow()
    now = datetime.utcnow()
    record = SourceRecord(
        id=new_source_id(),
        key=key,
        locator_key=format_source_locator(engine=engine, kind=kind, key=key),
        name=name,
        kind=kind,
        status="active",
        description=description,
        database_name=database_name,
        schema_filter=schema_filter,
        engine=engine,
        access_ciphertext=ciphertext,
        access_updated_at=access_updated_at,
        created_at=now,
        updated_at=now,
    )
    return get_source_store().create_source(record)


def update_source(
    source_id: str,
    *,
    name: str | None = None,
    description: str | None | object = ...,
    status: str | None = None,
    database_name: str | None = None,
    schema_filter: str | None | object = ...,
    engine: str | None = None,
    access: dict[str, Any] | None | object = ...,
) -> SourceRecord:
    store = get_source_store()
    existing = store.get_source(source_id)
    if existing is None:
        raise SourceNotFound()
    updated = replace(existing)
    if name is not None:
        updated.name = name
    if description is not ...:
        updated.description = description  # type: ignore[assignment]
    if status is not None:
        if status not in {"active", "disabled"}:
            raise SourceValidationError("Invalid status")
        updated.status = status
    if database_name is not None:
        updated.database_name = database_name
    if schema_filter is not ...:
        updated.schema_filter = schema_filter  # type: ignore[assignment]
    if engine is not None:
        if engine not in SUPPORTED_ENGINES:
            raise SourceEngineUnsupported()
        updated.engine = engine
    if access is not ...:
        eng = engine if engine is not None else updated.engine
        if eng is None:
            raise SourceAccessRequired()
        updated.access_ciphertext = seal_access(eng, access)  # type: ignore[arg-type]
        updated.access_updated_at = datetime.utcnow()
    elif engine is not None and updated.access_ciphertext:
        existing_access = decrypt_access_blob(updated.access_ciphertext)
        updated.access_ciphertext = seal_access(engine, existing_access)
        updated.access_updated_at = datetime.utcnow()
    updated.updated_at = datetime.utcnow()
    saved = store.save_source(updated)
    if engine is not None and existing.engine != saved.engine:
        from backend.metadata.catalog.store import get_catalog_store

        get_catalog_store().recompute_locators_for_source(
            source_id,
            engine=saved.engine,
            kind=saved.kind,
            source_key=saved.key,
        )
    return saved


def delete_source(source_id: str) -> SourceRecord:
    store = get_source_store()
    existing = store.get_source(source_id)
    if existing is None:
        raise SourceNotFound()
    if existing.status != "disabled":
        raise SourceNotDisabled()
    from backend.metadata.catalog.store import get_catalog_store

    get_catalog_store().delete_objects_for_source(source_id)
    if not store.delete_source(source_id):
        raise SourceNotFound()
    return existing
