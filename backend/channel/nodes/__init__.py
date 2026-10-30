"""Node type catalog.

Each family package holds one module per node type. This module is the only
registry: add a type by importing its ``NODE_TYPE`` and listing it here.
"""

from __future__ import annotations

import importlib

from backend.channel.nodes.read.changes import NODE_TYPE as READ_CHANGES
from backend.channel.nodes.read.source_query import NODE_TYPE as READ_SOURCE_QUERY
from backend.channel.nodes.read.sql import NODE_TYPE as READ_SQL
from backend.channel.nodes.spec import NodeType
from backend.channel.nodes.state.variable import NODE_TYPE as STATE_VARIABLE
from backend.channel.nodes.transform.code import NODE_TYPE as CODE
from backend.channel.nodes.transform.deduplicate import NODE_TYPE as DEDUPLICATE
from backend.channel.nodes.transform.filter import NODE_TYPE as FILTER
from backend.channel.nodes.transform.merge import NODE_TYPE as MERGE
from backend.channel.nodes.transform.set_fields import NODE_TYPE as SET_FIELDS
from backend.channel.nodes.trigger.error import NODE_TYPE as TRIGGER_ERROR
from backend.channel.nodes.trigger.manual import NODE_TYPE as TRIGGER_MANUAL
from backend.channel.nodes.trigger.scheduled import NODE_TYPE as TRIGGER_SCHEDULED
from backend.channel.nodes.action.email import NODE_TYPE as ACTION_EMAIL
from backend.channel.nodes.action.http import NODE_TYPE as ACTION_HTTP
from backend.channel.nodes.action.webhook import NODE_TYPE as ACTION_WEBHOOK
from backend.channel.nodes.volume.batch_read import NODE_TYPE as VOLUME_BATCH_READ
from backend.channel.nodes.volume.dataset_query import NODE_TYPE as VOLUME_DATASET_QUERY
from backend.channel.nodes.volume.materialize import NODE_TYPE as VOLUME_MATERIALIZE
from backend.channel.nodes.volume.until import NODE_TYPE as VOLUME_UNTIL
from backend.channel.nodes.write.entity import NODE_TYPE as WRITE_ENTITY

# `if` and `for` are keywords, so those modules load by name.
_IF = importlib.import_module("backend.channel.nodes.transform.if").NODE_TYPE
_FOR = importlib.import_module("backend.channel.nodes.volume.for").NODE_TYPE

__all__ = [
    "list_node_types",
]

_FAMILY_ORDER = {
    "trigger": 0,
    "read": 1,
    "transform": 2,
    "volume": 3,
    "state": 4,
    "write": 5,
    "action": 6,
}

_CATALOG: tuple[NodeType, ...] = (
    TRIGGER_ERROR,
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULED,
    READ_CHANGES,
    READ_SQL,
    READ_SOURCE_QUERY,
    SET_FIELDS,
    CODE,
    _IF,
    FILTER,
    MERGE,
    DEDUPLICATE,
    _FOR,
    VOLUME_BATCH_READ,
    VOLUME_DATASET_QUERY,
    VOLUME_MATERIALIZE,
    VOLUME_UNTIL,
    STATE_VARIABLE,
    WRITE_ENTITY,
    ACTION_EMAIL,
    ACTION_HTTP,
    ACTION_WEBHOOK,
)


def list_node_types() -> list[NodeType]:
    return sorted(
        _CATALOG,
        key=lambda item: (_FAMILY_ORDER[item.family], item.type_id),
    )
