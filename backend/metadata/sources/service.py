"""Source application service — CRUD, public projection, full access."""

from __future__ import annotations

from backend.admin.audit import persist_audit_event
from backend.admin.deps import resolve_user_permissions
from backend.admin.errors import AuthForbidden
from backend.admin.permissions import permissions_include
from backend.admin.role_store import get_role_store
from backend.admin.user_store import UserRecord
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now
from dataclasses import replace
from datetime import datetime
from typing import Any, cast

from sqlalchemy.orm import Session

from backend.metadata.source_access import (
    SourceMembership,
    create_membership_on,
    delete_for_source,
    delete_for_source_on,
    effective_level,
    effective_permissions,
    source_ids_for,
)

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
    ALL_SOURCES,
    SUPPORTED_KINDS,
    AllVisibleSources,
    SourceRecord,
    SqlSourceStore,
    get_source_store,
    new_source_id,
)
from backend.metadata.source_schedules import (
    delete_source_schedules_by_source_id,
    ensure_default_source_schedules_if_none,
    seed_default_source_schedules,
)
from backend.worker.schemas.schedules import ScheduleOut


def require_source(source_id: str) -> SourceRecord:
    record = get_source_store().get_source(source_id)
    if record is None:
        raise SourceNotFound()
    return record


def require_source_permission(
    user_id: str, source_id: str, permission: str
) -> SourceRecord:
    """Load one Source the caller can use.

    No level uses the same not-found error as an unknown id. A level that does
    not include ``permission`` is forbidden. ``sources:access_manage`` is not a
    level and does not pass this check.
    """
    record = get_source_store().get_source(source_id)
    if record is None or effective_level(user_id, source_id) is None:
        raise SourceNotFound()
    if permission not in effective_permissions(user_id, source_id):
        raise AuthForbidden()
    return record


def list_sources_page(
    *,
    query_text: str | None = None,
    engine: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    records, total = get_source_store().list_sources(
        query_text=query_text, engine=engine, limit=limit, offset=offset
    )
    return [public_view(r) for r in records], total


def identity_view(record: SourceRecord) -> dict[str, Any]:
    """Source identity for a caller with no level. Does not read access."""
    return {
        "id": record.id,
        "key": record.key,
        "name": record.name,
        "kind": record.kind,
        "engine": record.engine,
        "status": record.status,
    }


def list_sources_for_user(
    user: UserRecord,
    *,
    query_text: str | None,
    engine: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    records, total = get_source_store().list_sources(
        query_text=query_text,
        engine=engine,
        limit=limit,
        offset=offset,
        visible_ids=_visible_source_ids(user),
    )
    return [_project_list_item(user.id, record) for record in records], total


def _visible_source_ids(user: UserRecord) -> frozenset[str] | AllVisibleSources:
    """Ids this caller may see. Never ``None`` (that means unfiltered)."""
    perms = resolve_user_permissions(user, get_role_store())
    if permissions_include(perms, "sources:access_manage"):
        return ALL_SOURCES
    granted = source_ids_for(user.id, "sources:read")
    if granted.all_sources:
        return ALL_SOURCES
    return granted.source_ids


def _project_list_item(user_id: str, record: SourceRecord) -> dict[str, Any]:
    if effective_level(user_id, record.id) is None:
        return identity_view(record)
    return public_view(record)


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
            membership = _creator_membership(session, stored.id, actor_user_id)
            seed_default_source_schedules(
                stored,
                session=session,
                actor_user_id=actor_user_id,
                actor_token_id=actor_token_id,
            )
            _audit_creator_membership(
                session,
                membership,
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
            delete_source_schedules_by_source_id(record.id)
            _delete_memory_source_row(record.id)
        raise


def _insert_source_and_seed(
    record: SourceRecord,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> SourceRecord:
    stored = get_source_store().create_source(record)
    membership = _creator_membership(None, stored.id, actor_user_id)
    seed_default_source_schedules(
        stored,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
    )
    _audit_creator_membership(
        None,
        membership,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
    )
    return stored


def _creator_membership(
    session: Session | None, source_id: str, actor_user_id: str | None
) -> SourceMembership | None:
    if not actor_user_id:
        return None
    return create_membership_on(
        session,
        subject_type="user",
        subject_id=actor_user_id,
        target=source_id,
        level="maintainer",
    )


def _audit_creator_membership(
    session: Session | None,
    membership: SourceMembership | None,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> None:
    if membership is None:
        return
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="source_membership",
        resource_id=membership.id,
        action="source_membership.create",
        result="success",
        detail={
            "subject": {
                "type": membership.subject_type,
                "id": membership.subject_id,
            },
            "target": membership.target,
            "old_level": None,
            "new_level": membership.level,
        },
        session=session,
    )


def _delete_memory_source_row(source_id: str) -> bool:
    delete_for_source(source_id)
    return get_source_store().delete_source(source_id)


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
) -> list[ScheduleOut]:
    if not changed:
        return []
    return ensure_default_source_schedules_if_none(
        saved,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        session=session,
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
) -> tuple[SourceRecord, list[ScheduleOut]]:
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
    seeded: list[ScheduleOut] = []
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
    delete_source_schedules_by_source_id(source_id)
    if get_settings().store_backend == "persistent":
        sql_store = cast(SqlSourceStore, store)
        with session_scope() as session:
            delete_for_source_on(session, source_id)
            if not sql_store.delete_source_on(session, source_id):
                raise SourceNotFound()
    elif not _delete_memory_source_row(source_id):
        raise SourceNotFound()
    return existing
