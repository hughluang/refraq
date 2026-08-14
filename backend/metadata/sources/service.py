"""Source application service — CRUD, public projection, full access."""

from __future__ import annotations

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now
from dataclasses import replace
from datetime import datetime
from typing import Any, cast

from sqlalchemy.orm import Session

from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.structure_diffs.store import get_structure_diff_store
from backend.metadata.errors import (
    SourceAccessRequired,
    SourceEngineUnsupported,
    SourceKindUnsupported,
    SourceNotDisabled,
    SourceNotFound,
    SourceValidationError,
)
from backend.metadata.locators import format_source_locator
from backend.metadata.sources.access import (
    SUPPORTED_ENGINES,
    decrypt_access_blob,
    project_access,
    seal_access,
)
from backend.metadata.sources.store import (
    SUPPORTED_KINDS,
    SourceRecord,
    SqlSourceStore,
    get_source_store,
    new_source_id,
)
from backend.metadata.source_schedules import (
    ensure_default_structure_schedule_if_none,
    ensure_default_structure_schedule_if_none_on,
    seed_default_structure_schedule,
    seed_default_structure_schedule_on,
)
from backend.worker.api import delete_structure_schedules_by_source_id
from backend.worker.schemas.schedules import ScheduleOut


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
    engine: str | None,
    access: dict[str, Any] | None,
    actor_user_id: str | None = None,
    actor_token_id: str | None = None,
) -> SourceRecord:
    if kind not in SUPPORTED_KINDS:
        raise SourceKindUnsupported()
    ciphertext: str | None = None
    access_updated_at: datetime | None = None
    if kind == "database":
        if not engine or access is None:
            raise SourceAccessRequired()
        ciphertext = seal_access(engine, access)
        access_updated_at = utc_now()
    now = utc_now()
    record = SourceRecord(
        id=new_source_id(),
        key=key,
        locator_key=format_source_locator(engine=engine, kind=kind, key=key),
        name=name,
        kind=kind,
        status="active",
        description=description,
        engine=engine,
        access_ciphertext=ciphertext,
        access_updated_at=access_updated_at,
        created_at=now,
        updated_at=now,
    )
    if get_settings().store_backend == "persistent":
        store = cast(SqlSourceStore, get_source_store())
        with session_scope() as session:
            stored = store.create_source_on(session, record)
            seed_default_structure_schedule_on(
                stored,
                session=session,
                actor_user_id=actor_user_id,
                actor_token_id=actor_token_id,
            )
            return stored
    try:
        return _insert_source_and_seed(
            record,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
        )
    except Exception:
        if get_source_store().get_source(record.id) is not None:
            delete_structure_schedules_by_source_id(record.id)
            get_source_store().delete_source(record.id)
        raise


def _insert_source_and_seed(
    record: SourceRecord,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> SourceRecord:
    stored = get_source_store().create_source(record)
    seed_default_structure_schedule(
        stored.id,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
    )
    return stored


def _source_business_changed(before: SourceRecord, after: SourceRecord) -> bool:
    return (
        before.name != after.name
        or before.description != after.description
        or before.status != after.status
        or before.engine != after.engine
        or before.access_ciphertext != after.access_ciphertext
    )


def _maybe_seed_after_update(
    saved: SourceRecord,
    *,
    changed: bool,
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None = None,
) -> ScheduleOut | None:
    if not changed:
        return None
    if session is not None:
        return ensure_default_structure_schedule_if_none_on(
            saved,
            session=session,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
        )
    return ensure_default_structure_schedule_if_none(
        saved,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
    )


def update_source(
    source_id: str,
    *,
    name: str | None = None,
    description: str | None | object = ...,
    status: str | None = None,
    engine: str | None = None,
    access: dict[str, Any] | None | object = ...,
    actor_user_id: str | None = None,
    actor_token_id: str | None = None,
) -> tuple[SourceRecord, ScheduleOut | None]:
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
    if engine is not None:
        if engine not in SUPPORTED_ENGINES:
            raise SourceEngineUnsupported()
        updated.engine = engine
    if access is not ...:
        eng = engine if engine is not None else updated.engine
        if eng is None:
            raise SourceAccessRequired()
        updated.access_ciphertext = seal_access(eng, access)  # type: ignore[arg-type]
        updated.access_updated_at = utc_now()
    elif engine is not None and updated.access_ciphertext:
        existing_access = decrypt_access_blob(updated.access_ciphertext)
        updated.access_ciphertext = seal_access(engine, existing_access)
        updated.access_updated_at = utc_now()
    updated.updated_at = utc_now()
    changed = _source_business_changed(existing, updated)
    seeded: ScheduleOut | None = None
    if get_settings().store_backend == "persistent":
        sql_store = cast(SqlSourceStore, store)
        with session_scope() as session:
            saved = sql_store.save_source_on(session, updated)
            seeded = _maybe_seed_after_update(
                saved,
                changed=changed,
                actor_user_id=actor_user_id,
                actor_token_id=actor_token_id,
                session=session,
            )
    else:
        saved = store.save_source(updated)
        seeded = _maybe_seed_after_update(
            saved,
            changed=changed,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
        )
    if engine is not None and existing.engine != saved.engine:
        get_catalog_store().recompute_locators_for_source(
            source_id,
            engine=saved.engine,
            kind=saved.kind,
            source_key=saved.key,
        )
    return saved, seeded


def delete_source(source_id: str) -> SourceRecord:
    store = get_source_store()
    existing = store.get_source(source_id)
    if existing is None:
        raise SourceNotFound()
    if existing.status != "disabled":
        raise SourceNotDisabled()

    get_catalog_store().delete_objects_for_source(source_id)
    get_structure_diff_store().delete_for_source(source_id)
    delete_structure_schedules_by_source_id(source_id)
    if not store.delete_source(source_id):
        raise SourceNotFound()
    return existing
