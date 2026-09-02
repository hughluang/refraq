"""Model Service persistence."""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import Protocol

from sqlalchemy import func, select

from backend.admin.models import ModelServicePurposeRow, ModelServiceRow
from backend.admin.model_services.records import ModelServiceRecord, PurposeState
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.pagination import apply_offset_page, apply_sql_page
from backend.core.secrets import decrypt_secret, encrypt_secret


class ModelServiceStore(Protocol):
    def list_services(
        self, *, purpose: str | None = None, limit: int | None = None, offset: int = 0
    ) -> tuple[list[ModelServiceRecord], int]: ...

    def get(self, service_id: str) -> ModelServiceRecord | None: ...

    def save(self, record: ModelServiceRecord) -> ModelServiceRecord: ...

    def delete(self, service_id: str) -> None: ...

    def get_purpose(self, purpose: str) -> PurposeState: ...

    def save_purpose(self, state: PurposeState) -> PurposeState: ...


def _encrypt(secret: str | None) -> str | None:
    if secret is None or secret == "":
        return None
    return encrypt_secret(secret)


def _decrypt(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    return decrypt_secret(ciphertext)


def _default_purpose(purpose: str) -> PurposeState:
    return PurposeState(
        purpose=purpose,
        in_use_id=None,
        closed=False,
        ready=False,
        generation=0,
    )


class MemoryModelServiceStore:
    def __init__(self) -> None:
        self._items: dict[str, ModelServiceRecord] = {}
        self._purposes: dict[str, PurposeState] = {}
        self._lock = threading.Lock()

    def list_services(
        self, *, purpose: str | None = None, limit: int | None = None, offset: int = 0
    ) -> tuple[list[ModelServiceRecord], int]:
        with self._lock:
            items = list(self._items.values())
            if purpose is not None:
                items = [item for item in items if item.purpose == purpose]
            items.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
            return apply_offset_page(items, limit=limit, offset=offset)

    def get(self, service_id: str) -> ModelServiceRecord | None:
        with self._lock:
            return self._items.get(service_id)

    def save(self, record: ModelServiceRecord) -> ModelServiceRecord:
        with self._lock:
            self._items[record.id] = record
            return record

    def delete(self, service_id: str) -> None:
        with self._lock:
            self._items.pop(service_id, None)
            for purpose, state in list(self._purposes.items()):
                if state.in_use_id == service_id:
                    self._purposes[purpose] = PurposeState(
                        purpose=state.purpose,
                        in_use_id=None,
                        closed=state.closed,
                        ready=state.ready,
                        generation=state.generation,
                    )

    def get_purpose(self, purpose: str) -> PurposeState:
        with self._lock:
            return self._purposes.get(purpose) or _default_purpose(purpose)

    def save_purpose(self, state: PurposeState) -> PurposeState:
        with self._lock:
            self._purposes[state.purpose] = state
            return state


class SqlModelServiceStore:
    def list_services(
        self, *, purpose: str | None = None, limit: int | None = None, offset: int = 0
    ) -> tuple[list[ModelServiceRecord], int]:
        with session_scope() as session:
            count_stmt = select(func.count()).select_from(ModelServiceRow)
            stmt = select(ModelServiceRow)
            if purpose is not None:
                count_stmt = count_stmt.where(ModelServiceRow.purpose == purpose)
                stmt = stmt.where(ModelServiceRow.purpose == purpose)
            total = int(session.scalar(count_stmt) or 0)
            stmt = stmt.order_by(
                ModelServiceRow.updated_at.desc(), ModelServiceRow.id.desc()
            )
            stmt = apply_sql_page(stmt, limit=limit, offset=offset)
            rows = list(session.scalars(stmt).all())
            return [_row_to_record(row) for row in rows], total

    def get(self, service_id: str) -> ModelServiceRecord | None:
        with session_scope() as session:
            row = session.get(ModelServiceRow, service_id)
            return _row_to_record(row) if row is not None else None

    def save(self, record: ModelServiceRecord) -> ModelServiceRecord:
        with session_scope() as session:
            row = session.get(ModelServiceRow, record.id)
            if row is None:
                session.add(
                    ModelServiceRow(
                        id=record.id,
                        purpose=record.purpose,
                        protocol=record.protocol,
                        display_name=record.display_name,
                        url=record.url,
                        model=record.model,
                        secret_ciphertext=_encrypt(record.secret),
                        created_at=record.created_at,
                        updated_at=record.updated_at,
                    )
                )
            else:
                row.purpose = record.purpose
                row.protocol = record.protocol
                row.display_name = record.display_name
                row.url = record.url
                row.model = record.model
                row.secret_ciphertext = _encrypt(record.secret)
                row.updated_at = record.updated_at
            session.flush()
            return record

    def delete(self, service_id: str) -> None:
        with session_scope() as session:
            row = session.get(ModelServiceRow, service_id)
            if row is not None:
                session.delete(row)
            for purpose_row in session.scalars(select(ModelServicePurposeRow)).all():
                if purpose_row.in_use_id == service_id:
                    purpose_row.in_use_id = None
            session.flush()

    def get_purpose(self, purpose: str) -> PurposeState:
        with session_scope() as session:
            row = session.get(ModelServicePurposeRow, purpose)
            if row is None:
                return _default_purpose(purpose)
            return PurposeState(
                purpose=row.purpose,
                in_use_id=row.in_use_id,
                closed=row.closed,
                ready=row.ready,
                generation=row.generation,
            )

    def save_purpose(self, state: PurposeState) -> PurposeState:
        with session_scope() as session:
            row = session.get(ModelServicePurposeRow, state.purpose)
            if row is None:
                session.add(
                    ModelServicePurposeRow(
                        purpose=state.purpose,
                        in_use_id=state.in_use_id,
                        closed=state.closed,
                        ready=state.ready,
                        generation=state.generation,
                    )
                )
            else:
                row.in_use_id = state.in_use_id
                row.closed = state.closed
                row.ready = state.ready
                row.generation = state.generation
            session.flush()
            return state


def _row_to_record(row: ModelServiceRow) -> ModelServiceRecord:
    return ModelServiceRecord(
        id=row.id,
        purpose=row.purpose,
        protocol=row.protocol,
        display_name=row.display_name,
        url=row.url,
        model=row.model,
        secret=_decrypt(row.secret_ciphertext),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


_memory: MemoryModelServiceStore | None = None
_lock = threading.Lock()


@lru_cache
def get_model_service_store() -> ModelServiceStore:
    if get_settings().store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryModelServiceStore()
            return _memory
    return SqlModelServiceStore()


def reset_model_service_store() -> None:
    global _memory
    with _lock:
        _memory = None
    get_model_service_store.cache_clear()
