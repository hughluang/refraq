"""On-demand runs and run records."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.channel.errors import ChannelRunNotFound
from backend.channel.run_store import get_run_store, output_page, output_preview
from backend.channel.runs import start_run
from backend.channel.schemas.channels import GraphIn
from backend.channel.template_preview import preview_template
from backend.core.pagination import PageParams, page_params
from backend.core.time import Instant, format_instant
from backend.jobs.store import get_job_store

router = APIRouter(tags=["channels"])


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: Literal["draft", "published"] = "published"
    ignore_checkpoints: bool = False
    stop_at_node_id: str | None = None


class TemplatePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: GraphIn
    node_id: str = Field(min_length=1, max_length=64)
    path: list[str | int] = Field(min_length=1)


class ChannelRunOut(BaseModel):
    """Run record. Extra keys pass through; Instant fields are the time contract."""

    model_config = ConfigDict(extra="allow")

    created_at: Instant
    started_at: Instant | None = None
    finished_at: Instant | None = None


class ChannelRunListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[ChannelRunOut]


class ChannelRunStartResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run: ChannelRunOut


class NodeExecutionOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    started_at: Instant | None = None
    finished_at: Instant | None = None


class ChannelRunDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run: ChannelRunOut
    node_executions: list[NodeExecutionOut]


@router.post(
    "/channels/{channel_id}/runs",
    status_code=202,
    response_model=ChannelRunStartResponse,
)
def http_start_run(
    channel_id: str,
    body: StartRunRequest,
    actor: UserRecord = Depends(require_permission("channel:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Any:
    job, _queued = start_run(
        channel_id=channel_id,
        target=body.target,
        ignore_checkpoints=body.ignore_checkpoints,
        stop_at_node_id=body.stop_at_node_id,
        actor=actor,
        actor_token_id=actor_token_id,
    )
    job = get_job_store().get(job.id)
    stored = get_run_store().get_run(job.id)
    if stored is None:
        raise ChannelRunNotFound()
    return {"run": _present(job, stored)}


@router.get("/channels/{channel_id}/runs", response_model=ChannelRunListResponse)
def http_list_runs(
    channel_id: str,
    _actor: UserRecord = Depends(require_permission("channel:read")),
    status: str | None = None,
    target: str | None = None,
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
) -> dict[str, Any]:
    records, total = get_run_store().list_runs(
        channel_id,
        status=status,
        target=target,
        limit=page.limit,
        offset=page.offset,
    )
    items = []
    for record in records:
        job = get_job_store().get(record.job_id)
        if status is not None and job.status != status:
            continue
        items.append(_present(job, record))
    return {"items": items, "total": total, "limit": page.limit, "offset": page.offset}


@router.get(
    "/channels/{channel_id}/runs/{job_id}",
    response_model=ChannelRunDetailResponse,
)
def http_get_run(
    channel_id: str,
    job_id: str,
    _actor: UserRecord = Depends(require_permission("channel:read")),
) -> dict[str, Any]:
    record = _owned(channel_id, job_id)
    job = get_job_store().get(job_id)
    executions = []
    for item in get_run_store().list_executions(job_id):
        executions.append(
            {
                "seq": item.seq,
                "node_id": item.node_id,
                "status": item.status,
                "started_at": format_instant(item.started_at) if item.started_at else None,
                "finished_at": format_instant(item.finished_at) if item.finished_at else None,
                "output_bytes": item.output_bytes,
                "output_preview": output_preview(item.output),
                "error_code": item.error_code,
                "error_message": item.error_message,
                "error_detail": item.error_detail,
            }
        )
    return {"run": _present(job, record), "graph": record.graph, "node_executions": executions}


@router.get("/channels/{channel_id}/runs/{job_id}/executions/{seq}/output")
def http_execution_output(
    channel_id: str,
    job_id: str,
    seq: int,
    _actor: UserRecord = Depends(require_permission("channel:read")),
    path: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    _owned(channel_id, job_id)
    record = get_run_store().get_execution(job_id, seq)
    if record is None:
        raise ChannelRunNotFound()
    return output_page(record.output, path, limit=limit, offset=offset)


@router.post("/channels/{channel_id}/runs/{job_id}/template-preview")
def http_preview_template(
    channel_id: str,
    job_id: str,
    body: TemplatePreviewRequest,
    _actor: UserRecord = Depends(require_permission("channel:write")),
) -> dict[str, Any]:
    return preview_template(
        channel_id=channel_id,
        job_id=job_id,
        graph=body.graph.model_dump(mode="json"),
        node_id=body.node_id,
        path=body.path,
    )


def _owned(channel_id: str, job_id: str) -> Any:
    record = get_run_store().get_run(job_id)
    if record is None or record.channel_id != channel_id:
        raise ChannelRunNotFound()
    return record


def _present(job: Any, record: Any) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "status": job.status,
        "outcome": record.outcome,
        "target": record.target,
        "version": record.version,
        "draft_revision": record.draft_revision,
        "trigger_kind": job.trigger_kind,
        "trigger_ref": job.trigger_ref,
        "trigger_node_id": record.trigger_node_id,
        "trigger_actor_name": None,
        "trigger_schedule_name": None,
        "ignore_checkpoints": record.ignore_checkpoints,
        "stop_at_node_id": record.stop_at_node_id,
        "failed_node_id": record.failed_node_id,
        "stopped_node_id": record.stopped_node_id,
        "created_at": format_instant(record.created_at),
        "started_at": format_instant(job.started_at) if job.started_at else None,
        "finished_at": format_instant(job.finished_at) if job.finished_at else None,
        "error_code": job.error_code,
        "error_message": job.error_summary,
    }
