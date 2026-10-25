"""Platform registry of run-scoped dataset tables.

``channel_datasets.job_id`` is a plain column, not a foreign key to
``channel_runs.job_id``. The physical table lives in the entity database, so
deleting a run record cannot drop it. ``ON DELETE CASCADE`` would remove the
only stored relation name before a later purge could drop the table.
``expires_at`` stays null until a terminal job is sealed from ``finished_at``.
"""

from __future__ import annotations

import copy
import logging
import threading
import uuid
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update

from backend.channel.errors import TemporalTargetIncompatible
from backend.channel.models import ChannelDatasetRow
from backend.channel.parameters import (
    channel_dataset_max_total_gb,
    channel_dataset_retention_days,
    channel_dataset_success_retention_hours,
)
from backend.channel.run_store import get_run_store
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now
from backend.entity.datasets import (
    any_row_exists,
    column_types,
    copy_chunks,
    create_table_from_query,
    drop_relation,
    format_type_declaration,
    list_dataset_relations,
    normalized_type_of,
    physical_relation,
    postgres_type,
    read_keyset_page,
    temporal_target_conflict,
    temporal_value_conflict,
)
from backend.jobs.store import TERMINAL, get_job_store

__all__ = [
    "DatasetColumnSpec",
    "DatasetQuotaExceeded",
    "DatasetRecord",
    "DatasetRegistry",
    "MemoryDatasetStore",
    "SqlDatasetStore",
    "get_dataset_store",
    "reset_dataset_store",
    "seal_dataset_expiry",
]

logger = logging.getLogger(__name__)

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
    temporal_kind: str | None = None
    nullable: bool | None = None


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

    def seal_null_expiry(self, job_id: str, expires_at: datetime) -> None:
        with self._lock:
            for record in self._rows.values():
                if record.job_id == job_id and record.expires_at is None:
                    record.expires_at = expires_at

    def unsealed_job_ids(self) -> list[str]:
        with self._lock:
            return list(
                {record.job_id for record in self._rows.values() if record.expires_at is None}
            )

    def list_for_jobs(self, job_ids: Sequence[str]) -> list[DatasetRecord]:
        wanted = set(job_ids)
        if not wanted:
            return []
        with self._lock:
            return [
                copy.deepcopy(record)
                for record in self._rows.values()
                if record.job_id in wanted
            ]

    def list_expired(self, now: datetime) -> list[DatasetRecord]:
        with self._lock:
            return [
                copy.deepcopy(record)
                for record in self._rows.values()
                if record.expires_at is not None
                and record.expires_at <= now
                and record.status in _CAPACITY_STATUSES
            ]

    def active_relations(self) -> set[str]:
        with self._lock:
            return {
                record.relation
                for record in self._rows.values()
                if record.status in _CAPACITY_STATUSES
            }


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

    def seal_null_expiry(self, job_id: str, expires_at: datetime) -> None:
        with session_scope() as session:
            session.execute(
                update(ChannelDatasetRow)
                .where(
                    ChannelDatasetRow.job_id == job_id,
                    ChannelDatasetRow.expires_at.is_(None),
                )
                .values(expires_at=expires_at)
            )

    def unsealed_job_ids(self) -> list[str]:
        with session_scope() as session:
            rows = session.scalars(
                select(ChannelDatasetRow.job_id)
                .where(ChannelDatasetRow.expires_at.is_(None))
                .distinct()
            ).all()
            return [str(job_id) for job_id in rows]

    def list_for_jobs(self, job_ids: Sequence[str]) -> list[DatasetRecord]:
        if not job_ids:
            return []
        with session_scope() as session:
            rows = session.scalars(
                select(ChannelDatasetRow).where(ChannelDatasetRow.job_id.in_(tuple(job_ids)))
            ).all()
            return [_from_row(row) for row in rows]

    def list_expired(self, now: datetime) -> list[DatasetRecord]:
        with session_scope() as session:
            rows = session.scalars(
                select(ChannelDatasetRow).where(
                    ChannelDatasetRow.expires_at.is_not(None),
                    ChannelDatasetRow.expires_at <= now,
                    ChannelDatasetRow.status.in_(tuple(_CAPACITY_STATUSES)),
                )
            ).all()
            return [_from_row(row) for row in rows]

    def active_relations(self) -> set[str]:
        with session_scope() as session:
            rows = session.scalars(
                select(ChannelDatasetRow.relation).where(
                    ChannelDatasetRow.status.in_(tuple(_CAPACITY_STATUSES))
                )
            ).all()
            return {str(relation) for relation in rows}


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
                _declared_format_column(column) for column in column_types(record.relation)
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
        _reject_temporal_target(columns)
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
                _reject_temporal_values(columns, chunks),
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


def _declared_format_column(column: dict[str, str]) -> dict[str, Any]:
    kind, precision = format_type_declaration(column["type"])
    return {
        **column,
        "normalized_type": normalized_type_of(column["type"]),
        "temporal_kind": kind,
        "precision": precision,
        "nullable": None,
    }


