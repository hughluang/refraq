"""SCIM token and group-binding persistence (Memory and SQL adapters)."""

from __future__ import annotations

import hashlib
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Protocol

from sqlalchemy import select

from backend.admin.models import ScimGroupBindingRow, ScimTokenRow
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now

SCIM_TOKEN_PREFIX = "rfq_scim_"


def hash_scim_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate_scim_token() -> tuple[str, str, str, str]:
    """Return (id, plaintext, prefix, token_hash)."""
    token_id = f"sct_{secrets.token_hex(6)}"
    plaintext = f"{SCIM_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    prefix = plaintext[:16]
    return token_id, plaintext, prefix, hash_scim_token(plaintext)


@dataclass(frozen=True)
class ScimTokenRecord:
    id: str
    provider_id: str
    name: str
    token_hash: str
    prefix: str
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class ScimGroupBindingRecord:
    id: str
    provider_id: str
    external_id: str
    group_id: str
    created_at: datetime
    updated_at: datetime


class ScimStore(Protocol):
    def create_token(
        self, provider_id: str, name: str
    ) -> tuple[ScimTokenRecord, str]: ...

    def list_tokens(self, provider_id: str) -> list[ScimTokenRecord]: ...

    def get_token_by_hash(self, token_hash: str) -> ScimTokenRecord | None: ...

    def touch_token_last_used(self, token_id: str, when: datetime | None = None) -> None: ...

    def revoke_token(self, provider_id: str, token_id: str) -> ScimTokenRecord | None: ...

    def list_group_bindings(self, provider_id: str) -> list[ScimGroupBindingRecord]: ...

    def get_group_binding_by_external(
        self, provider_id: str, external_id: str
    ) -> ScimGroupBindingRecord | None: ...

    def get_group_binding_by_group(
        self, provider_id: str, group_id: str
    ) -> ScimGroupBindingRecord | None: ...

    def save_group_binding(
        self, record: ScimGroupBindingRecord
    ) -> ScimGroupBindingRecord: ...

    def delete_group_binding(self, provider_id: str, group_id: str) -> bool: ...


class MemoryScimStore:
    def __init__(self) -> None:
        self._tokens: dict[str, ScimTokenRecord] = {}
        self._group_bindings: dict[str, ScimGroupBindingRecord] = {}
        self._lock = threading.Lock()

    def create_token(self, provider_id: str, name: str) -> tuple[ScimTokenRecord, str]:
        token_id, plaintext, prefix, token_hash = generate_scim_token()
        record = ScimTokenRecord(
            id=token_id,
            provider_id=provider_id,
            name=name,
            token_hash=token_hash,
            prefix=prefix,
            revoked_at=None,
            last_used_at=None,
            created_at=utc_now(),
        )
        with self._lock:
            self._tokens[token_id] = record
        return record, plaintext

    def list_tokens(self, provider_id: str) -> list[ScimTokenRecord]:
        with self._lock:
            items = [
                item
                for item in self._tokens.values()
                if item.provider_id == provider_id and item.revoked_at is None
            ]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items

    def get_token_by_hash(self, token_hash: str) -> ScimTokenRecord | None:
        with self._lock:
            return next(
                (item for item in self._tokens.values() if item.token_hash == token_hash),
                None,
            )

    def touch_token_last_used(self, token_id: str, when: datetime | None = None) -> None:
        ts = when or utc_now()
        with self._lock:
            existing = self._tokens.get(token_id)
            if existing is None:
                return
            self._tokens[token_id] = ScimTokenRecord(
                id=existing.id,
                provider_id=existing.provider_id,
                name=existing.name,
                token_hash=existing.token_hash,
                prefix=existing.prefix,
                revoked_at=existing.revoked_at,
                last_used_at=ts,
                created_at=existing.created_at,
            )

    def revoke_token(self, provider_id: str, token_id: str) -> ScimTokenRecord | None:
        with self._lock:
            existing = self._tokens.get(token_id)
            if existing is None or existing.provider_id != provider_id:
                return None
            updated = ScimTokenRecord(
                id=existing.id,
                provider_id=existing.provider_id,
                name=existing.name,
                token_hash=existing.token_hash,
                prefix=existing.prefix,
                revoked_at=existing.revoked_at or utc_now(),
                last_used_at=existing.last_used_at,
                created_at=existing.created_at,
            )
            self._tokens[token_id] = updated
            return updated

    def list_group_bindings(self, provider_id: str) -> list[ScimGroupBindingRecord]:
        with self._lock:
            return [
                item
                for item in self._group_bindings.values()
                if item.provider_id == provider_id
            ]

    def get_group_binding_by_external(
        self, provider_id: str, external_id: str
    ) -> ScimGroupBindingRecord | None:
        with self._lock:
            return next(
                (
                    item
                    for item in self._group_bindings.values()
                    if item.provider_id == provider_id and item.external_id == external_id
                ),
                None,
            )

    def get_group_binding_by_group(
        self, provider_id: str, group_id: str
    ) -> ScimGroupBindingRecord | None:
        with self._lock:
            return next(
                (
                    item
                    for item in self._group_bindings.values()
                    if item.provider_id == provider_id and item.group_id == group_id
                ),
                None,
            )

    def save_group_binding(
        self, record: ScimGroupBindingRecord
    ) -> ScimGroupBindingRecord:
        with self._lock:
            self._group_bindings[record.id] = record
            return record

    def delete_group_binding(self, provider_id: str, group_id: str) -> bool:
        with self._lock:
            target = next(
                (
                    key
                    for key, item in self._group_bindings.items()
                    if item.provider_id == provider_id and item.group_id == group_id
                ),
                None,
            )
            if target is None:
                return False
            self._group_bindings.pop(target, None)
            return True


