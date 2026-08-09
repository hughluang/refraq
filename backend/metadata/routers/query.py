"""Controlled read-only query HTTP API (Slice D)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.metadata.query import service as query_service
from backend.metadata.schemas.query import QueryRequest, QueryResponse

router = APIRouter(tags=["query"])


@router.post("/sources/{source_id}/query", response_model=QueryResponse)
def run_query(
    source_id: str,
    body: QueryRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("query:run")),
) -> QueryResponse:
    outcome = query_service.run_controlled_query(
        source_id=source_id,
        sql=body.sql,
        max_rows=body.max_rows,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    return QueryResponse(
        columns=outcome.columns,
        rows=outcome.rows,
        truncated=outcome.truncated,
        duration_ms=outcome.duration_ms,
    )
