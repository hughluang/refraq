"""Durable cursors for checkpoint-owning nodes.

A position is ``(commit_seq, seq)``. The stored field ``xact`` holds the commit
sequence assigned when the writing transaction commits. Advance keeps the
greater of the stored position and the one a finished run proposed. A run
proposes while it executes; the cursor moves only when that run is settled as
a complete success.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, text

from backend.channel.models import ChannelCheckpointRow
from backend.channel.run_store import get_run_store
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now
from backend.entity.changes import capture_bound, commit_seq_ready, legacy_commit_position
from backend.metadata.mirrors.history import settlement_guard

__all__ = [
    "CheckpointPosition",
    "MirrorCheckpointPosition",
    "LocalCheckpoints",
    "RunCheckpoints",
    "advance_from_run",
    "advance_from_run_in_session",
    "get_checkpoint_store",
    "reset_checkpoint_store",
]


@dataclass(frozen=True, slots=True)
class CheckpointPosition:
    """One cursor. ``xact`` stores ``commit_seq``; ``seq`` is the log sequence."""

    xact: int
    seq: int


@dataclass(frozen=True, slots=True)
class MirrorCheckpointPosition:
    """Mirror lineage is separate from the legacy Entity transaction cursor."""

    history_epoch: str
    commit_seq: int
    entry_seq: int
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.history_epoch, str)
            or not self.history_epoch
            or len(self.history_epoch) > 64
            or self.commit_seq < 0
            or self.entry_seq < 0
        ):
            raise ValueError("Invalid mirror checkpoint position")
        if not self.source_ids or any(not value for value in self.source_ids):
            raise ValueError("Mirror checkpoint requires Source provenance")


Position = CheckpointPosition | MirrorCheckpointPosition


def _position_key(position: Position) -> tuple[int, int]:
    if isinstance(position, MirrorCheckpointPosition):
        return position.commit_seq, position.entry_seq
    return position.xact, position.seq


def _compatible(left: Position, right: Position) -> None:
    if type(left) is not type(right):
        raise ValueError("Checkpoint stream kind mismatch")
    if isinstance(left, MirrorCheckpointPosition) and (
        left.history_epoch != right.history_epoch
        or set(left.source_ids) != set(right.source_ids)
    ):
        raise ValueError("Mirror checkpoint epoch or Source provenance mismatch")


def _later(left: Position, right: Position) -> Position:
    _compatible(left, right)
    return left if _position_key(left) >= _position_key(right) else right


def _ahead(left: Position, right: Position) -> bool:
    _compatible(left, right)
    return _position_key(left) > _position_key(right)


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
        if isinstance(position, MirrorCheckpointPosition):
            raise ValueError("Mirror settlement requires a management transaction")
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
        adopt_commit_order()
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
            if row.stream_kind == "mirror":
                return MirrorCheckpointPosition(
                    history_epoch=row.history_epoch,
                    commit_seq=int(row.position_xact),
                    entry_seq=int(row.position_seq),
                    source_ids=tuple(row.source_ids or ()),
                )
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
        if isinstance(position, MirrorCheckpointPosition):
            raise ValueError("Mirror settlement requires a management transaction")
        adopt_commit_order()
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
    "THEN EXCLUDED.updated_at ELSE channel_checkpoints.updated_at END "
    "WHERE channel_checkpoints.stream_kind = 'entity'"
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
        adopt_commit_order()
        blob = _proposal_blob(run)
        run.checkpoint_proposals = blob
        self.proposals = _load_proposals(blob)

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
            self._bounds[key] = capture_bound(stream)
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
    adopt_commit_order()
    proposals = _load_proposals(_proposal_blob(run))
    if any(isinstance(p, MirrorCheckpointPosition) for p in proposals.values()):
        if get_settings().store_backend != "persistent":
            raise ValueError("Mirror settlement requires a management transaction")
        run.checkpoint_proposals = _dump_proposals(proposals)
        with session_scope() as session:
            advance_from_run_in_session(session, run)
        return
    store = get_checkpoint_store()
    for (node_id, stream), position in proposals.items():
        store.advance(run.channel_id, node_id, stream, position)


def advance_from_run_in_session(session: Any, run: Any) -> None:
    """Validate all Mirror gates before updating cursors; never commit the session."""
    if getattr(run, "outcome", None) != "completed" or getattr(
        run, "stop_at_node_id", None
    ):
        return
    proposals = _load_proposals(getattr(run, "checkpoint_proposals", None))
    mirrors = [
        dict(
            mirror_id=stream,
            history_epoch=p.history_epoch,
            position=dict(
                mirror_id=stream,
                history_epoch=p.history_epoch,
                commit_seq=p.commit_seq,
                entry_seq=p.entry_seq,
            ),
            source_ids=list(p.source_ids),
        )
        for (_, stream), p in sorted(proposals.items())
        if isinstance(p, MirrorCheckpointPosition)
    ]
    mirrors.sort(key=lambda proposal: proposal["mirror_id"])
    if mirrors:
        execution_user_id = getattr(run, "mirror_execution_user_id", None)
        if not execution_user_id:
            raise ValueError(
                "Mirror settlement requires an explicit execution identity"
            )
        if not session.in_transaction():
            session.begin()
        settlement_guard(
            session, proposals=mirrors, execution_user_id=execution_user_id
        )
    for (node_id, stream), position in sorted(proposals.items()):
        if isinstance(position, MirrorCheckpointPosition):
            current = (
                session.execute(
                    text(
                        "SELECT stream_kind, history_epoch, source_ids FROM channel_checkpoints "
                        "WHERE channel_id=:channel_id AND node_id=:node_id AND stream=:stream FOR UPDATE"
                    ),
                    dict(channel_id=run.channel_id, node_id=node_id, stream=stream),
                )
                .mappings()
                .first()
            )
            if current is not None:
                source_ids = current["source_ids"]
                if isinstance(source_ids, str):
                    source_ids = json.loads(source_ids)
                if (
                    current["stream_kind"] != "mirror"
                    or current["history_epoch"] != position.history_epoch
                    or set(source_ids or ()) != set(position.source_ids)
                ):
                    raise ValueError(
                        "Mirror checkpoint epoch or Source provenance mismatch"
                    )
            session.execute(
                _ADVANCE_MIRROR,
                dict(
                    channel_id=run.channel_id,
                    node_id=node_id,
                    stream=stream,
                    history_epoch=position.history_epoch,
                    commit_seq=position.commit_seq,
                    entry_seq=position.entry_seq,
                    source_ids=json.dumps(list(position.source_ids)),
                    updated_at=utc_now(),
                ),
            )
        else:
            session.execute(
                _ADVANCE,
                dict(
                    channel_id=run.channel_id,
                    node_id=node_id,
                    stream=stream,
                    position_xact=position.xact,
                    position_seq=position.seq,
                    updated_at=utc_now(),
                ),
            )


_ADVANCE_MIRROR = text(
    "INSERT INTO channel_checkpoints "
    "(channel_id, node_id, stream, stream_kind, history_epoch, source_ids, "
    "position_xact, position_seq, updated_at) VALUES "
    "(:channel_id, :node_id, :stream, 'mirror', :history_epoch, CAST(:source_ids AS jsonb), "
    ":commit_seq, :entry_seq, :updated_at) "
    "ON CONFLICT (channel_id, node_id, stream) DO UPDATE SET "
    "position_xact=EXCLUDED.position_xact, position_seq=EXCLUDED.position_seq, "
    "updated_at=EXCLUDED.updated_at "
    "WHERE channel_checkpoints.stream_kind='mirror' "
    "AND channel_checkpoints.history_epoch=EXCLUDED.history_epoch "
    "AND (EXCLUDED.position_xact, EXCLUDED.position_seq) > "
    "(channel_checkpoints.position_xact, channel_checkpoints.position_seq)"
)


def _max_position(
    left: CheckpointPosition | None, right: CheckpointPosition | None
) -> CheckpointPosition | None:
    if left is None:
        return right
    if right is None:
        return left
    return _later(left, right)


def _proposal_blob(run: Any) -> Any:
    """Proposals stored for this run. A persistent run is read from the row."""
    if get_settings().store_backend != "persistent":
        return getattr(run, "checkpoint_proposals", None)
    with session_scope() as session:
        return session.execute(
            text(
                "SELECT checkpoint_proposals FROM channel_runs WHERE job_id = :job_id"
            ),
            {"job_id": run.job_id},
        ).scalar()


_adopted = False
_adopt_guard = threading.Lock()


def adopt_commit_order() -> bool:
    """Rewrite stored transaction ids into commit sequences once.

    Returns true only when this call performs the rewrite. A memory store and a
    database that has not yet added the epoch row are left unchanged.
    """
    global _adopted
    if _adopted or get_settings().store_backend != "persistent":
        return False
    with _adopt_guard:
        return _adopt_once()


def _adopt_once() -> bool:
    global _adopted
    with session_scope() as session:
        if (
            session.execute(
                text("SELECT to_regclass('public.change_log_cursor_epoch')")
            ).scalar()
            is None
        ):
            return False
        adopted = session.execute(
            text("SELECT adopted FROM change_log_cursor_epoch WHERE id = 1 FOR UPDATE")
        ).scalar()
        if adopted:
            _adopted = True
            return False
        rows = session.execute(
            text(
                "SELECT channel_id, node_id, stream, position_xact, position_seq "
                "FROM channel_checkpoints WHERE stream_kind = 'entity'"
            )
        ).all()
        mapped: list[tuple[Any, CheckpointPosition]] = []
        if rows:
            if not commit_seq_ready():
                return False

            for row in rows:
                mapped.append(
                    (
                        row,
                        legacy_commit_position(
                            str(row.stream),
                            int(row.position_xact),
                            int(row.position_seq),
                        ),
                    )
                )
        for row, position in mapped:
            session.execute(
                text(
                    "UPDATE channel_checkpoints "
                    "SET position_xact = :commit_seq, position_seq = :seq "
                    "WHERE channel_id = :channel_id AND node_id = :node_id "
                    "AND stream = :stream"
                ),
                {
                    "commit_seq": position.xact,
                    "seq": position.seq,
                    "channel_id": row.channel_id,
                    "node_id": row.node_id,
                    "stream": row.stream,
                },
            )
        session.execute(
            text(
                "UPDATE channel_runs SET checkpoint_proposals = NULL "
                "WHERE checkpoint_proposals IS NOT NULL"
            )
        )
        session.execute(
            text("UPDATE change_log_cursor_epoch SET adopted = true WHERE id = 1")
        )
    _adopted = True
    return True


def _load_proposals(blob: Any) -> dict[tuple[str, str], CheckpointPosition]:
    """Read proposals written by ``_dump_proposals``. ``None`` is an empty set."""
    if blob is None:
        return {}
    loaded: dict[tuple[str, str], Position] = {}
    for node_id, streams in blob.items():
        for stream, raw in streams.items():
            kind = raw.get("stream_kind", "entity")
            if kind == "mirror":
                position = MirrorCheckpointPosition(
                    history_epoch=raw["history_epoch"],
                    commit_seq=int(raw["commit_seq"]),
                    entry_seq=int(raw["entry_seq"]),
                    source_ids=tuple(raw["source_ids"]),
                )
            elif kind == "entity":
                position = CheckpointPosition(
                    xact=int(raw["xact"]), seq=int(raw["seq"])
                )
            else:
                raise ValueError("Unknown checkpoint stream kind")
            loaded[(str(node_id), str(stream))] = position
    return loaded


def _dump_proposals(
    proposals: dict[tuple[str, str], Position],
) -> dict[str, dict[str, dict[str, Any]]]:
    blob: dict[str, dict[str, dict[str, Any]]] = {}
    for (node_id, stream), position in proposals.items():
        if isinstance(position, MirrorCheckpointPosition):
            raw = {
                "stream_kind": "mirror",
                "history_epoch": position.history_epoch,
                "commit_seq": position.commit_seq,
                "entry_seq": position.entry_seq,
                "source_ids": list(position.source_ids),
            }
        else:
            raw = {"xact": position.xact, "seq": position.seq}
        blob.setdefault(node_id, {})[stream] = raw
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