class SqlScimStore:
    def create_token(self, provider_id: str, name: str) -> tuple[ScimTokenRecord, str]:
        token_id, plaintext, prefix, token_hash = generate_scim_token()
        now = utc_now()
        with session_scope() as session:
            row = ScimTokenRow(
                id=token_id,
                provider_id=provider_id,
                name=name,
                token_hash=token_hash,
                prefix=prefix,
                revoked_at=None,
                last_used_at=None,
                created_at=now,
            )
            session.add(row)
            session.flush()
            return _row_to_token(row), plaintext

    def list_tokens(self, provider_id: str) -> list[ScimTokenRecord]:
        with session_scope() as session:
            rows = session.scalars(
                select(ScimTokenRow)
                .where(
                    ScimTokenRow.provider_id == provider_id,
                    ScimTokenRow.revoked_at.is_(None),
                )
                .order_by(ScimTokenRow.created_at.desc())
            ).all()
            return [_row_to_token(row) for row in rows]

    def get_token_by_hash(self, token_hash: str) -> ScimTokenRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(ScimTokenRow).where(ScimTokenRow.token_hash == token_hash)
            )
            return _row_to_token(row) if row is not None else None

    def touch_token_last_used(self, token_id: str, when: datetime | None = None) -> None:
        ts = when or utc_now()
        with session_scope() as session:
            row = session.get(ScimTokenRow, token_id)
            if row is not None:
                row.last_used_at = ts

    def revoke_token(self, provider_id: str, token_id: str) -> ScimTokenRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(ScimTokenRow).where(
                    ScimTokenRow.id == token_id,
                    ScimTokenRow.provider_id == provider_id,
                )
            )
            if row is None:
                return None
            if row.revoked_at is None:
                row.revoked_at = utc_now()
            session.flush()
            return _row_to_token(row)

    def list_group_bindings(self, provider_id: str) -> list[ScimGroupBindingRecord]:
        with session_scope() as session:
            rows = session.scalars(
                select(ScimGroupBindingRow).where(
                    ScimGroupBindingRow.provider_id == provider_id
                )
            ).all()
            return [_row_to_group_binding(row) for row in rows]

    def get_group_binding_by_external(
        self, provider_id: str, external_id: str
    ) -> ScimGroupBindingRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(ScimGroupBindingRow).where(
                    ScimGroupBindingRow.provider_id == provider_id,
                    ScimGroupBindingRow.external_id == external_id,
                )
            )
            return _row_to_group_binding(row) if row is not None else None

    def get_group_binding_by_group(
        self, provider_id: str, group_id: str
    ) -> ScimGroupBindingRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(ScimGroupBindingRow).where(
                    ScimGroupBindingRow.provider_id == provider_id,
                    ScimGroupBindingRow.group_id == group_id,
                )
            )
            return _row_to_group_binding(row) if row is not None else None

    def save_group_binding(
        self, record: ScimGroupBindingRecord
    ) -> ScimGroupBindingRecord:
        with session_scope() as session:
            row = session.get(ScimGroupBindingRow, record.id) or ScimGroupBindingRow(
                id=record.id,
                provider_id=record.provider_id,
                created_at=record.created_at,
            )
            row.external_id = record.external_id
            row.group_id = record.group_id
            row.updated_at = record.updated_at
            session.add(row)
            session.flush()
            return _row_to_group_binding(row)

    def delete_group_binding(self, provider_id: str, group_id: str) -> bool:
        with session_scope() as session:
            row = session.scalar(
                select(ScimGroupBindingRow).where(
                    ScimGroupBindingRow.provider_id == provider_id,
                    ScimGroupBindingRow.group_id == group_id,
                )
            )
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True


def _row_to_token(row: ScimTokenRow) -> ScimTokenRecord:
    return ScimTokenRecord(
        id=row.id,
        provider_id=row.provider_id,
        name=row.name,
        token_hash=row.token_hash,
        prefix=row.prefix,
        revoked_at=row.revoked_at,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
    )


def _row_to_group_binding(row: ScimGroupBindingRow) -> ScimGroupBindingRecord:
    return ScimGroupBindingRecord(
        id=row.id,
        provider_id=row.provider_id,
        external_id=row.external_id,
        group_id=row.group_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


_memory: MemoryScimStore | None = None
_lock = threading.Lock()


@lru_cache
def get_scim_store() -> ScimStore:
    if get_settings().store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryScimStore()
            return _memory
    return SqlScimStore()


def reset_scim_store() -> None:
    global _memory
    with _lock:
        _memory = None
    get_scim_store.cache_clear()
