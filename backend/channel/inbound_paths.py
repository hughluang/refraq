"""Publish sync of one channel's inbound path."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete

from backend.channel.errors import (
    ChannelInboundCredentialNotFound,
    ChannelInboundPathTaken,
)
from backend.channel.inbound_credentials import get_inbound_credential_store
from backend.channel.models import InboundPathRow
from backend.core.config import get_settings
from backend.core.db import session_scope

__all__ = [
    "InboundPathRecord",
    "get_inbound_path_store",
    "require_inbound_publish",
    "reset_inbound_path_store",
    "sync_published_inbound_path",
]


@dataclass(frozen=True, slots=True)
class InboundPathRecord:
    path: str
    channel_id: str
    node_id: str


class MemoryInboundPathStore:
    def __init__(self) -> None:
        self._rows: dict[str, InboundPathRecord] = {}
        self._lock = threading.Lock()

    def get(self, path: str) -> InboundPathRecord | None:
        with self._lock:
            return self._rows.get(path)

    def claim(self, *, path: str, channel_id: str, node_id: str) -> None:
        with self._lock:
            current = self._rows.get(path)
            if current is not None and current.channel_id != channel_id:
                raise ChannelInboundPathTaken()
            self._rows = {
                key: row
                for key, row in self._rows.items()
                if row.channel_id != channel_id
            }
            self._rows[path] = InboundPathRecord(
                path=path, channel_id=channel_id, node_id=node_id
            )

    def withdraw_channel(self, channel_id: str) -> None:
        with self._lock:
            self._rows = {
                key: row
                for key, row in self._rows.items()
                if row.channel_id != channel_id
            }


class SqlInboundPathStore:
    def get(self, path: str) -> InboundPathRecord | None:
        with session_scope() as session:
            row = session.get(InboundPathRow, path)
            if row is None:
                return None
            return InboundPathRecord(
                path=row.path, channel_id=row.channel_id, node_id=row.node_id
            )

    def claim(self, *, path: str, channel_id: str, node_id: str) -> None:
        with session_scope() as session:
            row = session.get(InboundPathRow, path)
            if row is not None and row.channel_id != channel_id:
                raise ChannelInboundPathTaken()
            session.execute(
                delete(InboundPathRow).where(
                    InboundPathRow.channel_id == channel_id,
                    InboundPathRow.path != path,
                )
            )
            if row is None:
                session.add(
                    InboundPathRow(
                        path=path, channel_id=channel_id, node_id=node_id
                    )
                )
            else:
                row.node_id = node_id

    def withdraw_channel(self, channel_id: str) -> None:
        with session_scope() as session:
            session.execute(
                delete(InboundPathRow).where(
                    InboundPathRow.channel_id == channel_id
                )
            )


_memory: MemoryInboundPathStore | None = None
_lock = threading.Lock()


def get_inbound_path_store() -> MemoryInboundPathStore | SqlInboundPathStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryInboundPathStore()
            return _memory
    return SqlInboundPathStore()


def reset_inbound_path_store() -> None:
    global _memory
    with _lock:
        _memory = None


def _inbound_trigger(graph: dict[str, Any]) -> dict[str, Any] | None:
    triggers = [
        node
        for node in graph.get("nodes") or []
        if isinstance(node, dict) and node.get("type") == "trigger.inbound"
    ]
    if len(triggers) != 1:
        return None
    return triggers[0]


def _config(node: dict[str, Any]) -> dict[str, Any]:
    config = node.get("config")
    if isinstance(config, dict):
        return config
    return {}


def _require_credential(credential_id: object) -> None:
    if (
        not isinstance(credential_id, str)
        or get_inbound_credential_store().get(credential_id) is None
    ):
        raise ChannelInboundCredentialNotFound()


def require_inbound_publish(channel_id: str, graph: dict[str, Any]) -> None:
    """Refuse publish before a version is stored when the path cannot be claimed."""
    node = _inbound_trigger(graph)
    if node is None:
        return
    config = _config(node)
    _require_credential(config.get("credential_id"))
    path = config.get("path")
    if not isinstance(path, str):
        return
    existing = get_inbound_path_store().get(path)
    if existing is not None and existing.channel_id != channel_id:
        raise ChannelInboundPathTaken()


def sync_published_inbound_path(channel_id: str, graph: dict[str, Any]) -> None:
    """Claim this channel's inbound path, or withdraw it when the trigger is not inbound."""
    node = _inbound_trigger(graph)
    if node is None:
        get_inbound_path_store().withdraw_channel(channel_id)
        return
    config = _config(node)
    _require_credential(config.get("credential_id"))
    path = config.get("path")
    if not isinstance(path, str):
        raise ChannelInboundPathTaken()
    get_inbound_path_store().claim(
        path=path, channel_id=channel_id, node_id=str(node["id"])
    )
