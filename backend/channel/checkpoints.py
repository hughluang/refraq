"""Durable cursors for checkpoint-owning nodes.

A position is ``(xact, seq)``. Advance keeps the greater of the stored position
and the one a finished run proposed. A run proposes while it executes; the
cursor moves only when that run is settled as a complete success.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, text

from backend.channel.models import ChannelCheckpointRow
from backend.channel.run_store import get_run_store
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now

__all__ = [
    "CheckpointPosition",
    "LocalCheckpoints",
    "RunCheckpoints",
    "advance_from_run",
    "get_checkpoint_store",
    "reset_checkpoint_store",
]


@dataclass(frozen=True, slots=True)
class CheckpointPosition:
    xact: int
    seq: int


def _later(left: CheckpointPosition, right: CheckpointPosition) -> CheckpointPosition:
    if (left.xact, left.seq) >= (right.xact, right.seq):
        return left
    return right


def _ahead(left: CheckpointPosition, right: CheckpointPosition) -> bool:
    return (left.xact, left.seq) > (right.xact, right.seq)


class MemoryCheckpointStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str], CheckpointPosition] = {}
        self._lock = threading.Lock()

    def read(
        self, channel_id: str, node_id: str, stream: str
    ) -> CheckpointPosition | None:
        with self._lock:
            return self._rows.get((channel_id, node_id, stream))

    def advance(
        self,
        channel_id: str,
        node_id: str,
        stream: str,
        position: CheckpointPosition,
    ) -> None:
        key = (channel_id, node_id, stream)
        with self._lock:
            current = self._rows.get(key)
            if current is None or _ahead(position, current):
                self._rows[key] = position

    def delete_for_channel(self, channel_id: str) -> None:
        with self._lock:
            doomed = [key for key in self._rows if key[0] == channel_id]
            for key in doomed:
                del self._rows[key]


class SqlCheckpointStore:
    def read(
        self, channel_id: str, node_id: str, stream: str
    ) -> CheckpointPosition | None:
        with session_scope() as session:
            row = session.scalar(
                select(ChannelCheckpointRow).where(
                    ChannelCheckpointRow.channel_id == channel_id,
                    ChannelCheckpointRow.node_id == node_id,
                    ChannelCheckpointRow.stream == stream,
                )
            )
            if row is None:
                return None
            return CheckpointPosition(
                xact=int(row.position_xact), seq=int(row.position_seq)
            )

    def advance(
        self,
        channel_id: str,
        node_id: str,
        stream: str,
        position: CheckpointPosition,
    ) -> None:
        with session_scope() as session:
            session.execute(
                _ADVANCE,
                {
                    "channel_id": channel_id,
                    "node_id": node_id,
                    "stream": stream,
                    "position_xact": position.xact,
                    "position_seq": position.seq,
                    "updated_at": utc_now(),
                },
            )

    def delete_for_channel(self, channel_id: str) -> None:
        with session_scope() as session:
            session.execute(
                delete(ChannelCheckpointRow).where(
                    ChannelCheckpointRow.channel_id == channel_id
                )
            )


_ADVANCE = text(
    "INSERT INTO channel_checkpoints ("
    "channel_id, node_id, stream, position_xact, position_seq, updated_at"
    ") VALUES ("
    ":channel_id, :node_id, :stream, :position_xact, :position_seq, :updated_at"
    ") ON CONFLICT (channel_id, node_id, stream) DO UPDATE SET "
    "position_xact = CASE "
    "WHEN (EXCLUDED.position_xact, EXCLUDED.position_seq) > "
    "(channel_checkpoints.position_xact, channel_checkpoints.position_seq) "
    "THEN EXCLUDED.position_xact ELSE channel_checkpoints.position_xact END, "
    "position_seq = CASE "
    "WHEN (EXCLUDED.position_xact, EXCLUDED.position_seq) > "
    "(channel_checkpoints.position_xact, channel_checkpoints.position_seq) "
    "THEN EXCLUDED.position_seq ELSE channel_checkpoints.position_seq END, "
    "updated_at = CASE "
    "WHEN (EXCLUDED.position_xact, EXCLUDED.position_seq) > "
    "(channel_checkpoints.position_xact, channel_checkpoints.position_seq) "
    "THEN EXCLUDED.updated_at ELSE channel_checkpoints.updated_at END"
)


class LocalCheckpoints:
    """In-memory session for one run that does not touch the checkpoint store."""

    def __init__(
        self,
        *,
        durable: dict[tuple[str, str], CheckpointPosition] | None = None,
        bound: int = 2**62,
    ) -> None:
        self.durable_positions = dict(durable or {})
        self.bound_value = bound
        self.proposals: dict[tuple[str, str], CheckpointPosition] = {}

    def durable(self, node_id: str, stream: str) -> CheckpointPosition | None:
        return self.durable_positions.get((node_id, stream))

    def proposed(self, node_id: str, stream: str) -> CheckpointPosition | None:
        return self.proposals.get((node_id, stream))

    def stored(self, node_id: str, stream: str) -> CheckpointPosition | None:
        return _max_position(
            self.durable(node_id, stream), self.proposed(node_id, stream)
        )

    def bound(self, node_id: str, stream: str) -> int:
        del node_id, stream
        return self.bound_value

    def propose(self, node_id: str, stream: str, position: CheckpointPosition) -> None:
        key = (node_id, stream)
        current = self.proposals.get(key)
        if current is not None and not _ahead(position, current):
            return
        self.proposals[key] = position


class RunCheckpoints:
    """One run's bounds and proposals. Proposals are written onto the run row."""

    def __init__(self, channel_id: str, run: Any) -> None:
        self._channel_id = channel_id
        self._run = run
        self._bounds: dict[tuple[str, str], int] = {}
        self.proposals = _load_proposals(getattr(run, "checkpoint_proposals", None))

    def durable(self, node_id: str, stream: str) -> CheckpointPosition | None:
        return get_checkpoint_store().read(self._channel_id, node_id, stream)

    def proposed(self, node_id: str, stream: str) -> CheckpointPosition | None:
        return self.proposals.get((node_id, stream))

    def stored(self, node_id: str, stream: str) -> CheckpointPosition | None:
        return _max_position(
            self.durable(node_id, stream), self.proposed(node_id, stream)
        )

    def bound(self, node_id: str, stream: str) -> int:
        key = (node_id, stream)
        if key not in self._bounds:
            from backend.entity.changes import capture_bound

            self._bounds[key] = capture_bound()
        return self._bounds[key]

    def propose(self, node_id: str, stream: str, position: CheckpointPosition) -> None:
        key = (node_id, stream)
        current = self.proposals.get(key)
        if current is not None and not _ahead(position, current):
            return
        self.proposals[key] = position
        blob = _dump_proposals(self.proposals)
        self._run.checkpoint_proposals = blob
        get_run_store().set_checkpoint_proposals(self._run.job_id, blob)


