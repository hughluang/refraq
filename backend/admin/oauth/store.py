"""OAuth Client persistence (Memory and SQL adapters)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol

from sqlalchemy import func, select

from backend.admin.models import OAuthClientRow
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now


@dataclass(frozen=True)
class OAuthClientRecord:
    id: str
    client_id: str
    name: str
    description: str | None
    provider_id: str
    enabled: bool
    token_endpoint_auth_method: str
    jwks: dict[str, Any] | None
    jwks_uri: str | None
    secret_hash: str | None
    secret_prefix: str | None
    allowed_grant_types: tuple[str, ...]
    allowed_subject_audiences: tuple[str, ...]
    allowed_surfaces: tuple[str, ...]
    allowed_scopes: tuple[str, ...]
    token_ttl_sec: int | None
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None


class OAuthClientStore(Protocol):
    def list_page(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        q: str | None = None,
        provider_id: str | None = None,
        enabled: bool | None = None,
    ) -> tuple[list[OAuthClientRecord], int]: ...

    def get_by_id(self, record_id: str) -> OAuthClientRecord | None: ...

    def get_by_client_id(self, client_id: str) -> OAuthClientRecord | None: ...

    def save(self, record: OAuthClientRecord) -> OAuthClientRecord: ...

    def touch_last_used(self, record_id: str, when: datetime | None = None) -> None: ...

    def delete(self, record_id: str) -> bool: ...


class MemoryOAuthClientStore:
    def __init__(self) -> None:
        self._items: dict[str, OAuthClientRecord] = {}
        self._lock = threading.Lock()

    def list_page(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        q: str | None = None,
        provider_id: str | None = None,
        enabled: bool | None = None,
    ) -> tuple[list[OAuthClientRecord], int]:
        needle = (q or "").strip().lower()
        with self._lock:
            items = list(self._items.values())
        if provider_id is not None:
            items = [item for item in items if item.provider_id == provider_id]
        if enabled is not None:
            items = [item for item in items if item.enabled is enabled]
        if needle:
            items = [
                item
                for item in items
                if needle in item.name.lower() or needle in item.client_id.lower()
            ]
        items.sort(key=lambda item: item.created_at, reverse=True)
        total = len(items)
        return items[offset : offset + limit], total

    def get_by_id(self, record_id: str) -> OAuthClientRecord | None:
        with self._lock:
            return self._items.get(record_id)

    def get_by_client_id(self, client_id: str) -> OAuthClientRecord | None:
        with self._lock:
            return next(
                (item for item in self._items.values() if item.client_id == client_id),
                None,
            )

    def save(self, record: OAuthClientRecord) -> OAuthClientRecord:
        with self._lock:
            self._items[record.id] = record
            return record

    def touch_last_used(self, record_id: str, when: datetime | None = None) -> None:
        ts = when or utc_now()
        with self._lock:
            existing = self._items.get(record_id)
            if existing is None:
                return
            self._items[record_id] = OAuthClientRecord(
                id=existing.id,
                client_id=existing.client_id,
                name=existing.name,
                description=existing.description,
                provider_id=existing.provider_id,
                enabled=existing.enabled,
                token_endpoint_auth_method=existing.token_endpoint_auth_method,
                jwks=existing.jwks,
                jwks_uri=existing.jwks_uri,
                secret_hash=existing.secret_hash,
                secret_prefix=existing.secret_prefix,
                allowed_grant_types=existing.allowed_grant_types,
                allowed_subject_audiences=existing.allowed_subject_audiences,
                allowed_surfaces=existing.allowed_surfaces,
                allowed_scopes=existing.allowed_scopes,
                token_ttl_sec=existing.token_ttl_sec,
                created_at=existing.created_at,
                updated_at=existing.updated_at,
                last_used_at=ts,
            )

    def delete(self, record_id: str) -> bool:
        with self._lock:
            return self._items.pop(record_id, None) is not None


class SqlOAuthClientStore:
    def list_page(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        q: str | None = None,
        provider_id: str | None = None,
        enabled: bool | None = None,
    ) -> tuple[list[OAuthClientRecord], int]:
        stmt = select(OAuthClientRow)
        count_stmt = select(func.count(OAuthClientRow.id))
        if provider_id is not None:
            stmt = stmt.where(OAuthClientRow.provider_id == provider_id)
            count_stmt = count_stmt.where(OAuthClientRow.provider_id == provider_id)
        if enabled is not None:
            stmt = stmt.where(OAuthClientRow.enabled == enabled)
            count_stmt = count_stmt.where(OAuthClientRow.enabled == enabled)
        needle = (q or "").strip()
        if needle:
            pattern = f"%{needle}%"
            clause = OAuthClientRow.name.ilike(pattern) | OAuthClientRow.client_id.ilike(pattern)
            stmt = stmt.where(clause)
            count_stmt = count_stmt.where(clause)
        with session_scope() as session:
            total = int(session.scalar(count_stmt) or 0)
            rows = session.scalars(
                stmt.order_by(OAuthClientRow.created_at.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            return [_row_to_record(row) for row in rows], total

    def get_by_id(self, record_id: str) -> OAuthClientRecord | None:
        with session_scope() as session:
            row = session.get(OAuthClientRow, record_id)
            return _row_to_record(row) if row is not None else None

    def get_by_client_id(self, client_id: str) -> OAuthClientRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(OAuthClientRow).where(OAuthClientRow.client_id == client_id)
            )
            return _row_to_record(row) if row is not None else None

    def save(self, record: OAuthClientRecord) -> OAuthClientRecord:
        with session_scope() as session:
            row = session.get(OAuthClientRow, record.id) or OAuthClientRow(
                id=record.id,
                client_id=record.client_id,
                created_at=record.created_at,
            )
            row.name = record.name
            row.description = record.description
            row.provider_id = record.provider_id
            row.enabled = record.enabled
            row.token_endpoint_auth_method = record.token_endpoint_auth_method
            row.jwks = record.jwks
            row.jwks_uri = record.jwks_uri
            row.secret_hash = record.secret_hash
            row.secret_prefix = record.secret_prefix
            row.allowed_grant_types = list(record.allowed_grant_types)
            row.allowed_subject_audiences = list(record.allowed_subject_audiences)
            row.allowed_surfaces = list(record.allowed_surfaces)
            row.allowed_scopes = list(record.allowed_scopes)
            row.token_ttl_sec = record.token_ttl_sec
            row.updated_at = record.updated_at
            row.last_used_at = record.last_used_at
            session.add(row)
            session.flush()
            return _row_to_record(row)

    def touch_last_used(self, record_id: str, when: datetime | None = None) -> None:
        ts = when or utc_now()
        with session_scope() as session:
            row = session.get(OAuthClientRow, record_id)
            if row is not None:
                row.last_used_at = ts

    def delete(self, record_id: str) -> bool:
        with session_scope() as session:
            row = session.get(OAuthClientRow, record_id)
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True


def _row_to_record(row: OAuthClientRow) -> OAuthClientRecord:
    return OAuthClientRecord(
        id=row.id,
        client_id=row.client_id,
        name=row.name,
        description=row.description,
        provider_id=row.provider_id,
        enabled=bool(row.enabled),
        token_endpoint_auth_method=row.token_endpoint_auth_method,
        jwks=dict(row.jwks) if isinstance(row.jwks, dict) else None,
        jwks_uri=row.jwks_uri,
        secret_hash=row.secret_hash,
        secret_prefix=row.secret_prefix,
        allowed_grant_types=tuple(str(item) for item in (row.allowed_grant_types or ())),
        allowed_subject_audiences=tuple(
            str(item) for item in (row.allowed_subject_audiences or ())
        ),
        allowed_surfaces=tuple(str(item) for item in (row.allowed_surfaces or ())),
        allowed_scopes=tuple(str(item) for item in (row.allowed_scopes or ())),
        token_ttl_sec=row.token_ttl_sec,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_used_at=row.last_used_at,
    )


_memory: MemoryOAuthClientStore | None = None
_lock = threading.Lock()


@lru_cache
def get_oauth_client_store() -> OAuthClientStore:
    if get_settings().store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryOAuthClientStore()
            return _memory
    return SqlOAuthClientStore()


def reset_oauth_client_store() -> None:
    global _memory
    with _lock:
        _memory = None
    get_oauth_client_store.cache_clear()
