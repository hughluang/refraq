"""Request-scoped PAT id for Entity Access Log writers.

The Entity Data API router sets it from the authenticated request. The Entity
MCP gate sets it around a tool call. Unset means a session or a caller with no
PAT, and the log stores null.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_pat_id: ContextVar[str | None] = ContextVar("entity_access_pat_id", default=None)


def current_actor_token_id() -> str | None:
    return _pat_id.get()


@contextmanager
def actor_token(pat_id: str | None) -> Iterator[None]:
    """Bind ``pat_id`` for writers on this context, then restore the previous value."""
    token = _pat_id.set(pat_id)
    try:
        yield
    finally:
        _pat_id.reset(token)
