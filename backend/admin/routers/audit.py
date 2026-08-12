"""Management audit read API implementing docs/api-contracts-audit.md."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from backend.admin.audit_store import AuditEventRecord, get_audit_store
from backend.admin.deps import require_permission
from backend.admin.errors import AuditEventNotFound
from backend.admin.schemas.audit import AuditEvent, AuditEventListResponse, AuditEventResponse
from backend.admin.user_store import UserRecord


router = APIRouter(tags=["audit"])

def _to_event(record: object) -> AuditEvent:

    assert isinstance(record, AuditEventRecord)
    return AuditEvent(
        id=record.id,
        created_at=record.created_at,
        actor_user_id=record.actor_user_id,
        actor_token_id=record.actor_token_id,
        resource_type=record.resource_type,
        resource_id=record.resource_id,
        action=record.action,
        result=record.result,
        detail=dict(record.detail),
    )

@router.get("/audit/events", response_model=AuditEventListResponse)
def list_audit_events(
    _user: UserRecord = Depends(require_permission("audit:read")),
    resource_type: str | None = Query(default=None),
    actor_user_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> AuditEventListResponse:
    store = get_audit_store()
    items, next_cursor = store.list_events(
        resource_type=resource_type,
        actor_user_id=actor_user_id,
        action=action,
        from_dt=from_,
        to_dt=to,
        cursor=cursor,
        limit=limit,
    )
    return AuditEventListResponse(
        items=[_to_event(item) for item in items],
        next_cursor=next_cursor,
    )

@router.get("/audit/events/{event_id}", response_model=AuditEventResponse)
def get_audit_event(
    event_id: str,
    _user: UserRecord = Depends(require_permission("audit:read")),
) -> AuditEventResponse:
    record = get_audit_store().get_by_id(event_id)
    if record is None:
        raise AuditEventNotFound()
    return AuditEventResponse(event=_to_event(record))
