"""Persist management-plane audit events."""

from __future__ import annotations

from backend.core.time import utc_now
from typing import Any

from sqlalchemy.orm import Session

from backend.admin.audit_store import (
    AuditEventRecord,
    SqlAuditStore,
    get_audit_store,
    new_audit_id,
)


def persist_audit_event(
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    resource_type: str,
    resource_id: str,
    action: str,
    result: str,
    detail: dict[str, Any] | None = None,
    session: Session | None = None,
) -> AuditEventRecord:
    record = _audit_event_record(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        result=result,
        detail=detail,
    )
    if session is not None:
        return SqlAuditStore().create_on(session, record)
    return get_audit_store().create(record)


def _audit_event_record(
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    resource_type: str,
    resource_id: str,
    action: str,
    result: str,
    detail: dict[str, Any] | None,
) -> AuditEventRecord:
    return AuditEventRecord(
        id=new_audit_id(),
        created_at=utc_now(),
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        result=result,
        detail=dict(detail or {}),
    )
