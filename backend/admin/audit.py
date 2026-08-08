"""Persist management-plane audit events."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.admin.audit_store import (
    AuditEventRecord,
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
) -> AuditEventRecord:
    store = get_audit_store()
    record = AuditEventRecord(
        id=new_audit_id(),
        created_at=datetime.utcnow(),
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        result=result,
        detail=dict(detail or {}),
    )
    return store.create(record)
