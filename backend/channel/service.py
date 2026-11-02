"""Data Channel definition use cases: draft, validation, and publish."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from backend.admin.audit import persist_audit_event
from backend.admin.errors import AuthForbidden
from backend.admin.user_store import get_user_store
from backend.channel.errors import (
    ChannelDraftConflict,
    ChannelGraphInvalid,
    ChannelNotFound,
    ChannelRequestInvalid,
    ChannelVersionNotFound,
)
from backend.channel.graph import validate
from backend.channel.checkpoints import get_checkpoint_store
from backend.channel.inbound_paths import (
    get_inbound_path_store,
    require_inbound_publish,
    sync_published_inbound_path,
)
from backend.channel.ids import new_channel_id
from backend.channel.nodes import list_node_types
from backend.channel.nodes.spec import Problem
from backend.channel.references import ChannelReferenceResolver
from backend.channel.run_store import get_run_store
from backend.channel.schedules import (
    cancel_channel_jobs,
    owner_ref_for,
    rename_channel_schedule,
    set_channel_schedule_enabled,
    sync_published_schedule,
)
from backend.channel.store import (
    ChannelRecord,
    ChannelVersionRecord,
    empty_graph,
    get_channel_store,
)
from backend.channel.variables import get_variable_store
from backend.core.time import format_instant, utc_now
from backend.jobs.store import get_job_store
from backend.metadata.source_access import ACCESS_LEVELS, effective_level
from backend.metadata.source_statements import source_identity
from backend.tags.api import (
    KIND_CHANNEL,
    BulkAssignment,
    bulk_add_tags,
    bulk_remove_tags,
    clear_assignment,
    list_subject_ids,
    replace_assignment,
)
from backend.worker.api import withdraw_schedules_by_owner_ref

__all__ = [
    "require_draft_permissions",
    "create_channel",
    "delete_channel",
    "get_channel",
    "get_draft",
    "get_version",
    "list_channels",
    "list_versions",
    "patch_channel",
    "preview_publish",
    "add_channel_tags",
    "remove_channel_tags",
    "replace_channel_tags",
    "set_channel_active",
    "publish_channel",
    "referenced_source_displays",
    "save_draft",
    "validate_draft",
]


def create_channel(
    *,
    name: str,
    description: str | None,
    actor_user_id: str,
    actor_token_id: str | None,
    tag_ids: list[str] | None = None,
    names: list[str] | None = None,
) -> ChannelRecord:
    now = utc_now()
    record = ChannelRecord(
        id=new_channel_id(),
        name=name,
        description=description,
        active=False,
        draft_graph=empty_graph(),
        draft_revision=1,
        draft_updated_at=now,
        created_at=now,
        updated_at=now,
    )
    requested_tag_ids = list(tag_ids or [])
    requested_names = list(names or [])

    def _bind(session: Any) -> None:
        replace_assignment(
            kind=KIND_CHANNEL,
            subject_id=record.id,
            base_revision=1,
            tag_ids=requested_tag_ids,
            names=requested_names,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            session=session,
        )

    saved = get_channel_store().create(record, after=_bind)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=saved.id,
        action="channel.create",
        detail={"name": saved.name},
    )
    return saved


def _tag_subject_ids(tag_ids: list[str] | None) -> frozenset[str] | None:
    """None omits the Tag predicate. A present list matches channels carrying any live id."""

    if tag_ids is None:
        return None
    return frozenset(list_subject_ids(kind=KIND_CHANNEL, tag_ids=tag_ids))


def list_channels(
    *,
    q: str | None,
    active: bool | None,
    tag_ids: list[str] | None = None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[ChannelRecord, tuple[int, datetime] | None]], int]:
    needle = (q or "").strip() or None
    records, total = get_channel_store().list_channels(
        q=needle,
        active=active,
        subject_ids=_tag_subject_ids(tag_ids),
        limit=limit,
        offset=offset,
    )
    latest = get_channel_store().latest_versions([record.id for record in records])
    return [(record, latest.get(record.id)) for record in records], total


def get_channel(
    channel_id: str,
) -> tuple[ChannelRecord, tuple[int, datetime] | None]:
    record = _require(channel_id)
    latest = get_channel_store().latest_versions([channel_id]).get(channel_id)
    return record, latest


def replace_channel_tags(
    *,
    channel_id: str,
    base_revision: int,
    tag_ids: list[str],
    names: list[str],
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    """Replace Tags on one Channel. Does not write the Channel or its draft."""

    with get_channel_store().lock_channel(channel_id) as (session, record):
        if record is None:
            raise ChannelNotFound()
        assignment = replace_assignment(
            kind=KIND_CHANNEL,
            subject_id=record.id,
            base_revision=base_revision,
            tag_ids=tag_ids,
            names=names,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            session=session,
        )
    return {
        "tags": [{"id": tag.id, "name": tag.name} for tag in assignment.tags],
        "tag_revision": assignment.tag_revision,
    }


_BULK_SUBJECT_LIMIT = 200
_BULK_TAG_LIMIT = 10


def add_channel_tags(
    *,
    channel_ids: list[str],
    tag_ids: list[str],
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    """Add Tags to many Channels. A failure writes nothing of the request."""

    subjects, tags = _bulk_ids(channel_ids, tag_ids)
    _require_channel_subjects(subjects)
    return _bulk_payload(
        bulk_add_tags(
            kind=KIND_CHANNEL,
            subject_ids=subjects,
            tag_ids=tags,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
        )
    )


def remove_channel_tags(
    *,
    channel_ids: list[str],
    tag_ids: list[str],
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    """Remove Tags from many Channels. A failure writes nothing of the request."""

    subjects, tags = _bulk_ids(channel_ids, tag_ids)
    _require_channel_subjects(subjects)
    return _bulk_payload(
        bulk_remove_tags(
            kind=KIND_CHANNEL,
            subject_ids=subjects,
            tag_ids=tags,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
        )
    )


def _bulk_ids(
    subject_ids: list[str], tag_ids: list[str]
) -> tuple[list[str], list[str]]:
    subjects = _collapse_ids(subject_ids)
    tags = _collapse_ids(tag_ids)
    if (
        not subjects
        or len(subjects) > _BULK_SUBJECT_LIMIT
        or not tags
        or len(tags) > _BULK_TAG_LIMIT
    ):
        raise ChannelRequestInvalid()
    return subjects, tags


def _collapse_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _require_channel_subjects(channel_ids: list[str]) -> None:
    missing = [
        {"kind": "channel", "id": channel_id}
        for channel_id in channel_ids
        if get_channel_store().get(channel_id) is None
    ]
    if missing:
        raise ChannelNotFound(subjects=missing)


def _bulk_payload(results: list[BulkAssignment]) -> dict[str, Any]:
    return {
        "subjects": [
            {
                "id": item.id,
                "tags": [{"id": tag.id, "name": tag.name} for tag in item.tags],
                "tag_revision": item.tag_revision,
            }
            for item in results
        ]
    }


def patch_channel(
    *,
    channel_id: str,
    name: str | None,
    description: str | None,
    description_set: bool,
    actor_user_id: str,
    actor_token_id: str | None,
) -> tuple[ChannelRecord, tuple[int, datetime] | None]:
    record = _require(channel_id)
    changed = False
    if name is not None and name != record.name:
        record.name = name
        changed = True
    if description_set and description != record.description:
        record.description = description
        changed = True
    if changed:
        record.updated_at = utc_now()
        record = get_channel_store().save(record)
        if name is not None:
            rename_channel_schedule(record)
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_id=record.id,
            action="channel.update",
            detail={"name": record.name},
        )
    latest = get_channel_store().latest_versions([channel_id]).get(channel_id)
    return record, latest


def set_channel_active(
    *,
    channel_id: str,
    active: bool,
    actor_user_id: str,
    actor_token_id: str | None,
) -> tuple[ChannelRecord, tuple[int, datetime] | None]:
    record = _require(channel_id)
    if record.active != active:
        record.active = active
        record.updated_at = utc_now()
        record = get_channel_store().save(record)
        set_channel_schedule_enabled(record, enabled=active)
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_id=record.id,
            action="channel.activate" if active else "channel.deactivate",
            detail={"name": record.name},
        )
    latest = get_channel_store().latest_versions([channel_id]).get(channel_id)
    return record, latest


def delete_channel(
    *,
    channel_id: str,
    actor_user_id: str,
    actor_token_id: str | None,
) -> None:
    if get_channel_store().get(channel_id) is None:
        raise ChannelNotFound()
    withdraw_schedules_by_owner_ref(owner_ref_for(channel_id))
    get_inbound_path_store().withdraw_channel(channel_id)
    cancel_channel_jobs(channel_id)

    def _clear(session: Any) -> None:
        clear_assignment(kind=KIND_CHANNEL, subject_id=channel_id, session=session)

    if not get_channel_store().delete(channel_id, after=_clear):
        raise ChannelNotFound()
    get_variable_store().delete_for_channel(channel_id)
    get_checkpoint_store().delete_for_channel(channel_id)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=channel_id,
        action="channel.delete",
    )


def get_draft(channel_id: str) -> ChannelRecord:
    return _require(channel_id)


def save_draft(
    *,
    channel_id: str,
    base_revision: int,
    graph: dict[str, Any],
    actor_user_id: str,
    actor_token_id: str | None,
    permissions: Sequence[str] = (),
) -> ChannelRecord:
    current = _require(channel_id)
    if current.draft_revision != base_revision:
        raise ChannelDraftConflict()
    require_draft_permissions(current.draft_graph, graph, permissions)
    _require_draft_source_levels(current.draft_graph, graph, actor_user_id)
    saved = get_channel_store().replace_draft(
        channel_id,
        base_revision=base_revision,
        graph=graph,
        now=utc_now(),
    )
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=channel_id,
        action="channel.draft_save",
        detail={"draft_revision": saved.draft_revision},
    )
    return saved


def validate_draft(channel_id: str, graph: Mapping[str, Any]) -> list[Problem]:
    _require(channel_id)
    return validate(graph, ChannelReferenceResolver(channel_id))


def preview_publish(channel_id: str) -> dict[str, Any]:
    record = _require(channel_id)
    return _confirmation(record)


def publish_channel(
    *,
    channel_id: str,
    draft_revision: int,
    actor_user_id: str,
    actor_token_id: str | None,
    permissions: Sequence[str] = (),
) -> tuple[ChannelVersionRecord, dict[str, Any]]:
    record = _require(channel_id)
    if record.draft_revision != draft_revision:
        raise ChannelDraftConflict()
    _require_publish_permissions(record.draft_graph, permissions)
    _require_publish_source_levels(record.draft_graph, actor_user_id)
    problems = validate(record.draft_graph, ChannelReferenceResolver(channel_id))
    errors = [problem for problem in problems if problem.severity == "error"]
    if errors:
        raise ChannelGraphInvalid(errors[0].detail, problems=errors)
    require_inbound_publish(channel_id, record.draft_graph)
    version = get_channel_store().publish_version(
        channel_id,
        draft_revision=draft_revision,
        published_at=utc_now(),
        published_by_user_id=actor_user_id,
    )
    confirmation = _confirmation(record)
    confirmation["draft_revision"] = draft_revision
    sync_published_schedule(record, version.graph)
    sync_published_inbound_path(channel_id, version.graph)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=channel_id,
        action="channel.publish",
        detail={"number": version.number, "draft_revision": draft_revision},
    )
    return version, confirmation


def list_versions(
    channel_id: str, *, limit: int, offset: int
) -> tuple[list[ChannelVersionRecord], int]:
    _require(channel_id)
    return get_channel_store().list_versions(channel_id, limit=limit, offset=offset)


def get_version(channel_id: str, number: int) -> ChannelVersionRecord:
    _require(channel_id)
    version = get_channel_store().get_version(channel_id, number)
    if version is None:
        raise ChannelVersionNotFound()
    return version


def display_names(user_ids: set[str]) -> dict[str, str]:
    users = get_user_store()
    names: dict[str, str] = {}
    for user_id in user_ids:
        user = users.get_by_id(user_id)
        if user is not None:
            names[user_id] = user.display_name
    return names


def _graph_nodes(graph: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [node for node in nodes if isinstance(node, dict)]


def _type_version(node: Mapping[str, Any]) -> int:
    value = node.get("type_version", 1)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 1


def _node_config(node: Mapping[str, Any]) -> Mapping[str, Any]:
    config = node.get("config")
    if isinstance(config, dict):
        return config
    return {}


def _node_label(node: Mapping[str, Any]) -> str:
    name = node.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return str(node.get("id") or "")


def _guarded_changed(stored: Mapping[str, Any] | None, node: Mapping[str, Any]) -> bool:
    if stored is None:
        return True
    if str(stored.get("type")) != str(node.get("type")):
        return True
    if _type_version(stored) != _type_version(node):
        return True
    return dict(_node_config(stored)) != dict(_node_config(node))


def _require_permission_for(
    node: Mapping[str, Any], permission: str, held: set[str]
) -> None:
    if permission in held:
        return
    raise AuthForbidden(f"Node '{_node_label(node)}' requires {permission}")


def require_draft_permissions(
    stored: Mapping[str, Any],
    submitted: Mapping[str, Any],
    permissions: Sequence[str],
) -> None:
    catalog = {item.type_id: item for item in list_node_types()}
    previous = {str(node.get("id")): node for node in _graph_nodes(stored)}
    held = set(permissions)
    for node in _graph_nodes(submitted):
        spec = catalog.get(str(node.get("type")))
        if spec is None or not spec.permission:
            continue
        if not _guarded_changed(previous.get(str(node.get("id"))), node):
            continue
        _require_permission_for(node, spec.permission, held)


def _require_publish_permissions(
    graph: Mapping[str, Any], permissions: Sequence[str]
) -> None:
    catalog = {item.type_id: item for item in list_node_types()}
    held = set(permissions)
    for node in _graph_nodes(graph):
        spec = catalog.get(str(node.get("type")))
        if spec is None or not spec.permission:
            continue
        _require_permission_for(node, spec.permission, held)


_SOURCE_LEVELS = {
    "read.sql": "maintainer",
    "volume.dataset_query": "maintainer",
    "read.source_query": "viewer",
}


def _level_meets(held: str | None, required: str) -> bool:
    if held is None or held not in ACCESS_LEVELS or required not in ACCESS_LEVELS:
        return False
    return ACCESS_LEVELS.index(held) >= ACCESS_LEVELS.index(required)


def _referenced_source(node: Mapping[str, Any]) -> tuple[str, str] | None:
    """Source id and required level for a node that references a Source."""
    type_id = str(node.get("type") or "")
    required = _SOURCE_LEVELS.get(type_id)
    if required is None:
        return None
    config = _node_config(node)
    if type_id == "read.source_query":
        source_id = config.get("source_id")
    else:
        source = config.get("source")
        if not isinstance(source, dict) or source.get("kind") != "source":
            return None
        source_id = source.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        return None
    return source_id, required


def _require_source_level(node: Mapping[str, Any], user_id: str) -> None:
    referenced = _referenced_source(node)
    if referenced is None:
        return
    source_id, required = referenced
    if _level_meets(effective_level(user_id, source_id), required):
        return
    raise AuthForbidden(
        f"Node '{_node_label(node)}' requires {required} on the Source"
    )


def _require_draft_source_levels(
    stored: Mapping[str, Any],
    submitted: Mapping[str, Any],
    user_id: str,
) -> None:
    previous = {str(node.get("id")): node for node in _graph_nodes(stored)}
    for node in _graph_nodes(submitted):
        if not _guarded_changed(previous.get(str(node.get("id"))), node):
            continue
        _require_source_level(node, user_id)


def _require_publish_source_levels(graph: Mapping[str, Any], user_id: str) -> None:
    for node in _graph_nodes(graph):
        _require_source_level(node, user_id)


def referenced_source_displays(
    user_id: str, graph: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Response-only displays. The stored graph is not modified."""
    displays: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in _graph_nodes(graph):
        referenced = _referenced_source(node)
        if referenced is None:
            continue
        source_id = referenced[0]
        if source_id in seen:
            continue
        seen.add(source_id)
        displays.append(_source_display(user_id, source_id))
    return displays


