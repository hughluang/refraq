"""Structure Diff HTTP adapters (Source-owned, not a Job sub-resource)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.admin.deps import require_permission
from backend.admin.user_store import UserRecord
from backend.metadata.schemas.structure_diffs import (
    StructureDiffListItemOut,
    StructureDiffListResponse,
    StructureDiffOut,
    StructureDiffResponse,
)
from backend.metadata.structure_diffs import service as diff_service
from backend.metadata.structure_diffs.store import StructureDiffRecord

router = APIRouter(tags=["structure-diffs"])


def _item_out(record: StructureDiffRecord) -> StructureDiffListItemOut:
    return StructureDiffListItemOut(
        id=record.id,
        source_id=record.source_id,
        job_id=record.job_id,
        class_=record.diff_class,
        counts=record.counts,
        created_at=record.created_at,
    )


def _detail_out(record: StructureDiffRecord) -> StructureDiffOut:
    return StructureDiffOut(
        id=record.id,
        source_id=record.source_id,
        job_id=record.job_id,
        class_=record.diff_class,
        counts=record.counts,
        created_at=record.created_at,
        changes=record.changes,
    )


@router.get(
    "/sources/{source_id}/structure-diffs",
    response_model=StructureDiffListResponse,
)
def list_source_structure_diffs(
    source_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> StructureDiffListResponse:
    items, total = diff_service.list_structure_diffs(
        source_id, limit=limit, offset=offset
    )
    return StructureDiffListResponse(
        items=[_item_out(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/structure-diffs/{diff_id}",
    response_model=StructureDiffResponse,
)
def get_structure_diff(
    diff_id: str,
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> StructureDiffResponse:
    record = diff_service.get_structure_diff(diff_id)
    return StructureDiffResponse(structure_diff=_detail_out(record))
