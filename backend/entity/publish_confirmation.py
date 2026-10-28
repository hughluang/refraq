"""Port the Entity publish preview uses to list incompatible write nodes.

Composition binds a Data Channel adapter. Entity does not import channel.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence

__all__ = [
    "WriteTargetPort",
    "bind_write_target_port",
    "change_log_publish_effect",
    "incompatible_write_nodes",
]


class WriteTargetPort(Protocol):
    def incompatible_writers(
        self, entity_id: str, attributes: Sequence[Any]
    ) -> list[dict[str, Any]]: ...


_port: WriteTargetPort | None = None


def bind_write_target_port(port: WriteTargetPort) -> None:
    global _port
    _port = port


def incompatible_write_nodes(
    entity_id: str, attributes: Sequence[Any]
) -> list[dict[str, Any]]:
    return _port.incompatible_writers(entity_id, attributes)


def change_log_publish_effect(
    *,
    effective_recording: bool,
    effective_retention_days: int | None,
    draft_recording: bool,
    draft_retention_days: int | None,
) -> str:
    """What this Publish will delete. ``none`` adds no confirmation sentence.

    ``delete_all`` is recording turning off. ``delete_expired`` is recording
    staying on while the window becomes shorter. Never-expire is not a window.
    """
    if effective_recording and not draft_recording:
        return "delete_all"
    if (
        effective_recording
        and draft_recording
        and _retention_is_shorter(effective_retention_days, draft_retention_days)
    ):
        return "delete_expired"
    return "none"


def _retention_is_shorter(
    effective_days: int | None, draft_days: int | None
) -> bool:
    if draft_days is None:
        return False
    if effective_days is None:
        return True
    return draft_days < effective_days
