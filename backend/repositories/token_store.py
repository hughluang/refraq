"""User PAT repository ports and adapters."""

from __future__ import annotations

import hashlib
import secrets
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Protocol

from backend.core.config import get_settings

TOKEN_PREFIX = "rfq_pat_"
_PREFIX_VISIBLE_LEN = 12  # rfq_pat_ + 4 chars of secret for list display


@dataclass
class TokenRecord:
    id: str
    user_id: str
    name: str
    token_hash: str
    prefix: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    last_used_at: datetime | None


def hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_token_secret() -> tuple[str, str, str]:
    """Return (full_secret, prefix, token_hash)."""
    suffix = secrets.token_urlsafe(32)
    secret = f"{TOKEN_PREFIX}{suffix}"
    prefix = secret[:_PREFIX_VISIBLE_LEN]
    return secret, prefix, hash_token(secret)


class TokenStore(Protocol):
    def list_for_user(self, user_id: str) -> list[TokenRecord]: ...

    def get_by_id(self, token_id: str) -> TokenRecord | None: ...

    def get_by_hash(self, token_hash: str) -> TokenRecord | None: ...

    def create(
        self,
        *,
        user_id: str,
        name: str,
        token_hash: str,
        prefix: str,
        expires_at: datetime,
    ) -> TokenRecord: ...

    def revoke(self, token_id: str, *, when: datetime) -> TokenRecord | None: ...

    def touch_last_used(self, token_id: str, when: datetime) -> None: ...


class MemoryTokenStore:
    def __init__(self) -> None:
        self._by_id: dict[str, TokenRecord] = {}
        self._by_hash: dict[str, str] = {}
        self._lock = threading.Lock()

    def list_for_user(self, user_id: str) -> list[TokenRecord]:
        with self._lock:
            items = [r for r in self._by_id.values() if r.user_id == user_id]
            return sorted(items, key=lambda r: (r.created_at, r.id), reverse=True)

    def get_by_id(self, token_id: str) -> TokenRecord | None:
        with self._lock:
            return self._by_id.get(token_id)

    def get_by_hash(self, token_hash: str) -> TokenRecord | None:
        with self._lock:
            token_id = self._by_hash.get(token_hash)
            if token_id is None:
                return None
            return self._by_id.get(token_id)

    def create(
        self,
        *,
        user_id: str,
        name: str,
        token_hash: str,
        prefix: str,
        expires_at: datetime,
    ) -> TokenRecord:
        with self._lock:
            token_id = f"pat_{uuid.uuid4().hex[:12]}"
            record = TokenRecord(
                id=token_id,
                user_id=user_id,
                name=name,
                token_hash=token_hash,
                prefix=prefix,
                expires_at=expires_at,
                revoked_at=None,
                created_at=datetime.utcnow(),
                last_used_at=None,
            )
            self._by_id[token_id] = record
            self._by_hash[token_hash] = token_id
            return record

    def revoke(self, token_id: str, *, when: datetime) -> TokenRecord | None:
        with self._lock:
            record = self._by_id.get(token_id)
            if record is None:
                return None
            if record.revoked_at is None:
                record.revoked_at = when
            return record

    def touch_last_used(self, token_id: str, when: datetime) -> None:
        with self._lock:
            record = self._by_id.get(token_id)
            if record is not None:
                record.last_used_at = when


class SqlTokenStore:
    def list_for_user(self, user_id: str) -> list[TokenRecord]:
        from sqlalchemy import select

        from backend.admin.models import UserPatRow
        from backend.core.db import session_scope

        with session_scope() as session:
            rows = session.scalars(
                select(UserPatRow)
                .where(UserPatRow.user_id == user_id)
                .order_by(UserPatRow.created_at.desc(), UserPatRow.id.desc())
            ).all()
            return [_row_to_token(row) for row in rows]

    def get_by_id(self, token_id: str) -> TokenRecord | None:
        from backend.admin.models import UserPatRow
        from backend.core.db import session_scope

        with session_scope() as session:
            row = session.get(UserPatRow, token_id)
            return _row_to_token(row) if row else None

    def get_by_hash(self, token_hash: str) -> TokenRecord | None:
        from sqlalchemy import select

        from backend.admin.models import UserPatRow
        from backend.core.db import session_scope

        with session_scope() as session:
            row = session.scalar(
                select(UserPatRow).where(UserPatRow.token_hash == token_hash)
            )
            return _row_to_token(row) if row else None

    def create(
        self,
        *,
        user_id: str,
        name: str,
        token_hash: str,
        prefix: str,
        expires_at: datetime,
    ) -> TokenRecord:
        from backend.admin.models import UserPatRow
        from backend.core.db import session_scope

        token_id = f"pat_{uuid.uuid4().hex[:12]}"
        created_at = datetime.utcnow()
        with session_scope() as session:
            row = UserPatRow(
                id=token_id,
                user_id=user_id,
                name=name,
                token_hash=token_hash,
                prefix=prefix,
                expires_at=expires_at,
                revoked_at=None,
                created_at=created_at,
                last_used_at=None,
            )
            session.add(row)
            session.flush()
            return _row_to_token(row)

    def revoke(self, token_id: str, *, when: datetime) -> TokenRecord | None:
        from backend.admin.models import UserPatRow
        from backend.core.db import session_scope

        with session_scope() as session:
            row = session.get(UserPatRow, token_id)
            if row is None:
                return None
            if row.revoked_at is None:
                row.revoked_at = when
            session.flush()
            return _row_to_token(row)

    def touch_last_used(self, token_id: str, when: datetime) -> None:
        from backend.admin.models import UserPatRow
        from backend.core.db import session_scope

        with session_scope() as session:
            row = session.get(UserPatRow, token_id)
            if row is not None:
                row.last_used_at = when


def _row_to_token(row: object) -> TokenRecord:
    from backend.admin.models import UserPatRow

    assert isinstance(row, UserPatRow)
    return TokenRecord(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        token_hash=row.token_hash,
        prefix=row.prefix,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
    )


_memory_singleton: MemoryTokenStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_token_store() -> TokenStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryTokenStore()
            return _memory_singleton
    return SqlTokenStore()


def reset_token_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_token_store.cache_clear()
