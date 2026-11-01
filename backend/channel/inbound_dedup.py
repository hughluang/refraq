"""One dedup record per channel, path, and event id.

A repeat inside the window receives the first response, or a refusal while
that run has not answered. Hit counts live beside the records so a retry
storm does not insert one row per repeat, and so purging a record does not
reset the count.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from backend.channel.models import InboundDedupHitRow, InboundDedupRow
from backend.core.config import get_settings
from backend.core.db import session_scope

__all__ = [
    "DedupReplay",
    "get_inbound_dedup_store",
    "reset_inbound_dedup_store",
]


@dataclass(frozen=True, slots=True)
class DedupReplay:
    status: int
    headers: dict[str, str]
    body: Any


_Admission = DedupReplay | Literal["in_flight", "reserved"]


def _snapshot(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _headers(value: Mapping[str, Any]) -> dict[str, str]:
    return {str(key): str(item) for key, item in value.items()}


def _stored_replay(
    status: int | None, headers: Mapping[str, Any], body: Any
) -> DedupReplay:
    # `answer` writes an int status before it flips the row to answered.
    return DedupReplay(cast(int, status), _headers(headers), _snapshot(body))


@dataclass
class _MemoryRow:
    channel_id: str
    path: str
    event_id: str
    state: str
    status_code: int | None
    headers: dict[str, str]
    body: Any
    received_at: datetime
    expires_at: datetime
    job_id: str | None


class MemoryInboundDedupStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str], _MemoryRow] = {}
        self._hits: dict[str, int] = {}
        self._lock = threading.Lock()

    def admit(
        self,
        *,
        channel_id: str,
        path: str,
        event_id: str,
        received_at: datetime,
        expires_at: datetime,
    ) -> _Admission:
        key = (channel_id, path, event_id)
        with self._lock:
            row = self._rows.get(key)
            if row is not None and row.expires_at > received_at:
                if row.state == "answered":
                    self._hits[channel_id] = self._hits.get(channel_id, 0) + 1
                    return _stored_replay(row.status_code, row.headers, row.body)
                return "in_flight"
            self._rows[key] = _MemoryRow(
                channel_id=channel_id,
                path=path,
                event_id=event_id,
                state="in_flight",
                status_code=None,
                headers={},
                body=None,
                received_at=received_at,
                expires_at=expires_at,
                job_id=None,
            )
            return "reserved"

    def attach_job(
        self, *, channel_id: str, path: str, event_id: str, job_id: str
    ) -> None:
        with self._lock:
            row = self._rows.get((channel_id, path, event_id))
            if row is None or row.state != "in_flight" or row.job_id is not None:
                return
            row.job_id = job_id

    def abandon(self, *, channel_id: str, path: str, event_id: str) -> None:
        key = (channel_id, path, event_id)
        with self._lock:
            row = self._rows.get(key)
            if row is None or row.state != "in_flight" or row.job_id is not None:
                return
            del self._rows[key]

    def answer(
        self,
        *,
        channel_id: str,
        path: str,
        event_id: str,
        job_id: str,
        status: int,
        headers: dict[str, str],
        body: Any,
    ) -> bool:
        with self._lock:
            row = self._rows.get((channel_id, path, event_id))
            if row is None or row.state != "in_flight" or row.job_id != job_id:
                return False
            row.state = "answered"
            row.status_code = status
            row.headers = _headers(headers)
            row.body = _snapshot(body)
            return True

    def release_unanswered(self, job_id: str) -> None:
        with self._lock:
            doomed = [
                key
                for key, row in self._rows.items()
                if row.job_id == job_id and row.state == "in_flight"
            ]
            for key in doomed:
                del self._rows[key]

    def delete_expired(self, now: datetime) -> int:
        with self._lock:
            doomed = [
                key for key, row in self._rows.items() if row.expires_at <= now
            ]
            for key in doomed:
                del self._rows[key]
        return len(doomed)

    def hit_count(self, channel_id: str) -> int:
        with self._lock:
            return self._hits.get(channel_id, 0)


class SqlInboundDedupStore:
    def admit(
        self,
        *,
        channel_id: str,
        path: str,
        event_id: str,
        received_at: datetime,
        expires_at: datetime,
    ) -> _Admission:
        try:
            return self._admit(
                channel_id=channel_id,
                path=path,
                event_id=event_id,
                received_at=received_at,
                expires_at=expires_at,
            )
        except IntegrityError:
            return self._admit(
                channel_id=channel_id,
                path=path,
                event_id=event_id,
                received_at=received_at,
                expires_at=expires_at,
            )

    def _admit(
        self,
        *,
        channel_id: str,
        path: str,
        event_id: str,
        received_at: datetime,
        expires_at: datetime,
    ) -> _Admission:
        with session_scope() as session:
            row = session.scalar(
                select(InboundDedupRow)
                .where(
                    InboundDedupRow.channel_id == channel_id,
                    InboundDedupRow.path == path,
                    InboundDedupRow.event_id == event_id,
                )
                .with_for_update()
            )
            if row is not None and row.expires_at > received_at:
                if row.state == "answered":
                    self._increment_hit(session, channel_id)
                    return _stored_replay(row.status_code, row.headers, row.body)
                return "in_flight"
            if row is None:
                session.add(
                    InboundDedupRow(
                        channel_id=channel_id,
                        path=path,
                        event_id=event_id,
                        state="in_flight",
                        status_code=None,
                        headers={},
                        body=None,
                        received_at=received_at,
                        expires_at=expires_at,
                        job_id=None,
                    )
                )
                session.flush()
                return "reserved"
            row.state = "in_flight"
            row.status_code = None
            row.headers = {}
            row.body = None
            row.received_at = received_at
            row.expires_at = expires_at
            row.job_id = None
            return "reserved"

    def attach_job(
        self, *, channel_id: str, path: str, event_id: str, job_id: str
    ) -> None:
        with session_scope() as session:
            session.execute(
                update(InboundDedupRow)
                .where(
                    InboundDedupRow.channel_id == channel_id,
                    InboundDedupRow.path == path,
                    InboundDedupRow.event_id == event_id,
                    InboundDedupRow.state == "in_flight",
                    InboundDedupRow.job_id.is_(None),
                )
                .values(job_id=job_id)
            )

    def abandon(self, *, channel_id: str, path: str, event_id: str) -> None:
        with session_scope() as session:
            session.execute(
                delete(InboundDedupRow).where(
                    InboundDedupRow.channel_id == channel_id,
                    InboundDedupRow.path == path,
                    InboundDedupRow.event_id == event_id,
                    InboundDedupRow.state == "in_flight",
                    InboundDedupRow.job_id.is_(None),
                )
            )

    def answer(
        self,
        *,
        channel_id: str,
        path: str,
        event_id: str,
        job_id: str,
        status: int,
        headers: dict[str, str],
        body: Any,
    ) -> bool:
        with session_scope() as session:
            row = session.scalar(
                select(InboundDedupRow)
                .where(
                    InboundDedupRow.channel_id == channel_id,
                    InboundDedupRow.path == path,
                    InboundDedupRow.event_id == event_id,
                )
                .with_for_update()
            )
            if row is None or row.state != "in_flight" or row.job_id != job_id:
                return False
            row.state = "answered"
            row.status_code = status
            row.headers = _headers(headers)
            row.body = _snapshot(body)
            return True

    def release_unanswered(self, job_id: str) -> None:
        with session_scope() as session:
            session.execute(
                delete(InboundDedupRow).where(
                    InboundDedupRow.job_id == job_id,
                    InboundDedupRow.state == "in_flight",
                )
            )

    def delete_expired(self, now: datetime) -> int:
        with session_scope() as session:
            result = session.execute(
                delete(InboundDedupRow).where(InboundDedupRow.expires_at <= now)
            )
            return int(result.rowcount or 0)

    def hit_count(self, channel_id: str) -> int:
        with session_scope() as session:
            value = session.scalar(
                select(InboundDedupHitRow.hit_count).where(
                    InboundDedupHitRow.channel_id == channel_id
                )
            )
            return int(value or 0)

    def _increment_hit(self, session: Any, channel_id: str) -> None:
        session.execute(
            pg_insert(InboundDedupHitRow)
            .values(channel_id=channel_id, hit_count=1)
            .on_conflict_do_update(
                index_elements=["channel_id"],
                set_={"hit_count": InboundDedupHitRow.hit_count + 1},
            )
        )


_memory: MemoryInboundDedupStore | None = None
_lock = threading.Lock()


def get_inbound_dedup_store() -> MemoryInboundDedupStore | SqlInboundDedupStore:
    if get_settings().store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryInboundDedupStore()
            return _memory
    return SqlInboundDedupStore()


def reset_inbound_dedup_store() -> None:
    global _memory
    with _lock:
        _memory = None
