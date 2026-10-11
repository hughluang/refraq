"""Data Channel HTTP adapters."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response, status

from backend.admin.deps import (
    get_actor_token_id,
    require_permission,
)
from backend.admin.user_store import UserRecord
from backend.channel.nodes import list_node_types
from backend.channel.nodes.spec import NodeType
from backend.channel.schemas.channels import (
    ChannelCreateRequest,
    ChannelListResponse,
    ChannelOut,
    ChannelPatchRequest,
    ChannelResponse,
    ConfirmationOut,
    DraftPutRequest,
    DraftResponse,
    LatestVersionOut,
    NodeTypeListResponse,
    NodeTypeOut,
    RefinedPortOut,
    PortOut,
    ProblemOut,
    PublishRequest,
    PublishResponse,
    ValidateResponse,
    VersionListResponse,
    VersionOut,
    VersionResponse,
    VersionSummaryOut,
)
from backend.channel.graph import refine_ports
from backend.channel.references import ChannelReferenceResolver
from backend.channel.service import (
    create_channel,
    delete_channel,
    display_names,
    get_channel,
    get_draft,
    get_version,
    list_channels,
    list_versions,
    patch_channel,
    preview_publish,
    set_channel_active,
    publish_channel,
    save_draft,
    validate_draft,
)
from backend.channel.store import ChannelRecord, ChannelVersionRecord
from backend.core.pagination import PageBounds, PageParams, page_params

router = APIRouter(tags=["channels"])

CHANNEL_PAGE = PageBounds(default_limit=50, max_limit=200)


def _channel_out(
    record: ChannelRecord,
    latest: tuple[int, datetime] | None,
) -> ChannelOut:
    latest_out = None
    if latest is not None:
        number, published_at = latest
        latest_out = LatestVersionOut(number=number, published_at=published_at)
    return ChannelOut(
        id=record.id,
        name=record.name,
        description=record.description,
        active=record.active,
        draft_revision=record.draft_revision,
        draft_updated_at=record.draft_updated_at,
        latest_version=latest_out,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _draft_out(record: ChannelRecord) -> DraftResponse:
    return DraftResponse(
        draft_revision=record.draft_revision,
        draft_updated_at=record.draft_updated_at,
        graph=record.draft_graph,
    )


def _version_summary(
    record: ChannelVersionRecord, names: dict[str, str]
) -> VersionSummaryOut:
    return VersionSummaryOut(
        channel_id=record.channel_id,
        number=record.number,
        published_at=record.published_at,
        published_by_user_id=record.published_by_user_id,
        published_by_name=names.get(record.published_by_user_id),
    )


def _version_out(record: ChannelVersionRecord, names: dict[str, str]) -> VersionOut:
    summary = _version_summary(record, names)
    return VersionOut(
        channel_id=summary.channel_id,
        number=summary.number,
        published_at=summary.published_at,
        published_by_user_id=summary.published_by_user_id,
        published_by_name=summary.published_by_name,
        graph=record.graph,
    )


def _node_type_out(spec: NodeType) -> NodeTypeOut:
    return NodeTypeOut(
        type=spec.type_id,
        family=spec.family,
        label=spec.label,
        summary=spec.summary,
        description=spec.description,
        entry=spec.entry,
        inputs=[
            PortOut(
                port=port.port,
                description=port.description,
                coarse_type=port.coarse_type,
            )
            for port in spec.inputs
        ],
        outputs=[
            PortOut(
                port=port.port,
                description=port.description,
                coarse_type=port.coarse_type,
            )
            for port in spec.outputs
        ],
        config_schema=spec.config_schema,
        permission=spec.permission,
        type_version=spec.type_version,
    )


@router.get("/channel-node-types", response_model=NodeTypeListResponse)
def http_list_node_types(
    user: UserRecord = Depends(require_permission("channel:read")),
) -> NodeTypeListResponse:
    del user
    return NodeTypeListResponse(
        items=[_node_type_out(item) for item in list_node_types()]
    )


@router.post(
    "/channels", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED
)
def http_create_channel(
    body: ChannelCreateRequest,
    user: UserRecord = Depends(require_permission("channel:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> ChannelResponse:
    record = create_channel(
        name=body.name,
        description=body.description,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return ChannelResponse(channel=_channel_out(record, None))


@router.get("/channels", response_model=ChannelListResponse)
def http_list_channels(
    q: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    page: PageParams = Depends(page_params(CHANNEL_PAGE)),
    user: UserRecord = Depends(require_permission("channel:read")),
) -> ChannelListResponse:
    del user
    items, total = list_channels(
        q=q, active=active, limit=page.limit, offset=page.offset
    )
    return ChannelListResponse(
        items=[_channel_out(record, latest) for record, latest in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/channels/{channel_id}", response_model=ChannelResponse)
def http_get_channel(
    channel_id: str,
    user: UserRecord = Depends(require_permission("channel:read")),
) -> ChannelResponse:
    del user
    record, latest = get_channel(channel_id)
    return ChannelResponse(channel=_channel_out(record, latest))


@router.patch("/channels/{channel_id}", response_model=ChannelResponse)
def http_patch_channel(
    channel_id: str,
    body: ChannelPatchRequest,
    user: UserRecord = Depends(require_permission("channel:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> ChannelResponse:
    provided = body.model_dump(exclude_unset=True)
    record, latest = patch_channel(
        channel_id=channel_id,
        name=body.name if "name" in provided else None,
        description=body.description if "description" in provided else None,
        description_set="description" in provided,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return ChannelResponse(channel=_channel_out(record, latest))


@router.post("/channels/{channel_id}/activate", response_model=ChannelResponse)
def http_activate_channel(
    channel_id: str,
    user: UserRecord = Depends(require_permission("channel:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> ChannelResponse:
    record, latest = set_channel_active(
        channel_id=channel_id,
        active=True,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return ChannelResponse(channel=_channel_out(record, latest))


@router.post("/channels/{channel_id}/deactivate", response_model=ChannelResponse)
def http_deactivate_channel(
    channel_id: str,
    user: UserRecord = Depends(require_permission("channel:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> ChannelResponse:
    record, latest = set_channel_active(
        channel_id=channel_id,
        active=False,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return ChannelResponse(channel=_channel_out(record, latest))


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def http_delete_channel(
    channel_id: str,
    user: UserRecord = Depends(require_permission("channel:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response:
    delete_channel(
        channel_id=channel_id,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/channels/{channel_id}/draft", response_model=DraftResponse)
def http_get_draft(
    channel_id: str,
    user: UserRecord = Depends(require_permission("channel:read")),
) -> DraftResponse:
    del user
    return _draft_out(get_draft(channel_id))


@router.put("/channels/{channel_id}/draft", response_model=DraftResponse)
def http_put_draft(
    channel_id: str,
    body: DraftPutRequest,
    user: UserRecord = Depends(require_permission("channel:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> DraftResponse:
    saved = save_draft(
        channel_id=channel_id,
        base_revision=body.base_revision,
        graph=body.graph.model_dump(mode="json"),
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return _draft_out(saved)


@router.post("/channels/{channel_id}/draft/validate", response_model=ValidateResponse)
def http_validate_draft(
    channel_id: str,
    user: UserRecord = Depends(require_permission("channel:write")),
) -> ValidateResponse:
    del user
    record, problems = validate_draft(channel_id)
    ports = refine_ports(record.draft_graph, ChannelReferenceResolver(channel_id))
    errors = [problem for problem in problems if problem.severity == "error"]
    return ValidateResponse(
        draft_revision=record.draft_revision,
        valid=not errors,
        problems=[
            ProblemOut(
                code=problem.code,
                node_id=problem.node_id,
                edge_id=problem.edge_id,
                detail=problem.detail,
                severity=problem.severity if problem.severity == "warning" else "error",
            )
            for problem in problems
        ],
        ports=[
            RefinedPortOut(
                node_id=port.node_id,
                port=port.port,
                direction=port.direction
                if port.direction in {"input", "output"}
                else "output",
                coarse_type=port.coarse_type,
                value_schema=port.schema,
            )
            for port in ports
        ],
    )


@router.post("/channels/{channel_id}/publish/preview", response_model=ConfirmationOut)
def http_preview_publish(
    channel_id: str,
    user: UserRecord = Depends(require_permission("channel:write")),
) -> ConfirmationOut:
    del user
    return ConfirmationOut.model_validate(preview_publish(channel_id))


@router.post(
    "/channels/{channel_id}/publish",
    response_model=PublishResponse,
    status_code=status.HTTP_201_CREATED,
)
def http_publish(
    channel_id: str,
    body: PublishRequest,
    user: UserRecord = Depends(require_permission("channel:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> PublishResponse:
    version, confirmation = publish_channel(
        channel_id=channel_id,
        draft_revision=body.draft_revision,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    names = display_names({version.published_by_user_id})
    return PublishResponse(
        version=_version_out(version, names),
        confirmation=ConfirmationOut.model_validate(confirmation),
    )


@router.get("/channels/{channel_id}/versions", response_model=VersionListResponse)
def http_list_versions(
    channel_id: str,
    page: PageParams = Depends(page_params(CHANNEL_PAGE)),
    user: UserRecord = Depends(require_permission("channel:read")),
) -> VersionListResponse:
    del user
    records, total = list_versions(channel_id, limit=page.limit, offset=page.offset)
    names = display_names({record.published_by_user_id for record in records})
    return VersionListResponse(
        items=[_version_summary(record, names) for record in records],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/channels/{channel_id}/versions/{number}", response_model=VersionResponse)
def http_get_version(
    channel_id: str,
    number: int,
    user: UserRecord = Depends(require_permission("channel:read")),
) -> VersionResponse:
    del user
    record = get_version(channel_id, number)
    names = display_names({record.published_by_user_id})
    return VersionResponse(version=_version_out(record, names))