def _reject_temporal_values(
    columns: Sequence[DatasetColumnSpec],
    chunks: Iterable[Sequence[Sequence[Any]]],
) -> Iterator[Sequence[Sequence[Any]]]:
    specs = list(columns)
    for chunk in chunks:
        for row in chunk:
            if isinstance(row, (str, bytes)) or not isinstance(row, Sequence):
                continue
            for spec, cell in zip(specs, row):
                conflict = temporal_value_conflict(
                    temporal_kind=spec.temporal_kind,
                    precision=spec.precision,
                    value=cell,
                )
                if conflict is None:
                    continue
                raise TemporalTargetIncompatible(
                    declaration=conflict["declaration"],
                    value=conflict["value"],
                    target_limit=conflict["target_limit"],
                )
        yield chunk


def _reject_temporal_target(columns: Sequence[DatasetColumnSpec]) -> None:
    for column in columns:
        conflict = temporal_target_conflict(
            temporal_kind=column.temporal_kind,
            precision=column.precision,
        )
        if conflict is not None:
            raise TemporalTargetIncompatible(
                declaration=conflict["declaration"],
                value=conflict["value"],
                target_limit=conflict["target_limit"],
            )


def _pg_column(column: DatasetColumnSpec) -> tuple[str, str]:
    return column.name, postgres_type(
        column.normalized_type,
        precision=column.precision,
        scale=column.scale,
        with_time_zone=column.with_time_zone,
        temporal_kind=column.temporal_kind,
    )


def seal_dataset_expiry(job_id: str) -> None:
    """Write ``expires_at`` once, anchored on the job's ``finished_at``.

    A succeeded run whose target is not ``draft`` uses success retention hours.
    Zero hours is due at ``finished_at``. Every other terminal run, including
    every draft, uses retention days. An existing timestamp is left alone.
    A non-terminal job is left null.
    """
    job = get_job_store().get(job_id)
    if job is None or job.status not in TERMINAL or job.finished_at is None:
        return
    run = get_run_store().get_run(job_id)
    target = run.target if run is not None else None
    if job.status == "succeeded" and target != "draft":
        expires_at = job.finished_at + timedelta(
            hours=channel_dataset_success_retention_hours()
        )
    else:
        expires_at = job.finished_at + timedelta(days=channel_dataset_retention_days())
    get_dataset_store().seal_null_expiry(job_id, expires_at)


def seal_unsealed_terminal_datasets() -> None:
    """Safety net: seal any still-null row whose job is already terminal."""
    for job_id in get_dataset_store().unsealed_job_ids():
        seal_dataset_expiry(job_id)


def drop_expired_datasets(now: datetime) -> None:
    """Drop tables whose ``expires_at`` is due.

    A ``loading`` row stays while its job is not terminal.
    """
    jobs = get_job_store()
    for record in get_dataset_store().list_expired(now):
        if record.status == "loading":
            job = jobs.get(record.job_id)
            if job is None or job.status not in TERMINAL:
                continue
        _drop_and_mark(record)


def drop_orphan_dataset_tables() -> None:
    """Drop ``ds_*`` tables that have no loading or ready registry row."""
    protected = get_dataset_store().active_relations()
    for relation in list_dataset_relations():
        if relation in protected:
            continue
        try:
            drop_relation(relation)
        except Exception:
            logger.exception("orphan dataset drop failed relation=%s", relation)


def drop_datasets_for_due_runs(cutoff: datetime) -> None:
    """Drop physical tables for runs the retention purge is about to delete."""
    _drop_registered(get_run_store().job_ids_due(cutoff))


def _drop_registered(job_ids: Sequence[str]) -> None:
    for record in get_dataset_store().list_for_jobs(job_ids):
        if record.status not in _CAPACITY_STATUSES:
            continue
        _drop_and_mark(record)


def _drop_and_mark(record: DatasetRecord) -> None:
    try:
        drop_relation(record.relation)
    except Exception:
        logger.exception("dataset table drop failed id=%s", record.id)
        return
    record.status = "dropped"
    get_dataset_store().save(record)


_memory_datasets: MemoryDatasetStore | None = None
_dataset_lock = threading.Lock()


def get_dataset_store() -> MemoryDatasetStore | SqlDatasetStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_datasets
        with _dataset_lock:
            if _memory_datasets is None:
                _memory_datasets = MemoryDatasetStore()
            return _memory_datasets
    return SqlDatasetStore()


def reset_dataset_store() -> None:
    global _memory_datasets
    with _dataset_lock:
        _memory_datasets = None


def _with_normalized_types(
    columns: list[dict[str, str]], specs: Sequence[DatasetColumnSpec]
) -> list[dict[str, Any]]:
    by_name = {spec.name: spec for spec in specs}
    stored: list[dict[str, Any]] = []
    for column in columns:
        spec = by_name[column["name"]]
        stored.append(
            {
                **column,
                "normalized_type": spec.normalized_type,
                "temporal_kind": spec.temporal_kind,
                "precision": spec.precision if spec.temporal_kind else None,
                "nullable": spec.nullable,
            }
        )
    return stored
