"""Node type catalog.

Each family package holds one module per node type. This module is the only
registry: add a type by importing its ``NODE_TYPE`` and listing it here.
"""

from __future__ import annotations

from backend.channel.nodes.read.sql import NODE_TYPE as READ_SQL
from backend.channel.nodes.spec import NodeType
from backend.channel.nodes.state.variable import NODE_TYPE as STATE_VARIABLE
from backend.channel.nodes.trigger.manual import NODE_TYPE as TRIGGER_MANUAL
from backend.channel.nodes.trigger.scheduled import NODE_TYPE as TRIGGER_SCHEDULED
from backend.channel.nodes.write.entity import NODE_TYPE as WRITE_ENTITY

__all__ = [
    "list_node_types",
]

_FAMILY_ORDER = {
    "trigger": 0,
    "read": 1,
    "state": 2,
    "write": 3,
}

_CATALOG: tuple[NodeType, ...] = (
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULED,
    READ_SQL,
    STATE_VARIABLE,
    WRITE_ENTITY,
)


def list_node_types() -> list[NodeType]:
    return sorted(
        _CATALOG,
        key=lambda item: (_FAMILY_ORDER[item.family], item.type_id),
    )
