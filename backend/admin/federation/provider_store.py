"""Identity Provider persistence."""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import Protocol

from backend.admin.federation.config import decrypt_config, encrypt_config
from backend.admin.federation.errors import ProviderProtocolUnsupported
from backend.admin.federation.spec import ProviderRecord
from backend.admin.models import IdentityProviderRow
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.pagination import apply_offset_page, apply_sql_page
from backend.core.time import utc_now
from sqlalchemy import func, select


class ProviderStore(Protocol):
    def list_providers(
        self, *, enabled_only: bool = False, limit: int | None = None, offset: int = 0
    ) -> tuple[list[ProviderRecord], int]: ...

    def get(self, provider_id: str) -> ProviderRecord | None: ...

    def get_by_issuer(self, issuer: str) -> ProviderRecord | None: ...

    def save(self, record: ProviderRecord) -> ProviderRecord: ...

    def delete(self, provider_id: str) -> None: ...


class MemoryProviderStore:
    def __init__(self) -> None:
        self._items: dict[str, ProviderRecord] = {}
        self._lock = threading.Lock()

    def list_providers(
        self, *, enabled_only: bool = False, limit: int | None = None, offset: int = 0
    ) -> tuple[list[ProviderRecord], int]:
        with self._lock:
            items = [
                item
                for item in self._items.values()
                if not enabled_only or item.enabled
            ]
            items.sort(key=lambda item: ((item.display_name or "").lower(), item.id))
            return apply_offset_page(items, limit=limit, offset=offset)

    def get(self, provider_id: str) -> ProviderRecord | None:
        with self._lock:
            return self._items.get(provider_id)

    def get_by_issuer(self, issuer: str) -> ProviderRecord | None:
        with self._lock:
            return next((item for item in self._items.values() if item.issuer == issuer), None)

    def save(self, record: ProviderRecord) -> ProviderRecord:
        with self._lock:
            self._items[record.id] = record
            return record

    def delete(self, provider_id: str) -> None:
        with self._lock:
            self._items.pop(provider_id, None)


class SqlProviderStore:
    def list_providers(
        self, *, enabled_only: bool = False, limit: int | None = None, offset: int = 0
    ) -> tuple[list[ProviderRecord], int]:
        with session_scope() as session:
            count_stmt = select(func.count()).select_from(IdentityProviderRow)
            stmt = select(IdentityProviderRow)
            if enabled_only:
                count_stmt = count_stmt.where(IdentityProviderRow.enabled.is_(True))
                stmt = stmt.where(IdentityProviderRow.enabled.is_(True))
            total = int(session.scalar(count_stmt) or 0)
            stmt = apply_sql_page(
                stmt.order_by(IdentityProviderRow.display_name, IdentityProviderRow.id),
                limit=limit,
                offset=offset,
            )
            return [_row_to_provider(row) for row in session.scalars(stmt).all()], total

    def get(self, provider_id: str) -> ProviderRecord | None:
        with session_scope() as session:
            return _row_to_provider(session.get(IdentityProviderRow, provider_id))

    def get_by_issuer(self, issuer: str) -> ProviderRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(IdentityProviderRow).where(IdentityProviderRow.issuer == issuer)
            )
            return _row_to_provider(row)

    def save(self, record: ProviderRecord) -> ProviderRecord:
        with session_scope() as session:
            row = session.get(IdentityProviderRow, record.id) or IdentityProviderRow(
                id=record.id,
                created_at=record.created_at or utc_now(),
            )
            row.protocol = record.protocol
            row.display_name = record.display_name
            row.issuer = record.issuer
            row.enabled = record.enabled
            row.config_ciphertext = encrypt_config(record.config)
            row.updated_at = record.updated_at or utc_now()
            session.add(row)
            session.flush()
            return _row_to_provider(row)

    def delete(self, provider_id: str) -> None:
        with session_scope() as session:
            row = session.get(IdentityProviderRow, provider_id)
            if row is not None:
                session.delete(row)


def _row_to_provider(row: IdentityProviderRow | None) -> ProviderRecord | None:
    if row is None:
        return None
    if row.protocol != "oidc":
        raise ProviderProtocolUnsupported()
    return ProviderRecord(
        id=row.id,
        protocol="oidc",
        display_name=row.display_name,
        issuer=row.issuer,
        enabled=row.enabled,
        config=decrypt_config(row.config_ciphertext),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


_memory: MemoryProviderStore | None = None
_lock = threading.Lock()


@lru_cache
def get_provider_store() -> ProviderStore:
    if get_settings().store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryProviderStore()
            return _memory
    return SqlProviderStore()


def reset_provider_store() -> None:
    global _memory
    with _lock:
        _memory = None
    get_provider_store.cache_clear()
