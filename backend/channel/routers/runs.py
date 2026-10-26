"""On-demand runs and run records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.channel.dataset_registry import get_dataset_store
from backend.channel.errors import (
    ChannelDatasetUnavailable,
    ChannelRequestInvalid,
    ChannelRunNotFound,
)
from backend.channel.graph import CONTAINER_TYPES
from backend.channel.run_store import (
    ContainerRoundRecord,
    NodeExecutionRecord,
    get_run_store,
    output_page,
    output_preview_with_truncated,
)
from backend.channel.runs import rerun_failed, start_run
from backend.channel.sql_read import jsonable_cell
from backend.channel.values import temporal_kinds_by_name
from backend.channel.schemas.channels import GraphIn
from backend.channel.template_preview import node_sample, preview_template
from backend.core.pagination import PageParams, page_params
from backend.core.time import Instant, format_instant, utc_now
from backend.entity.datasets import any_row_exists, read_keyset_page
from backend.jobs.store import get_job_store

router = APIRouter(tags=["channels"])


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: Literal["draft", "published"] = "published"
    ignore_checkpoints: bool = False
    stop_at_node_id: str | None = None


class ScopeLevelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    container_node_id: str = Field(min_length=1, max_length=64)
    round: int = Field(ge=0)


class TemplatePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: GraphIn
    node_id: str = Field(min_length=1, max_length=64)
    path: list[str | int] = Field(min_length=1)
    scope: list[ScopeLevelIn] | None = None


class NodeSampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: GraphIn
    node_id: str = Field(min_length=1, max_length=64)
    scope: list[ScopeLevelIn] | None = None
    container_round: int | None = Field(default=None, ge=0)


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
    input_preview: Any = None
    input_truncated: bool = False
    input_totals: dict[str, int] | None = None


class NodeSummaryOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    node_id: str
    execution_count: int
    status_counts: dict[str, int]


class ChannelRunDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run: ChannelRunOut
    node_summaries: list[NodeSummaryOut]


class ExecutionListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[NodeExecutionOut]
    total: int
    limit: int
    offset: int


class ContainerRoundOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    round: int
    step_preview: Any = None
    step_truncated: bool = False
    step_totals: dict[str, int] = Field(default_factory=dict)
    status_counts: dict[str, int] = Field(default_factory=dict)


class ContainerRoundListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[ContainerRoundOut]
    total: int
    limit: int
    offset: int


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


@router.post(
    "/channels/{channel_id}/runs/{job_id}/rerun",
    status_code=202,
    response_model=ChannelRunStartResponse,
)
def http_rerun(
    channel_id: str,
    job_id: str,
    actor: UserRecord = Depends(require_permission("channel:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Any:
    job, _record = rerun_failed(
        channel_id=channel_id,
        job_id=job_id,
        actor=actor,
        actor_token_id=actor_token_id,
    )
    stored = get_run_store().get_run(job.id)
    current = get_job_store().get(job.id)
    if stored is None or current is None:
        raise ChannelRunNotFound()
    return {"run": _present(current, stored)}


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
    summaries = [
        {
            "node_id": item.node_id,
            "execution_count": item.execution_count,
            "status_counts": item.status_counts,
        }
        for item in get_run_store().execution_summaries(job_id)
    ]
    return {"run": _present(job, record), "graph": record.graph, "node_summaries": summaries}


@router.get(
    "/channels/{channel_id}/runs/{job_id}/executions",
    response_model=ExecutionListResponse,
)
def http_list_executions(
    channel_id: str,
    job_id: str,
    _actor: UserRecord = Depends(require_permission("channel:read")),
    node_id: str | None = None,
    container_seq: int | None = None,
    round_index: int | None = Query(default=None, alias="round"),
    status: Literal["running", "succeeded", "failed", "skipped"] | None = None,
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
) -> dict[str, Any]:
    _owned(channel_id, job_id)
    items, total = get_run_store().query_executions(
        job_id,
        node_id=node_id,
        container_seq=container_seq,
        round_index=round_index,
        status=status,
        limit=page.limit,
        offset=page.offset,
    )
    return {
        "items": [_execution_body(item) for item in items],
        "total": total,
        "limit": page.limit,
        "offset": page.offset,
    }


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


@router.get(
    "/channels/{channel_id}/runs/{job_id}/executions/{seq}/rounds",
    response_model=ContainerRoundListResponse,
)
def http_execution_rounds(
    channel_id: str,
    job_id: str,
    seq: int,
    _actor: UserRecord = Depends(require_permission("channel:read")),
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
) -> dict[str, Any]:
    run = _owned(channel_id, job_id)
    record = get_run_store().get_execution(job_id, seq)
    if record is None:
        raise ChannelRunNotFound()
    if not _is_container(run, record):
        raise ChannelRequestInvalid("Execution is not a container")
    items, total = get_run_store().query_rounds(
        job_id, seq, limit=page.limit, offset=page.offset
    )
    counts = get_run_store().round_status_counts(job_id, seq)
    return {
        "items": [_round_body(item, counts.get(item.round, {})) for item in items],
        "total": total,
        "limit": page.limit,
        "offset": page.offset,
    }


@router.get("/channels/{channel_id}/runs/{job_id}/datasets/{dataset_id}/rows")
def http_dataset_rows(
    channel_id: str,
    job_id: str,
    dataset_id: str,
    _actor: UserRecord = Depends(require_permission("channel:read")),
    after_ord: int = Query(default=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Page dataset rows. This read does not consult the capacity ceiling."""
    _owned(channel_id, job_id)
    record = get_dataset_store().get(dataset_id)
    if record is None:
        raise ChannelDatasetUnavailable("not_found")
    if record.job_id != job_id:
        raise ChannelDatasetUnavailable("foreign_run")
    if record.expires_at is not None and record.expires_at <= utc_now():
        raise ChannelDatasetUnavailable("expired")
    if record.status != "ready":
        raise ChannelDatasetUnavailable("not_found")
    # Lost means the registry still counts rows and the table has none.
    # EXISTS, not count(*).
    if record.row_count > 0 and not any_row_exists(record.relation):
        raise ChannelDatasetUnavailable("lost")
    fetched = read_keyset_page(record.relation, after_ord=after_ord, limit=limit + 1)
    kinds = temporal_kinds_by_name(record.columns)
    items = [_present_dataset_row(row, kinds) for row in fetched[:limit]]
    next_after_ord = int(items[-1]["_ord"]) if len(fetched) > limit else None
    return {"items": items, "limit": limit, "next_after_ord": next_after_ord}


