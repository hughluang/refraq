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
    ChannelVersionNotFound,
)
from backend.channel.graph import validate
from backend.channel.ids import new_channel_id
from backend.channel.nodes import list_node_types
from backend.channel.nodes.spec import Problem
from backend.channel.references import ChannelReferenceResolver
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
from backend.channel.run_store import get_run_store
from backend.core.time import format_instant, utc_now
from backend.jobs.store import get_job_store
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
    "set_channel_active",
    "publish_channel",
    "save_draft",
    "validate_draft",
]


def create_channel(
    *,
    name: str,
    description: str | None,
    actor_user_id: str,
    actor_token_id: str | None,
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
    saved = get_channel_store().create(record)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=saved.id,
        action="channel.create",
        detail={"name": saved.name},
    )
    return saved


def list_channels(
    *,
    q: str | None,
    active: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[ChannelRecord, tuple[int, datetime] | None]], int]:
    needle = (q or "").strip() or None
    records, total = get_channel_store().list_channels(
        q=needle, active=active, limit=limit, offset=offset
    )
    latest = get_channel_store().latest_versions([record.id for record in records])
    return [(record, latest.get(record.id)) for record in records], total


def get_channel(
    channel_id: str,
) -> tuple[ChannelRecord, tuple[int, datetime] | None]:
    record = _require(channel_id)
    latest = get_channel_store().latest_versions([channel_id]).get(channel_id)
    return record, latest


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
    cancel_channel_jobs(channel_id)
    if not get_channel_store().delete(channel_id):
        raise ChannelNotFound()
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
    problems = validate(record.draft_graph, ChannelReferenceResolver(channel_id))
    errors = [problem for problem in problems if problem.severity == "error"]
    if errors:
        raise ChannelGraphInvalid(errors[0].detail, problems=errors)
    version = get_channel_store().publish_version(
        channel_id,
        draft_revision=draft_revision,
        published_at=utc_now(),
        published_by_user_id=actor_user_id,
    )
    confirmation = _confirmation(record)
    confirmation["draft_revision"] = draft_revision
    sync_published_schedule(record, version.graph)
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


def _require_permission_for(node: Mapping[str, Any], permission: str, held: set[str]) -> None:
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


def _require_publish_permissions(graph: Mapping[str, Any], permissions: Sequence[str]) -> None:
    catalog = {item.type_id: item for item in list_node_types()}
    held = set(permissions)
    for node in _graph_nodes(graph):
        spec = catalog.get(str(node.get("type")))
        if spec is None or not spec.permission:
            continue
        _require_permission_for(node, spec.permission, held)


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
        if (job.input or {}).get("channel_id") != channel_id:
            continue
        run = get_run_store().get_run(job.id)
        if run is None or run.target != "published":
            continue
        items.append(
            {
                "job_id": job.id,
                "version": run.version,
                "started_at": format_instant(job.started_at) if job.started_at else None,
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
