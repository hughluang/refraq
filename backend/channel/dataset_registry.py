"""Platform registry of run-scoped dataset tables.

``channel_datasets.job_id`` is a plain column, not a foreign key to
``channel_runs.job_id``. The physical table lives in the entity database, so
deleting a run record cannot drop it. ``ON DELETE CASCADE`` would remove the
only stored relation name before a later purge could drop the table. This unit
leaves ``expires_at`` null; sealing and purge are later.
"""

from __future__ import annotations

import copy
import threading
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from backend.channel.models import ChannelDatasetRow
from backend.channel.parameters import channel_dataset_max_total_gb
from backend.core.db import session_scope
from backend.core.time import utc_now
from backend.entity.datasets import (
    any_row_exists,
    column_types,
    copy_chunks,
    create_table_from_query,
    drop_relation,
    normalized_type_of,
    physical_relation,
    postgres_type,
    read_keyset_page,
)

__all__ = [
    "DatasetColumnSpec",
    "DatasetQuotaExceeded",
    "DatasetRecord",
    "DatasetRegistry",
    "MemoryDatasetStore",
    "SqlDatasetStore",
]

_CAPACITY_STATUSES = frozenset({"loading", "ready"})
# pg_total_relation_size is bytes. One gigabyte of the capacity parameter is 2**30 bytes.
_BYTES_PER_GB = 1024**3


@dataclass
class DatasetRecord:
    id: str
    job_id: str
    node_id: str
    seq: int
    relation: str
    columns: list[dict[str, Any]]
    row_count: int
    size_bytes: int
    status: str
    created_at: datetime
    expires_at: datetime | None = None


@dataclass(frozen=True)
class DatasetColumnSpec:
    """One loaded column. ``type`` on the registry row is the PostgreSQL type used."""

    name: str
    normalized_type: str
    precision: int | None = None
    scale: int | None = None
    with_time_zone: bool = False


class DatasetQuotaExceeded(Exception):
    """Loading and ready datasets are already at the capacity ceiling."""

    code = "CHANNEL_DATASET_QUOTA_EXCEEDED"

    def __init__(self) -> None:
        super().__init__(self.code)


class MemoryDatasetStore:
    """In-memory registry rows. Copies on save and read."""

    def __init__(self) -> None:
        self._rows: dict[str, DatasetRecord] = {}
        self._lock = threading.Lock()

    def save(self, record: DatasetRecord) -> None:
        with self._lock:
            self._rows[record.id] = copy.deepcopy(record)

    def get(self, dataset_id: str) -> DatasetRecord | None:
        with self._lock:
            record = self._rows.get(dataset_id)
            return None if record is None else copy.deepcopy(record)

    def used_bytes(self) -> int:
        with self._lock:
            return sum(
                row.size_bytes for row in self._rows.values() if row.status in _CAPACITY_STATUSES
            )


class SqlDatasetStore:
    """Platform-database registry rows."""

    def save(self, record: DatasetRecord) -> None:
        with session_scope() as session:
            row = session.get(ChannelDatasetRow, record.id)
            if row is None:
                session.add(_to_row(record))
                return
            _apply(row, record)

    def get(self, dataset_id: str) -> DatasetRecord | None:
        with session_scope() as session:
            row = session.get(ChannelDatasetRow, dataset_id)
            return None if row is None else _from_row(row)

    def used_bytes(self) -> int:
        with session_scope() as session:
            value = session.scalar(
                select(func.coalesce(func.sum(ChannelDatasetRow.size_bytes), 0)).where(
                    ChannelDatasetRow.status.in_(tuple(_CAPACITY_STATUSES))
                )
            )
            return int(value)


def _to_row(record: DatasetRecord) -> ChannelDatasetRow:
    return ChannelDatasetRow(
        id=record.id,
        job_id=record.job_id,
        node_id=record.node_id,
        seq=record.seq,
        relation=record.relation,
        columns=copy.deepcopy(record.columns),
        row_count=record.row_count,
        size_bytes=record.size_bytes,
        status=record.status,
        created_at=record.created_at,
        expires_at=record.expires_at,
    )


def _apply(row: ChannelDatasetRow, record: DatasetRecord) -> None:
    row.job_id = record.job_id
    row.node_id = record.node_id
    row.seq = record.seq
    row.relation = record.relation
    row.columns = copy.deepcopy(record.columns)
    row.row_count = record.row_count
    row.size_bytes = record.size_bytes
    row.status = record.status
    row.created_at = record.created_at
    row.expires_at = record.expires_at