def advance_from_run(run: Any) -> None:
    """Move cursors to the greater of the stored position and this run's proposals.

    A run that did not complete, or that stopped at one node, proposes nothing
    that is kept. Draft and published runs both advance.
    """
    if getattr(run, "outcome", None) != "completed":
        return
    if getattr(run, "stop_at_node_id", None):
        return
    proposals = _load_proposals(getattr(run, "checkpoint_proposals", None))
    store = get_checkpoint_store()
    for (node_id, stream), position in proposals.items():
        store.advance(run.channel_id, node_id, stream, position)


def _max_position(
    left: CheckpointPosition | None, right: CheckpointPosition | None
) -> CheckpointPosition | None:
    if left is None:
        return right
    if right is None:
        return left
    return _later(left, right)


def _load_proposals(blob: Any) -> dict[tuple[str, str], CheckpointPosition]:
    """Read proposals written by ``_dump_proposals``. ``None`` is an empty set."""
    if blob is None:
        return {}
    loaded: dict[tuple[str, str], CheckpointPosition] = {}
    for node_id, streams in blob.items():
        for stream, raw in streams.items():
            loaded[(str(node_id), str(stream))] = CheckpointPosition(
                xact=int(raw["xact"]), seq=int(raw["seq"])
            )
    return loaded


def _dump_proposals(
    proposals: dict[tuple[str, str], CheckpointPosition],
) -> dict[str, dict[str, dict[str, int]]]:
    blob: dict[str, dict[str, dict[str, int]]] = {}
    for (node_id, stream), position in proposals.items():
        blob.setdefault(node_id, {})[stream] = {
            "xact": position.xact,
            "seq": position.seq,
        }
    return blob


_memory: MemoryCheckpointStore | None = None
_lock = threading.Lock()


def get_checkpoint_store() -> MemoryCheckpointStore | SqlCheckpointStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryCheckpointStore()
            return _memory
    return SqlCheckpointStore()


def reset_checkpoint_store() -> None:
    global _memory
    with _lock:
        _memory = None
