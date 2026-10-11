"""Port the Entity publish preview uses to list incompatible write nodes.

Composition binds a Data Channel adapter. Entity does not import channel.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence

__all__ = [
    "WriteTargetPort",
    "bind_write_target_port",
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