def _from_row(row: ChannelDatasetRow) -> DatasetRecord:
    return DatasetRecord(
        id=row.id,
        job_id=row.job_id,
        node_id=row.node_id,
        seq=row.seq,
        relation=row.relation,
        columns=[dict(column) for column in row.columns],
        row_count=int(row.row_count),
        size_bytes=int(row.size_bytes),
        status=row.status,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


def _limit_bytes() -> int:
    return channel_dataset_max_total_gb() * _BYTES_PER_GB


class DatasetRegistry:
    """Create dataset tables and keep the registry row in step with them."""

    def __init__(self, store: MemoryDatasetStore | SqlDatasetStore) -> None:
        self._store = store

    def create_from_query(
        self, *, job_id: str, node_id: str, seq: int, query: str
    ) -> DatasetRecord:
        record = self._begin(job_id=job_id, node_id=node_id, seq=seq)
        try:
            row_count, size = create_table_from_query(record.relation, query)
            columns = [
                {**column, "normalized_type": normalized_type_of(column["type"])}
                for column in column_types(record.relation)
            ]
        except Exception:
            self._drop_failed(record)
            raise
        return self._ready(record, columns=columns, row_count=row_count, size=size)

    def create_from_chunks(
        self,
        *,
        job_id: str,
        node_id: str,
        seq: int,
        columns: Sequence[DatasetColumnSpec],
        chunks: Iterable[Sequence[Sequence[Any]]],
    ) -> DatasetRecord:
        record = self._begin(job_id=job_id, node_id=node_id, seq=seq)

        def on_chunk(size: int) -> None:
            record.size_bytes = size
            self._store.save(record)
            if self._store.used_bytes() >= _limit_bytes():
                raise DatasetQuotaExceeded()

        try:
            row_count, size = copy_chunks(
                record.relation,
                [_pg_column(column) for column in columns],
                chunks,
                on_chunk_size=on_chunk,
            )
            stored_columns = _with_normalized_types(column_types(record.relation), columns)
        except Exception:
            self._drop_failed(record)
            raise
        return self._ready(record, columns=stored_columns, row_count=row_count, size=size)

    def read_page(self, dataset_id: str, *, after_ord: int, limit: int) -> list[dict[str, Any]]:
        return read_keyset_page(
            self._require(dataset_id).relation, after_ord=after_ord, limit=limit
        )

    def is_lost(self, dataset_id: str) -> bool:
        record = self._require(dataset_id)
        if record.row_count <= 0:
            return False
        return not any_row_exists(record.relation)

    def _begin(self, *, job_id: str, node_id: str, seq: int) -> DatasetRecord:
        self._ensure_capacity()
        dataset_id = "d" + uuid.uuid4().hex
        record = DatasetRecord(
            id=dataset_id,
            job_id=job_id,
            node_id=node_id,
            seq=seq,
            relation=physical_relation(dataset_id),
            columns=[],
            row_count=0,
            size_bytes=0,
            status="loading",
            created_at=utc_now(),
            expires_at=None,
        )
        self._store.save(record)
        return record

    def _drop_failed(self, record: DatasetRecord) -> None:
        drop_relation(record.relation)
        record.status = "dropped"
        self._store.save(record)

    def _ready(
        self,
        record: DatasetRecord,
        *,
        columns: list[dict[str, Any]],
        row_count: int,
        size: int,
    ) -> DatasetRecord:
        record.columns = columns
        record.row_count = row_count
        record.size_bytes = size
        record.status = "ready"
        self._store.save(record)
        return record

    def _ensure_capacity(self) -> None:
        if self._store.used_bytes() >= _limit_bytes():
            raise DatasetQuotaExceeded()

    def _require(self, dataset_id: str) -> DatasetRecord:
        record = self._store.get(dataset_id)
        if record is None:
            raise KeyError(dataset_id)
        return record


def _pg_column(column: DatasetColumnSpec) -> tuple[str, str]:
    return column.name, postgres_type(
        column.normalized_type,
        precision=column.precision,
        scale=column.scale,
        with_time_zone=column.with_time_zone,
    )


def _with_normalized_types(
    columns: list[dict[str, str]], specs: Sequence[DatasetColumnSpec]
) -> list[dict[str, Any]]:
    by_name = {spec.name: spec.normalized_type for spec in specs}
    stored: list[dict[str, Any]] = []
    for column in columns:
        stored.append({**column, "normalized_type": by_name[column["name"]]})
    return stored