def _source_display(user_id: str, source_id: str) -> dict[str, Any]:
    if effective_level(user_id, source_id) is None:
        return {"source_id": source_id, "inaccessible": True}
    identity = source_identity(source_id)
    if identity is None:
        return {"source_id": source_id}
    key, name = identity
    return {"source_id": source_id, "key": key, "name": name}


def _require(channel_id: str) -> ChannelRecord:
    record = get_channel_store().get(channel_id)
    if record is None:
        raise ChannelNotFound()
    return record


def _confirmation(record: ChannelRecord) -> dict[str, Any]:
    timeout = record.draft_graph["settings"]["run_timeout_sec"]
    return {
        "draft_revision": record.draft_revision,
        "mirrors_to_open": [],
        "runs_to_cancel": _runs_to_cancel(record.id),
        "missing_run_timeout": timeout is None,
    }


def _runs_to_cancel(channel_id: str) -> list[dict[str, Any]]:
    jobs, _total = get_job_store().list(kind="channel_run", status="running")
    items: list[dict[str, Any]] = []
    for job in jobs:
        payload = job.input or {}
        if payload.get("channel_id") != channel_id or payload.get("pin_version"):
            continue
        run = get_run_store().get_run(job.id)
        if run is None or run.target != "published":
            continue
        items.append(
            {
                "job_id": job.id,
                "version": run.version,
                "started_at": format_instant(job.started_at)
                if job.started_at
                else None,
            }
        )
    return items


def _audit(
    *,
    actor_user_id: str,
    actor_token_id: str | None,
    resource_id: str,
    action: str,
    detail: dict[str, Any] | None = None,
) -> None:
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="channel",
        resource_id=resource_id,
        action=action,
        result="success",
        detail=detail,
    )
