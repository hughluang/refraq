"""Project a channel_run Scheduled Task onto the platform schedule list."""

from __future__ import annotations

from backend.channel.store import get_channel_store
from backend.worker.schedules import ScheduledTaskRecord
from backend.worker.schemas.schedules import ScheduleOut, ScheduleTargetOut

__all__ = ["project_channel_schedule"]


def project_channel_schedule(
    record: ScheduledTaskRecord, projected: ScheduleOut
) -> ScheduleOut:
    """Fill work_kind and target for a channel row. Other rows pass through."""
    if not record.key.startswith("channel_run:"):
        return projected
    channel_id = record.kwargs_json["channel_id"]
    node_id = record.kwargs_json["node_id"]
    channel_name, node_name = _names(channel_id, node_id)
    return projected.model_copy(
        update={
            "work_kind": "channel_run",
            "target": ScheduleTargetOut(
                channel_id=channel_id,
                channel_name=channel_name,
                node_id=node_id,
                node_name=node_name,
            ),
        }
    )


def _names(channel_id: str, node_id: str) -> tuple[str | None, str | None]:
    channel = get_channel_store().get(channel_id)
    if channel is None:
        return None, None
    node_name = None
    versions, _total = get_channel_store().list_versions(channel_id, limit=1, offset=0)
    if versions:
        for node in versions[0].graph.get("nodes") or []:
            if node.get("id") == node_id and isinstance(node.get("name"), str):
                node_name = node["name"]
                break
    return channel.name, node_name
