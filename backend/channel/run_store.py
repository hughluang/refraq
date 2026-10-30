"""Channel run and node-execution records."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import func, select, text

from backend.channel.models import (
    ChannelContainerRoundRow,
    ChannelNodeExecutionRow,
    ChannelRunRow,
)
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now
from backend.jobs.store import TERMINAL, get_job_store

__all__ = [
    "ChannelRunRecord",
    "ContainerRoundRecord",
    "NodeExecutionRecord",
    "NodeExecutionSummary",
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
    # `self.channel`, `self.run`, and `self.platform`; None until the run starts.
    context: dict[str, Any] | None = None
    # node id -> stream -> {"xact", "seq"}. None until a node proposes a position.
    checkpoint_proposals: dict[str, Any] | None = None


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
    container_seq: int | None = None
    round: int | None = None
    preview_only: bool = False
    preview_totals: dict[str, int] = field(default_factory=dict)
    input: Any = None
    input_totals: dict[str, int] | None = None


@dataclass
class NodeExecutionSummary:
    node_id: str
    execution_count: int
    status_counts: dict[str, int]


@dataclass
class ContainerRoundRecord:
    job_id: str
    container_seq: int
    round: int
    step: Any
    step_totals: dict[str, int]


def _execution_matches(
    item: NodeExecutionRecord,
    *,
    node_id: str | None,
    container_seq: int | None,
    round_index: int | None,
    status: str | None,
) -> bool:
    if node_id is not None and item.node_id != node_id:
        return False
    if container_seq is not None and item.container_seq != container_seq:
        return False
    if round_index is not None and item.round != round_index:
        return False
    if status is not None and item.status != status:
        return False
    return True


def _summarize(items: list[NodeExecutionRecord]) -> list[NodeExecutionSummary]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in sorted(items, key=lambda record: record.seq):
        bucket = grouped.get(item.node_id)
        if bucket is None:
            bucket = {
                "execution_count": 0,
                "status_counts": {},
                "first_seq": item.seq,
            }
            grouped[item.node_id] = bucket
        bucket["execution_count"] += 1
        counts: dict[str, int] = bucket["status_counts"]
        counts[item.status] = counts.get(item.status, 0) + 1
    ordered = sorted(grouped.items(), key=lambda entry: entry[1]["first_seq"])
    return [
        NodeExecutionSummary(
            node_id=node_id,
            execution_count=bucket["execution_count"],
            status_counts=bucket["status_counts"],
        )
        for node_id, bucket in ordered
    ]


def _summaries_from_groups(
    rows: list[tuple[Any, ...]],
) -> list[NodeExecutionSummary]:
    grouped: dict[str, dict[str, Any]] = {}
    for node_id, status, count, min_seq in rows:
        bucket = grouped.get(str(node_id))
        if bucket is None:
            bucket = {
                "execution_count": 0,
                "status_counts": {},
                "first_seq": int(min_seq),
            }
            grouped[str(node_id)] = bucket
        bucket["execution_count"] += int(count)
        bucket["status_counts"][str(status)] = int(count)
        bucket["first_seq"] = min(int(bucket["first_seq"]), int(min_seq))
    ordered = sorted(grouped.items(), key=lambda entry: entry[1]["first_seq"])
    return [
        NodeExecutionSummary(
            node_id=node_id,
            execution_count=bucket["execution_count"],
            status_counts=bucket["status_counts"],
        )
        for node_id, bucket in ordered
    ]


def _run_is_due(created_at: datetime, job_id: str, cutoff: datetime, jobs: Any) -> bool:
    """A memory run created before ``cutoff`` whose Job is terminal."""
    job = jobs.get(job_id)
    return created_at < cutoff and job is not None and job.status in TERMINAL


def _due_runs_clause(cutoff: datetime) -> tuple[str, dict[str, Any]]:
    """SQL for ``created_at < cutoff`` and a terminal Job.

    ``DELETE`` and the id lookup share this text so the two cannot drift.
    """
    statuses = list(TERMINAL)
    holders = ", ".join(f":status_{index}" for index in range(len(statuses)))
    params: dict[str, Any] = {
        f"status_{index}": status for index, status in enumerate(statuses)
    }
    params["cutoff"] = cutoff
    clause = (
        "created_at < :cutoff "
        f"AND job_id IN (SELECT id FROM jobs WHERE status IN ({holders}))"
    )
    return clause, params


class MemoryRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, ChannelRunRecord] = {}
        self._execs: dict[str, NodeExecutionRecord] = {}
        self._rounds: dict[tuple[str, int, int], ContainerRoundRecord] = {}
        self._lock = threading.Lock()

    def insert_run(self, record: ChannelRunRecord) -> None:
        with self._lock:
            self._runs[record.job_id] = record

    def update_run(self, record: ChannelRunRecord) -> None:
        with self._lock:
            self._runs[record.job_id] = record

    def set_checkpoint_proposals(self, job_id: str, proposals: dict[str, Any]) -> None:
        with self._lock:
            record = self._runs.get(job_id)
            if record is None:
                raise RuntimeError(f"channel run {job_id} is missing")
            record.checkpoint_proposals = proposals

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

    def start_execution(
        self,
        job_id: str,
        node_id: str,
        *,
        container_seq: int | None = None,
        round: int | None = None,
    ) -> NodeExecutionRecord:
        with self._lock:
            seqs = [item.seq for item in self._execs.values() if item.job_id == job_id]
            seq = (max(seqs) if seqs else 0) + 1
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
                container_seq=container_seq,
                round=round,
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

    def execution_summaries(self, job_id: str) -> list[NodeExecutionSummary]:
        with self._lock:
            items = [item for item in self._execs.values() if item.job_id == job_id]
        return _summarize(items)

    def query_executions(
        self,
        job_id: str,
        *,
        node_id: str | None,
        container_seq: int | None,
        round_index: int | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[NodeExecutionRecord], int]:
        with self._lock:
            items = [item for item in self._execs.values() if item.job_id == job_id]
        matched = [
            item
            for item in items
            if _execution_matches(
                item,
                node_id=node_id,
                container_seq=container_seq,
                round_index=round_index,
                status=status,
            )
        ]
        matched.sort(key=lambda item: item.seq)
        return matched[offset : offset + limit], len(matched)

    def get_execution(self, job_id: str, seq: int) -> NodeExecutionRecord | None:
        for item in self.list_executions(job_id):
            if item.seq == seq:
                return item
        return None

    def insert_round(
        self,
        job_id: str,
        *,
        container_seq: int,
        round: int,
        step: Any,
        step_totals: Mapping[str, int],
    ) -> None:
        record = ContainerRoundRecord(
            job_id=job_id,
            container_seq=container_seq,
            round=round,
            step=step,
            step_totals={str(key): int(value) for key, value in step_totals.items()},
        )
        with self._lock:
            self._rounds[(job_id, container_seq, round)] = record

    def set_round_template(
        self,
        job_id: str,
        *,
        container_seq: int,
        round: int,
        path: str,
        entry: Any,
    ) -> None:
        """Add one Round Template entry to a round that was already inserted."""
        key = (job_id, container_seq, round)
        with self._lock:
            record = self._rounds.get(key)
            if record is None:
                raise RuntimeError(f"channel container round {key} is missing")
            record.step = {**record.step, path: entry}

    def query_rounds(
        self,
        job_id: str,
        container_seq: int,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[ContainerRoundRecord], int]:
        with self._lock:
            matched = [
                item
                for item in self._rounds.values()
                if item.job_id == job_id and item.container_seq == container_seq
            ]
        matched.sort(key=lambda item: item.round)
        return matched[offset : offset + limit], len(matched)

    def get_round(
        self, job_id: str, container_seq: int, round_index: int
    ) -> ContainerRoundRecord | None:
        """The recorded step for one container execution and round, if any."""
        with self._lock:
            return self._rounds.get((job_id, container_seq, round_index))

    def round_status_counts(
        self, job_id: str, container_seq: int
    ) -> dict[int, dict[str, int]]:
        """Counts of direct child executions grouped by round and status."""
        with self._lock:
            items = [
                item
                for item in self._execs.values()
                if item.job_id == job_id
                and item.container_seq == container_seq
                and item.round is not None
            ]
        counts: dict[int, dict[str, int]] = {}
        for item in items:
            bucket = counts.setdefault(item.round, {})
            bucket[item.status] = bucket.get(item.status, 0) + 1
        return counts

    def job_ids_due(self, cutoff: datetime) -> list[str]:
        """Job ids of runs created before ``cutoff`` whose Job is terminal.

        Same predicate as ``delete_expired_terminal_runs``. Does not delete.
        """
        jobs = get_job_store()
        with self._lock:
            snapshot = [
                (record.created_at, record.job_id) for record in self._runs.values()
            ]
        return [
            job_id
            for created_at, job_id in snapshot
            if _run_is_due(created_at, job_id, cutoff, jobs)
        ]

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
                if _run_is_due(record.created_at, record.job_id, cutoff, jobs)
            ]
            for job_id in doomed:
                del self._runs[job_id]
            doomed_ids = set(doomed)
            drop = [
                key for key, item in self._execs.items() if item.job_id in doomed_ids
            ]
            for key in drop:
                del self._execs[key]
            drop_rounds = [
                key for key, item in self._rounds.items() if item.job_id in doomed_ids
            ]
            for key in drop_rounds:
                del self._rounds[key]
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
            row.checkpoint_proposals = record.checkpoint_proposals

    def set_checkpoint_proposals(self, job_id: str, proposals: dict[str, Any]) -> None:
        with session_scope() as session:
            row = session.get(ChannelRunRow, job_id)
            if row is None:
                raise RuntimeError(f"channel run {job_id} is missing")
            row.checkpoint_proposals = proposals

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
            total = int(
                session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            )
            rows = session.scalars(
                stmt.order_by(
                    ChannelRunRow.created_at.desc(), ChannelRunRow.job_id.desc()
                )
                .limit(limit)
                .offset(offset)
            ).all()
            return [_run_record(row) for row in rows], total

    def start_execution(
        self,
        job_id: str,
        node_id: str,
        *,
        container_seq: int | None = None,
        round: int | None = None,
    ) -> NodeExecutionRecord:
        with session_scope() as session:
            seq = (
                int(
                    session.scalar(
                        select(func.max(ChannelNodeExecutionRow.seq)).where(
                            ChannelNodeExecutionRow.job_id == job_id
                        )
                    )
                    or 0
                )
                + 1
            )
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
                container_seq=container_seq,
                round=round,
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
            row.output = _pack_output(record)
            row.output_bytes = record.output_bytes
            row.error_code = record.error_code
            row.error_message = record.error_message
            row.error_detail = record.error_detail
            row.input = record.input
            row.input_totals = record.input_totals

    def list_executions(self, job_id: str) -> list[NodeExecutionRecord]:
        with session_scope() as session:
            rows = session.scalars(
                select(ChannelNodeExecutionRow)
                .where(ChannelNodeExecutionRow.job_id == job_id)
                .order_by(ChannelNodeExecutionRow.seq)
            ).all()
            return [_exec_record(row) for row in rows]

    def execution_summaries(self, job_id: str) -> list[NodeExecutionSummary]:
        with session_scope() as session:
            rows = session.execute(
                select(
                    ChannelNodeExecutionRow.node_id,
                    ChannelNodeExecutionRow.status,
                    func.count(),
                    func.min(ChannelNodeExecutionRow.seq),
                )
                .where(ChannelNodeExecutionRow.job_id == job_id)
                .group_by(
                    ChannelNodeExecutionRow.node_id,
                    ChannelNodeExecutionRow.status,
                )
            ).all()
            return _summaries_from_groups([tuple(row) for row in rows])

    def query_executions(
        self,
        job_id: str,
        *,
        node_id: str | None,
        container_seq: int | None,
        round_index: int | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[NodeExecutionRecord], int]:
        clauses = _execution_clauses(
            job_id,
            node_id=node_id,
            container_seq=container_seq,
            round_index=round_index,
            status=status,
        )
        with session_scope() as session:
            total = int(
                session.scalar(
                    select(func.count())
                    .select_from(ChannelNodeExecutionRow)
                    .where(*clauses)
                )
                or 0
            )
            rows = session.scalars(
                select(ChannelNodeExecutionRow)
                .where(*clauses)
                .order_by(ChannelNodeExecutionRow.seq)
                .limit(limit)
                .offset(offset)
            ).all()
            return [_exec_record(row) for row in rows], total

    def get_execution(self, job_id: str, seq: int) -> NodeExecutionRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(ChannelNodeExecutionRow).where(
                    ChannelNodeExecutionRow.job_id == job_id,
                    ChannelNodeExecutionRow.seq == seq,
                )
            )
            return None if row is None else _exec_record(row)

    def insert_round(
        self,
        job_id: str,
        *,
        container_seq: int,
        round: int,
        step: Any,
        step_totals: Mapping[str, int],
    ) -> None:
        with session_scope() as session:
            session.add(
                ChannelContainerRoundRow(
                    job_id=job_id,
                    container_seq=container_seq,
                    round=round,
                    step=step,
                    step_totals={
                        str(key): int(value) for key, value in step_totals.items()
                    },
                )
            )

    def set_round_template(
        self,
        job_id: str,
        *,
        container_seq: int,
        round: int,
        path: str,
        entry: Any,
    ) -> None:
        """Add one Round Template entry to a round that was already inserted."""
        key = (job_id, container_seq, round)
        with session_scope() as session:
            row = session.get(ChannelContainerRoundRow, key)
            if row is None:
                raise RuntimeError(f"channel container round {key} is missing")
            row.step = {**row.step, path: entry}

    def query_rounds(
        self,
        job_id: str,
        container_seq: int,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[ContainerRoundRecord], int]:
        clauses = (
            ChannelContainerRoundRow.job_id == job_id,
            ChannelContainerRoundRow.container_seq == container_seq,
        )
        with session_scope() as session:
            total = int(
                session.scalar(
                    select(func.count())
                    .select_from(ChannelContainerRoundRow)
                    .where(*clauses)
                )
                or 0
            )
            rows = session.scalars(
                select(ChannelContainerRoundRow)
                .where(*clauses)
                .order_by(ChannelContainerRoundRow.round)
                .limit(limit)
                .offset(offset)
            ).all()
            return [_round_record(row) for row in rows], total

    def get_round(
        self, job_id: str, container_seq: int, round_index: int
    ) -> ContainerRoundRecord | None:
        """The recorded step for one container execution and round, if any."""
        with session_scope() as session:
            row = session.scalar(
                select(ChannelContainerRoundRow).where(
                    ChannelContainerRoundRow.job_id == job_id,
                    ChannelContainerRoundRow.container_seq == container_seq,
                    ChannelContainerRoundRow.round == round_index,
                )
            )
            return None if row is None else _round_record(row)

    def round_status_counts(
        self, job_id: str, container_seq: int
    ) -> dict[int, dict[str, int]]:
        """Counts of direct child executions grouped by round and status."""
        with session_scope() as session:
            rows = session.execute(
                select(
                    ChannelNodeExecutionRow.round,
                    ChannelNodeExecutionRow.status,
                    func.count(),
                )
                .where(
                    ChannelNodeExecutionRow.job_id == job_id,
                    ChannelNodeExecutionRow.container_seq == container_seq,
                    ChannelNodeExecutionRow.round.is_not(None),
                )
                .group_by(
                    ChannelNodeExecutionRow.round,
                    ChannelNodeExecutionRow.status,
                )
            ).all()
        counts: dict[int, dict[str, int]] = {}
        for round_index, status, count in rows:
            counts.setdefault(int(round_index), {})[str(status)] = int(count)
        return counts

    def job_ids_due(self, cutoff: datetime) -> list[str]:
        """Job ids of runs created before ``cutoff`` whose Job is terminal.

        Same predicate as ``delete_expired_terminal_runs``. Does not delete.
        """
        clause, params = _due_runs_clause(cutoff)
        with session_scope() as session:
            rows = session.execute(
                text(f"SELECT job_id FROM channel_runs WHERE {clause}"),
                params,
            ).scalars()
            return [str(job_id) for job_id in rows]

    def delete_expired_terminal_runs(self, cutoff: datetime) -> int:
        """Delete runs created before ``cutoff`` whose Job is terminal.

        ``channel_node_executions`` cascade with the run. Jobs stay.
        """
        clause, params = _due_runs_clause(cutoff)
        with session_scope() as session:
            result = session.execute(
                text(f"DELETE FROM channel_runs WHERE {clause}"),
                params,
            )
            return int(result.rowcount or 0)


def _execution_clauses(
    job_id: str,
    *,
    node_id: str | None,
    container_seq: int | None,
    round_index: int | None,
    status: str | None,
) -> list[Any]:
    clauses: list[Any] = [ChannelNodeExecutionRow.job_id == job_id]
    if node_id is not None:
        clauses.append(ChannelNodeExecutionRow.node_id == node_id)
    if container_seq is not None:
        clauses.append(ChannelNodeExecutionRow.container_seq == container_seq)
    if round_index is not None:
        clauses.append(ChannelNodeExecutionRow.round == round_index)
    if status is not None:
        clauses.append(ChannelNodeExecutionRow.status == status)
    return clauses


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
        skipped_node_ids=list(record.skipped_node_ids),
        context=record.context,
        checkpoint_proposals=record.checkpoint_proposals,
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
        context=row.context,
        checkpoint_proposals=row.checkpoint_proposals,
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
        output=_pack_output(record),
        output_bytes=record.output_bytes,
        error_code=record.error_code,
        error_message=record.error_message,
        error_detail=record.error_detail,
        container_seq=record.container_seq,
        round=record.round,
        input=record.input,
        input_totals=record.input_totals,
    )


def _exec_record(row: ChannelNodeExecutionRow) -> NodeExecutionRecord:
    output, preview_only, preview_totals = _unpack_output(row.output)
    return NodeExecutionRecord(
        id=row.id,
        job_id=row.job_id,
        node_id=row.node_id,
        seq=row.seq,
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        output=output,
        output_bytes=row.output_bytes,
        error_code=row.error_code,
        error_message=row.error_message,
        error_detail=row.error_detail,
        container_seq=row.container_seq,
        round=row.round,
        preview_only=preview_only,
        preview_totals=preview_totals,
        input=row.input,
        input_totals=_int_map(row.input_totals),
    )


def _round_record(row: ChannelContainerRoundRow) -> ContainerRoundRecord:
    return ContainerRoundRecord(
        job_id=row.job_id,
        container_seq=row.container_seq,
        round=row.round,
        step=row.step,
        step_totals=_int_map(row.step_totals) or {},
    )


def _int_map(raw: Any) -> dict[str, int] | None:
    if raw is None:
        return None
    return {str(key): int(value) for key, value in raw.items()}


_PREVIEW_MARK = "$refraq_preview"
_PREVIEW_VALUE = "$refraq_value"


def _pack_output(record: NodeExecutionRecord) -> Any:
    """Persist preview metadata beside the value without a second column.

    The marker keys are reserved. Node code never sets them. A non-preview
    execution stores its output unchanged.
    """
    if not record.preview_only:
        return record.output
    return {
        _PREVIEW_MARK: {
            "preview_only": True,
            "preview_totals": record.preview_totals,
        },
        _PREVIEW_VALUE: record.output,
    }


def _unpack_output(raw: Any) -> tuple[Any, bool, dict[str, int]]:
    if (
        isinstance(raw, dict)
        and set(raw) == {_PREVIEW_MARK, _PREVIEW_VALUE}
        and isinstance(raw.get(_PREVIEW_MARK), dict)
        and raw[_PREVIEW_MARK].get("preview_only") is True
    ):
        totals = raw[_PREVIEW_MARK].get("preview_totals") or {}
        return (
            raw[_PREVIEW_VALUE],
            True,
            {str(key): int(value) for key, value in totals.items()},
        )
    return raw, False, {}


def output_page(
    output: Any, path: str | None, *, limit: int, offset: int
) -> dict[str, Any]:
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


# Stored previews and the read-time helper cut lists at the same length.
PREVIEW_LIST_CAP = 100


def output_preview(output: Any, *, cap: int = PREVIEW_LIST_CAP) -> Any:
    return output_preview_with_truncated(output, cap=cap)[0]


def output_preview_with_truncated(
    output: Any,
    *,
    cap: int = PREVIEW_LIST_CAP,
    totals: Mapping[str, int] | None = None,
) -> tuple[Any, bool]:
    """Cut lists for a response and report a cut from this pass or from storage.

    ``totals`` holds original lengths recorded when the value was stored
    already clipped. A length above ``cap`` means that store-time cut happened.
    """
    preview, truncated = _cut(output, cap)
    if not truncated and totals:
        truncated = any(int(length) > cap for length in totals.values())
    return preview, truncated


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
    running = [
        item for item in store.list_executions(job_id) if item.status == "running"
    ]
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
