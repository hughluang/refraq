"""Checkpointed Change Log range for Read Changes and Changes Dataset.

Recording, purge-mark validity, start, bound, and proposal live here.
Open and read do not propose. The caller proposes after it succeeds.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.channel.checkpoints import CheckpointPosition
from backend.entity.changes import (
    ChangeLogOff,
    ChangePosition,
    purge_mark,
    recording_enabled,
)
from backend.entity.history.service import (
    IncrementalPage,
    IncrementalPosition,
    read_incremental,
)
from backend.entity.errors import EntityNotFound

if TYPE_CHECKING:
    from backend.channel.nodes.spec import CheckpointView

__all__ = [
    "ChangeRange",
    "ChangeRangeError",
    "open_change_range",
    "propose_change_range",
    "read_change_range",
]

_OFF = "Change recording is off for this entity."
_INVALID = "Checkpoint is behind deleted change-log entries."
_UNRESOLVED = "Entity does not resolve"


class ChangeRangeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ChangeRange:
    """Start and bound for one node's Change Log stream."""

    node_id: str
    entity_id: str
    after: ChangePosition | None
    bound: int


@contextmanager
def _range_errors() -> Iterator[None]:
    """Known failures become ``ChangeRangeError``. Other exceptions propagate."""
    try:
        yield
    except ChangeLogOff:
        raise ChangeRangeError("CHANNEL_CHANGE_LOG_OFF", _OFF) from None
    except EntityNotFound:
        raise ChangeRangeError("CHANNEL_NODE_FAILED", _UNRESOLVED) from None


def open_change_range(
    entity_id: str,
    node_id: str,
    session: CheckpointView,
    *,
    ignore_checkpoints: bool,
) -> ChangeRange:
    """Recording check, purge-mark validity, start, and bound.

    Does not propose and does not read entries.
    """
    with _range_errors():
        if not recording_enabled(entity_id):
            raise ChangeRangeError("CHANNEL_CHANGE_LOG_OFF", _OFF)
        if not ignore_checkpoints:
            durable = session.durable(node_id, entity_id)
            mark = purge_mark(entity_id)
            if (
                durable is not None
                and mark is not None
                and (durable.xact, durable.seq) < (mark.xact, mark.seq)
            ):
                raise ChangeRangeError("CHANNEL_CHECKPOINT_INVALID", _INVALID)
        after = (
            session.proposed(node_id, entity_id)
            if ignore_checkpoints
            else session.stored(node_id, entity_id)
        )
        bound = session.bound(node_id, entity_id)
        return ChangeRange(
            node_id=node_id,
            entity_id=entity_id,
            after=_change_position(after),
            bound=bound,
        )


def read_change_range(
    opened: ChangeRange,
    *,
    limit: int,
    after: IncrementalPosition | None = None,
) -> IncrementalPage:
    """One projected page through ``read_incremental``. Does not propose.

    The operation loads the platform System Identity. This function does not
    take a user. ``after`` none resumes at the opened start, including the
    beginning of the stream. A later page passes the previous page's progress.
    """
    cursor = after
    if cursor is None and opened.after is not None:
        cursor = IncrementalPosition(
            commit_seq=opened.after.xact, seq=opened.after.seq
        )
    with _range_errors():
        return read_incremental(
            opened.entity_id,
            after=cursor,
            bound=opened.bound,
            limit=limit,
        )


def propose_change_range(
    session: CheckpointView,
    opened: ChangeRange,
    progress: IncrementalPosition | None,
) -> None:
    """Propose the operation's evaluated position. An empty scan proposes nothing.

    Call only after the caller has succeeded. The position is ``progress``,
    not the last row the caller wrote.
    """
    if progress is None:
        return
    session.propose(
        opened.node_id,
        opened.entity_id,
        CheckpointPosition(xact=progress.commit_seq, seq=progress.seq),
    )


def _change_position(position: CheckpointPosition | None) -> ChangePosition | None:
    if position is None:
        return None
    return ChangePosition(xact=position.xact, seq=position.seq)
