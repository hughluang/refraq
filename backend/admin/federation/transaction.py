"""Shared transaction boundary for federation persistence."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from backend.admin.federation.binding_store import (
    BindingStore,
    MemoryBindingStore,
    SqlBindingStore,
)
from backend.admin.federation.pending_store import (
    MemoryPendingStore,
    PendingStore,
    SqlPendingStore,
)
from backend.admin.user_store import MemoryUserStore, SqlUserStore, UserStore
from backend.core.db import session_scope


@contextmanager
def federation_transaction(
    *,
    users: UserStore,
    bindings: BindingStore,
    pending: PendingStore | None = None,
) -> Iterator[Session | None]:
    persistent = isinstance(users, SqlUserStore) and isinstance(bindings, SqlBindingStore)
    if pending is not None:
        persistent = persistent and isinstance(pending, SqlPendingStore)
    if persistent:
        with session_scope() as session:
            yield session
        return

    memory = isinstance(users, MemoryUserStore) and isinstance(
        bindings, MemoryBindingStore
    )
    if pending is not None:
        memory = memory and isinstance(pending, MemoryPendingStore)
    if not memory:
        raise RuntimeError("Federation stores must use the same persistence backend")
    yield None
