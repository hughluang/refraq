"""Channel run and node-execution records."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text

from backend.channel.models import ChannelNodeExecutionRow, ChannelRunRow
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now
from backend.jobs.store import TERMINAL, get_job_store
from backend.jobs.store import TERMINAL, get_job_store

__all__ = [
    "ChannelRunRecord",
    "NodeExecutionRecord",
    "get_run_store",
    "note_killed_run",
]


@dataclass
class ChannelRunRecord:
    job_id: str
    channel_id: str
    target: str
    version: int | None
    draft_revision: int | None
    graph: dict[str, Any] | None
    trigger_node_id: str
    ignore_checkpoints: bool
    outcome: str | None
    failed_node_id: str | None
    skipped_node_ids: list[str]
    created_at: datetime
    stopped_node_id: str | None = None
    stop_at_node_id: str | None = None
    pinned: list[dict[str, Any]] = field(default_factory=list)
    # `self.channel`, `self.run`, and `self.platform`; None until the run starts.
    context: dict[str, Any] | None = None


@dataclass
class NodeExecutionRecord:
    id: str
    job_id: str
    node_id: str
    seq: int
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    output: Any
    output_bytes: int
    error_code: str | None
    error_message: str | None
    error_detail: dict[str, Any] | None


class MemoryRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, ChannelRunRecord] = {}
        self._execs: dict[str, NodeExecutionRecord] = {}
        self._lock = threading.Lock()

    def insert_run(self, record: ChannelRunRecord) -> None:
        with self._lock:
            self._runs[record.job_id] = record

    def update_run(self, record: ChannelRunRecord) -> None:
        with self._lock:
            self._runs[record.job_id] = record

    def get_run(self, job_id: str) -> ChannelRunRecord | None:
        with self._lock:
            return self._runs.get(job_id)

    def list_runs(
        self,
        channel_id: str,
        *,
        status: str | None,
        target: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ChannelRunRecord], int]:
        del status
        with self._lock:
            items = [
                item
                for item in self._runs.values()
                if item.channel_id == channel_id
                and (target is None or item.target == target)
            ]
        items.sort(key=lambda item: (item.created_at, item.job_id), reverse=True)
        return items[offset : offset + limit], len(items)

    def start_execution(self, job_id: str, node_id: str) -> NodeExecutionRecord:
        with self._lock:
            seq = 1 + sum(1 for item in self._execs.values() if item.job_id == job_id)
            record = NodeExecutionRecord(
                id=f"cne_{uuid.uuid4().hex[:12]}",
                job_id=job_id,
                node_id=node_id,
                seq=seq,
                status="running",
                started_at=utc_now(),
                finished_at=None,
                output=None,
                output_bytes=0,
                error_code=None,
                error_message=None,
                error_detail=None,
            )
            self._execs[record.id] = record
            return record

    def finish_execution(self, record: NodeExecutionRecord) -> None:
        with self._lock:
            self._execs[record.id] = record

    def list_executions(self, job_id: str) -> list[NodeExecutionRecord]:
        with self._lock:
            items = [item for item in self._execs.values() if item.job_id == job_id]
        items.sort(key=lambda item: item.seq)
        return items

    def get_execution(self, job_id: str, seq: int) -> NodeExecutionRecord | None:
        for item in self.list_executions(job_id):
            if item.seq == seq:
                return item
        return None

    def delete_expired_terminal_runs(self, cutoff: datetime) -> int:
        """Delete runs created before ``cutoff`` whose Job is terminal.

        Node executions of those runs go with them. Jobs stay. A run whose Job
        is missing or unfinished stays.
        """
        jobs = get_job_store()
        with self._lock:
            doomed = [
                record.job_id
                for record in self._runs.values()
                if record.created_at < cutoff
                and (job := jobs.get(record.job_id)) is not None
                and job.status in TERMINAL
            ]
            for job_id in doomed:
                del self._runs[job_id]
            drop = [key for key, item in self._execs.items() if item.job_id in set(doomed)]
            for key in drop:
                del self._execs[key]
            return len(doomed)


class SqlRunStore:
    def insert_run(self, record: ChannelRunRecord) -> None:
        with session_scope() as session:
            session.add(_run_row(record))

    def update_run(self, record: ChannelRunRecord) -> None:
        with session_scope() as session:
            row = session.get(ChannelRunRow, record.job_id)
            if row is None:
                raise RuntimeError(f"channel run {record.job_id} is missing")
            row.version = record.version
            row.draft_revision = record.draft_revision
            row.graph = record.graph
            row.outcome = record.outcome
            row.failed_node_id = record.failed_node_id
            row.stopped_node_id = record.stopped_node_id
            row.trigger_node_id = record.trigger_node_id
            row.skipped_node_ids = list(record.skipped_node_ids)
            row.context = record.context

    def get_run(self, job_id: str) -> ChannelRunRecord | None:
        with session_scope() as session:
            row = session.get(ChannelRunRow, job_id)
            return None if row is None else _run_record(row)

    def list_runs(
        self,
        channel_id: str,
        *,
        status: str | None,
        target: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ChannelRunRecord], int]:
        del status
        with session_scope() as session:
            stmt = select(ChannelRunRow).where(ChannelRunRow.channel_id == channel_id)
            if target is not None:
                stmt = stmt.where(ChannelRunRow.target == target)
            total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
            rows = session.scalars(
                stmt.order_by(ChannelRunRow.created_at.desc(), ChannelRunRow.job_id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            return [_run_record(row) for row in rows], total

    def start_execution(self, job_id: str, node_id: str) -> NodeExecutionRecord:
        with session_scope() as session:
            seq = int(
                session.scalar(
                    select(func.count())
                    .select_from(ChannelNodeExecutionRow)
                    .where(ChannelNodeExecutionRow.job_id == job_id)
                )
                or 0
            ) + 1
            record = NodeExecutionRecord(
                id=f"cne_{uuid.uuid4().hex[:12]}",
                job_id=job_id,
                node_id=node_id,
                seq=seq,
                status="running",
                started_at=utc_now(),
                finished_at=None,
                output=None,
                output_bytes=0,
                error_code=None,
                error_message=None,
                error_detail=None,
            )
            session.add(_exec_row(record))
            return record

    def finish_execution(self, record: NodeExecutionRecord) -> None:
        with session_scope() as session:
            row = session.get(ChannelNodeExecutionRow, record.id)
            if row is None:
                raise RuntimeError(f"channel node execution {record.id} is missing")
            row.status = record.status
            row.finished_at = record.finished_at
            row.output = record.output
            row.output_bytes = record.output_bytes
            row.error_code = record.error_code
            row.error_message = record.error_message
            row.error_detail = record.error_detail

    def list_executions(self, job_id: str) -> list[NodeExecutionRecord]:
        with session_scope() as session:
            rows = session.scalars(
                select(ChannelNodeExecutionRow)
                .where(ChannelNodeExecutionRow.job_id == job_id)
                .order_by(ChannelNodeExecutionRow.seq)
            ).all()
            return [_exec_record(row) for row in rows]

    def get_execution(self, job_id: str, seq: int) -> NodeExecutionRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(ChannelNodeExecutionRow).where(
                    ChannelNodeExecutionRow.job_id == job_id,
                    ChannelNodeExecutionRow.seq == seq,
                )
            )
            return None if row is None else _exec_record(row)

    def delete_expired_terminal_runs(self, cutoff: datetime) -> int:
        """Delete runs created before ``cutoff`` whose Job is terminal.

        ``channel_node_executions`` cascade with the run. Jobs stay.
        """
        statuses = list(TERMINAL)
        holders = ", ".join(f":status_{index}" for index in range(len(statuses)))
        params: dict[str, Any] = {
            f"status_{index}": status for index, status in enumerate(statuses)
        }
        params["cutoff"] = cutoff
        with session_scope() as session:
            result = session.execute(
                text(
                    "DELETE FROM channel_runs WHERE created_at < :cutoff "
                    f"AND job_id IN (SELECT id FROM jobs WHERE status IN ({holders}))"
                ),
                params,
            )
            return int(result.rowcount or 0)


def _run_row(record: ChannelRunRecord) -> ChannelRunRow:
    return ChannelRunRow(
        job_id=record.job_id,
        channel_id=record.channel_id,
        target=record.target,
        version=record.version,
        draft_revision=record.draft_revision,
        graph=record.graph,
        trigger_node_id=record.trigger_node_id,
        ignore_checkpoints=record.ignore_checkpoints,
        outcome=record.outcome,
        failed_node_id=record.failed_node_id,
        stopped_node_id=record.stopped_node_id,
        stop_at_node_id=record.stop_at_node_id,
        pinned=list(record.pinned),
        skipped_node_ids=list(record.skipped_node_ids),
        context=record.context,
        created_at=record.created_at,
    )


def _run_record(row: ChannelRunRow) -> ChannelRunRecord:
    return ChannelRunRecord(
        job_id=row.job_id,
        channel_id=row.channel_id,
        target=row.target,
        version=row.version,
        draft_revision=row.draft_revision,
        graph=row.graph,
        trigger_node_id=row.trigger_node_id,
        ignore_checkpoints=row.ignore_checkpoints,
        outcome=row.outcome,
        failed_node_id=row.failed_node_id,
        skipped_node_ids=list(row.skipped_node_ids or []),
        created_at=row.created_at,
        stopped_node_id=row.stopped_node_id,
        stop_at_node_id=row.stop_at_node_id,
        pinned=list(row.pinned),
        context=row.context,
    )


def _exec_row(record: NodeExecutionRecord) -> ChannelNodeExecutionRow:
    return ChannelNodeExecutionRow(
        id=record.id,
        job_id=record.job_id,
        node_id=record.node_id,
        seq=record.seq,
        status=record.status,
        started_at=record.started_at,
        finished_at=record.finished_at,
        output=record.output,
        output_bytes=record.output_bytes,
        error_code=record.error_code,
        error_message=record.error_message,
        error_detail=record.error_detail,
    )


def _exec_record(row: ChannelNodeExecutionRow) -> NodeExecutionRecord:
    return NodeExecutionRecord(
        id=row.id,
        job_id=row.job_id,
        node_id=row.node_id,
        seq=row.seq,
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        output=row.output,
        output_bytes=row.output_bytes,
        error_code=row.error_code,
        error_message=row.error_message,
        error_detail=row.error_detail,
    )


def output_page(output: Any, path: str | None, *, limit: int, offset: int) -> dict[str, Any]:
    value = output
    if path:
        for part in path.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                value = None
                break
    if isinstance(value, list):
        return {
            "items": value[offset : offset + limit],
            "total": len(value),
            "limit": limit,
            "offset": offset,
        }
    return {"value": value}


def output_preview(output: Any, *, cap: int = 100) -> Any:
    return output_preview_with_truncated(output, cap=cap)[0]


def output_preview_with_truncated(
    output: Any, *, cap: int = 100
) -> tuple[Any, bool]:
    return _cut(output, cap)


def _cut(value: Any, cap: int) -> tuple[Any, bool]:
    if isinstance(value, list):
        items = [_cut(item, cap) for item in value[:cap]]
        return [item for item, _truncated in items], (
            len(value) > cap or any(truncated for _item, truncated in items)
        )
    if isinstance(value, dict):
        items = {key: _cut(item, cap) for key, item in value.items()}
        return (
            {key: item for key, (item, _truncated) in items.items()},
            any(truncated for _item, truncated in items.values()),
        )
    return value, False


def note_killed_run(job_id: str) -> None:
    """Record the node a killed child left running, when one exists."""
    store = get_run_store()
    run = store.get_run(job_id)
    if run is None:
        return
    running = [item for item in store.list_executions(job_id) if item.status == "running"]
    if not running:
        return
    current = running[-1]
    current.status = "failed"
    current.finished_at = utc_now()
    current.error_message = "cancelled"
    store.finish_execution(current)
    if run.stopped_node_id is None:
        run.stopped_node_id = current.node_id
        store.update_run(run)


def output_size(output: Any) -> int:
    try:
        return len(json.dumps(output))
    except TypeError:
        return 0


_memory: MemoryRunStore | None = None
_lock = threading.Lock()


def get_run_store() -> MemoryRunStore | SqlRunStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryRunStore()
            return _memory
    return SqlRunStore()
