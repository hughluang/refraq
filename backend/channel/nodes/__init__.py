"""Node type catalog.

Each family package holds one module per node type. This module is the only
registry: add a type by importing its ``NODE_TYPE`` and listing it here.
"""

from __future__ import annotations

from backend.channel.nodes.read.entity import NODE_TYPE as READ_ENTITY
from backend.channel.nodes.spec import NodeType
from backend.channel.nodes.trigger.manual import NODE_TYPE as TRIGGER_MANUAL
from backend.channel.nodes.write.entity import NODE_TYPE as WRITE_ENTITY

__all__ = [
    "list_node_types",
]

_FAMILY_ORDER = {
    "trigger": 0,
    "read": 1,
    "write": 2,
}

_CATALOG: tuple[NodeType, ...] = (
    TRIGGER_MANUAL,
    READ_ENTITY,
    WRITE_ENTITY,
)


def list_node_types() -> list[NodeType]:
    return sorted(
        _CATALOG,
        key=lambda item: (_FAMILY_ORDER[item.family], item.type_id),
    )