def _present_dataset_row(row: Mapping[str, Any], kinds: Mapping[str, str]) -> dict[str, Any]:
    """Encode declared temporal cells. Other cells stay as the driver returned them."""
    presented: dict[str, Any] = {}
    for key, value in row.items():
        name = str(key)
        kind = kinds.get(name)
        presented[name] = value if kind is None else jsonable_cell(value, kind)
    return presented


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
        scope=_scope_arg(body.scope),
    )


@router.post("/channels/{channel_id}/runs/{job_id}/node-sample")
def http_node_sample(
    channel_id: str,
    job_id: str,
    body: NodeSampleRequest,
    _actor: UserRecord = Depends(require_permission("channel:write")),
) -> dict[str, Any]:
    """Read a Node Sample. The request executes no node and writes nothing."""
    return node_sample(
        channel_id=channel_id,
        job_id=job_id,
        graph=body.graph.model_dump(mode="json"),
        node_id=body.node_id,
        scope=_scope_arg(body.scope),
        container_round=body.container_round,
    )


def _execution_body(item: NodeExecutionRecord) -> dict[str, Any]:
    preview, truncated = output_preview_with_truncated(item.output)
    input_preview, input_truncated = output_preview_with_truncated(
        item.input, totals=item.input_totals
    )
    return {
        "seq": item.seq,
        "node_id": item.node_id,
        "container_seq": item.container_seq,
        "round": item.round,
        "status": item.status,
        "started_at": format_instant(item.started_at) if item.started_at else None,
        "finished_at": format_instant(item.finished_at) if item.finished_at else None,
        "output_bytes": item.output_bytes,
        "output_preview": preview,
        "output_truncated": truncated,
        "input_preview": input_preview,
        "input_truncated": input_truncated,
        "input_totals": item.input_totals,
        "preview_only": item.preview_only,
        "preview_totals": item.preview_totals,
        "error_code": item.error_code,
        "error_message": item.error_message,
        "error_detail": item.error_detail,
    }


def _round_body(
    item: ContainerRoundRecord, status_counts: dict[str, int]
) -> dict[str, Any]:
    preview, truncated = output_preview_with_truncated(item.step, totals=item.step_totals)
    return {
        "round": item.round,
        "step_preview": preview,
        "step_truncated": truncated,
        "step_totals": item.step_totals,
        "status_counts": status_counts,
    }


def _is_container(run: Any, record: NodeExecutionRecord) -> bool:
    graph = run.graph if isinstance(getattr(run, "graph", None), dict) else None
    nodes = graph.get("nodes") if graph is not None else None
    if not isinstance(nodes, list):
        return False
    for node in nodes:
        if isinstance(node, dict) and str(node.get("id")) == record.node_id:
            return str(node.get("type")) in CONTAINER_TYPES
    return False


def _scope_arg(scope: list[ScopeLevelIn] | None) -> list[dict[str, Any]] | None:
    if scope is None:
        return None
    return [item.model_dump() for item in scope]


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
