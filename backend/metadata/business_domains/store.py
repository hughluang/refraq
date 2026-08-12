"""Business Domain store ports/adapters."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from functools import lru_cache
from typing import Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.metadata.errors import BusinessDomainCodeConflict, BusinessDomainNotFound
from backend.metadata.models import BusinessDomainRow, CatalogObjectRow


__all__ = [
    "BusinessDomainRecord",
    "BusinessDomainStore",
    "MemoryBusinessDomainStore",
    "SqlBusinessDomainStore",
    "get_business_domain_store",
    "new_business_domain_id",
    "reset_business_domain_store",
]

@dataclass
class BusinessDomainRecord:
    id: str
    code: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

def new_business_domain_id() -> str:
    return f"bd_{uuid.uuid4().hex[:12]}"

class BusinessDomainStore(Protocol):
    def list_domains(
        self, *, q: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[BusinessDomainRecord], int]: ...

    def get(self, domain_id: str) -> BusinessDomainRecord | None: ...
    def get_by_code(self, code: str) -> BusinessDomainRecord | None: ...

    def create(self, record: BusinessDomainRecord) -> BusinessDomainRecord: ...
    def save(self, record: BusinessDomainRecord) -> BusinessDomainRecord: ...

    def delete(self, domain_id: str) -> bool: ...
    def count_object_refs(self, domain_id: str) -> int: ...

class MemoryBusinessDomainStore:
    def __init__(self) -> None:
        self._domains: dict[str, BusinessDomainRecord] = {}
        self._by_code: dict[str, str] = {}
        self._object_refs: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    def list_domains(
        self, *, q: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[BusinessDomainRecord], int]:
        with self._lock:
            items = list(self._domains.values())
        if q:
            needle = q.lower().strip()
            items = [
                d
                for d in items
                if needle in d.code.lower()
                or needle in d.name.lower()
                or (d.description and needle in d.description.lower())
            ]
        items.sort(key=lambda d: (d.code.lower(), d.id))
        total = len(items)
        return items[offset : offset + limit], total

    def get(self, domain_id: str) -> BusinessDomainRecord | None:
        with self._lock:
            return self._domains.get(domain_id)

    def get_by_code(self, code: str) -> BusinessDomainRecord | None:
        with self._lock:
            domain_id = self._by_code.get(code)
            return self._domains.get(domain_id) if domain_id else None

    def create(self, record: BusinessDomainRecord) -> BusinessDomainRecord:
        with self._lock:
            if record.code in self._by_code:
                raise BusinessDomainCodeConflict()
            self._domains[record.id] = record
            self._by_code[record.code] = record.id
            return record

    def save(self, record: BusinessDomainRecord) -> BusinessDomainRecord:
        with self._lock:
            existing = self._domains.get(record.id)
            if existing is None:
                raise BusinessDomainNotFound()
            if existing.code != record.code:
                raise BusinessDomainCodeConflict()
            self._domains[record.id] = record
            return record

    def delete(self, domain_id: str) -> bool:
        with self._lock:
            existing = self._domains.pop(domain_id, None)
            if existing is None:
                return False
            if self._by_code.get(existing.code) == domain_id:
                del self._by_code[existing.code]
            self._object_refs.pop(domain_id, None)
            return True

    def count_object_refs(self, domain_id: str) -> int:
        with self._lock:
            return len(self._object_refs.get(domain_id, set()))

    def set_object_ref(self, object_id: str, domain_id: str | None) -> None:
        """Memory-only helper so catalog store can track RESTRICT refs."""
        with self._lock:
            for refs in self._object_refs.values():
                refs.discard(object_id)
            if domain_id is None:
                return
            self._object_refs.setdefault(domain_id, set()).add(object_id)

class SqlBusinessDomainStore:
    def list_domains(
        self, *, q: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[BusinessDomainRecord], int]:

        with session_scope() as session:
            stmt = select(BusinessDomainRow)
            count_stmt = select(func.count()).select_from(BusinessDomainRow)
            if q and q.strip():
                needle = f"%{q.strip()}%"
                filt = or_(
                    BusinessDomainRow.code.ilike(needle),
                    BusinessDomainRow.name.ilike(needle),
                    BusinessDomainRow.description.ilike(needle),
                )
                stmt = stmt.where(filt)
                count_stmt = count_stmt.where(filt)
            total = int(session.execute(count_stmt).scalar_one())
            rows = (
                session.execute(
                    stmt.order_by(BusinessDomainRow.code, BusinessDomainRow.id)
                    .offset(offset)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [_row_to_record(r) for r in rows], total

    def get(self, domain_id: str) -> BusinessDomainRecord | None:
        with session_scope() as session:
            row = session.get(BusinessDomainRow, domain_id)
            return _row_to_record(row) if row else None

    def get_by_code(self, code: str) -> BusinessDomainRecord | None:
        with session_scope() as session:
            row = session.execute(
                select(BusinessDomainRow).where(BusinessDomainRow.code == code)
            ).scalar_one_or_none()
            return _row_to_record(row) if row else None

    def create(self, record: BusinessDomainRecord) -> BusinessDomainRecord:
        with session_scope() as session:
            session.add(
                BusinessDomainRow(
                    id=record.id,
                    code=record.code,
                    name=record.name,
                    description=record.description,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )
            try:
                session.flush()
            except IntegrityError as exc:
                raise BusinessDomainCodeConflict() from exc
            return record

    def save(self, record: BusinessDomainRecord) -> BusinessDomainRecord:
        with session_scope() as session:
            row = session.get(BusinessDomainRow, record.id)
            if row is None:
                raise BusinessDomainNotFound()
            if row.code != record.code:
                raise BusinessDomainCodeConflict()
            row.name = record.name
            row.description = record.description
            row.updated_at = record.updated_at
            session.flush()
            return _row_to_record(row)

    def delete(self, domain_id: str) -> bool:
        with session_scope() as session:
            row = session.get(BusinessDomainRow, domain_id)
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True

    def count_object_refs(self, domain_id: str) -> int:
        with session_scope() as session:
            return int(
                session.execute(
                    select(func.count())
                    .select_from(CatalogObjectRow)
                    .where(CatalogObjectRow.business_domain_id == domain_id)
                ).scalar_one()
            )

def _row_to_record(row: object) -> BusinessDomainRecord:
    assert isinstance(row, BusinessDomainRow)
    return BusinessDomainRecord(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )

_memory_singleton: MemoryBusinessDomainStore | None = None
_memory_lock = threading.Lock()

@lru_cache
def get_business_domain_store() -> MemoryBusinessDomainStore | SqlBusinessDomainStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryBusinessDomainStore()
            return _memory_singleton
    return SqlBusinessDomainStore()

def reset_business_domain_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_business_domain_store.cache_clear()
