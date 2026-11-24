"""Bounded diagnostics history and independently written latest observations."""

from copy import deepcopy
from threading import RLock

from sqlalchemy import Integer, JSON, String, cast, delete, extract, func, select, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.db import Base
from backend.metadata.mirrors.throughput_store import (
    METRICS, RETENTION, ThroughputRow, add_interval, aggregate_rates, aware, new_bin, overlaps, row_value,
)


class DiagnosticRow(Base):
    __tablename__ = "source_mirror_diagnostics"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)


class DiagnosticStore:
    def __init__(self, *, memory, transaction):
        self.memory = memory
        self.transaction = transaction
        self.values = {}
        self.throughput = {}
        self.lock = RLock()

    def read(self, kind, scope_id):
        key = f"{kind}:{scope_id}"
        if self.memory:
            with self.lock:
                return deepcopy(self.values.get(key))
        with self.transaction() as session:
            return session.scalar(select(DiagnosticRow.value).where(DiagnosticRow.id == key))

    def all(self, kind):
        if self.memory:
            with self.lock:
                prefix = kind + ":"
                return {key[len(prefix):]: deepcopy(value) for key, value in self.values.items() if key.startswith(prefix)}
        with self.transaction() as session:
            return dict(session.execute(select(DiagnosticRow.scope_id, DiagnosticRow.value).where(DiagnosticRow.kind == kind)).all())

    def update(self, kind, scope_id, change):
        """Serialize only this telemetry key; never acquire Source or target locks."""
        key = f"{kind}:{scope_id}"
        if self.memory:
            with self.lock:
                value = change(deepcopy(self.values.get(key)))
                self.values[key] = deepcopy(value)
                return value
        with self.transaction() as session:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "diagnostics:" + key})
            row = session.get(DiagnosticRow, key)
            value = change(deepcopy(row.value) if row else None)
            if row:
                row.value = value
            else:
                session.add(DiagnosticRow(id=key, kind=kind, scope_id=scope_id, value=value))
            return value

    def record_throughput(self, source_id, authority, sample, *, now):
        """Keep 25 hours of byte evidence, compacted into bounded 30-second bins.

        Interval durations retain gaps; merging never claims continuous coverage.
        Historical provenance remains attached across authority and publication changes.
        """
        metrics = [(name, getattr(sample, field)) for name, field in METRICS if getattr(sample, field) is not None]
        if not metrics or sample.interval_end <= now - RETENTION:
            return
        incoming = new_bin(source_id, authority, sample)
        cutoff = now - RETENTION
        if self.memory:
            with self.lock:
                history = {key: value for key, value in self.throughput.get(sample.mirror_id, {}).items()
                           if value["bucket_at"] >= cutoff}
                prior = list(history.values())
                value = deepcopy(history.get(incoming["id"], incoming))
                for metric, count in metrics:
                    if not any(overlaps(row[metric + "_intervals"], sample) for row in prior):
                        add_interval(value, metric, count, sample)
                if any(value[name + "_bytes"] is not None for name, _ in METRICS):
                    history[value["id"]] = value
                self.throughput[sample.mirror_id] = history
            return
        with self.transaction() as session:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                                {"key": "throughput:" + sample.mirror_id})
            session.execute(delete(ThroughputRow).where(ThroughputRow.mirror_id == sample.mirror_id,
                                                       ThroughputRow.bucket_at < cutoff))
            row = session.get(ThroughputRow, incoming["id"])
            value = row_value(row) if row is not None else incoming
            for metric, count in metrics:
                start, end = getattr(ThroughputRow, metric + "_start"), getattr(ThroughputRow, metric + "_end")
                candidates = session.scalars(select(getattr(ThroughputRow, metric + "_intervals")).where(
                    ThroughputRow.mirror_id == sample.mirror_id, ThroughputRow.bucket_at >= sample.interval_start,
                    start < sample.interval_end,
                    end > sample.interval_start))
                if not any(overlaps(intervals, sample) for intervals in candidates):
                    add_interval(value, metric, count, sample)
            if row is not None:
                for key, item in value.items():
                    setattr(row, key, item)
            elif any(value[name + "_bytes"] is not None for name, _ in METRICS):
                session.add(ThroughputRow(**value))

    def throughput_rates(self, mirror_ids, *, start, end):
        """Aggregate fleet history into at most 24 chart points.

        Average each Mirror over its observed duration before summing its rate.
        Thus a long-sampled table cannot suppress another table's measured rate.
        """
        if not mirror_ids:
            return {}
        if self.memory:
            with self.lock:
                rows = [value for mirror_id in mirror_ids for value in self.throughput.get(mirror_id, {}).values()
                        if start < aware(value["bucket_at"]) <= end]
                return aggregate_rates(rows, start=start, end=end)
        seconds = (end - start).total_seconds() / 24
        point = cast(func.floor((extract("epoch", ThroughputRow.bucket_at) - start.timestamp() - 1) / seconds), Integer).label("point")
        columns = [point, ThroughputRow.mirror_id]
        for metric, _ in METRICS:
            for field in ("bytes", "seconds"):
                columns.append(func.sum(getattr(ThroughputRow, metric + "_" + field)).label(metric + "_" + field))
            for field, aggregate in (("start", func.min), ("end", func.max), ("oldest", func.min), ("newest", func.max)):
                columns.append(aggregate(getattr(ThroughputRow, metric + "_" + field)).label(metric + "_" + field))
        per_mirror = select(*columns).where(ThroughputRow.mirror_id.in_(mirror_ids), ThroughputRow.bucket_at > start,
                                           ThroughputRow.bucket_at <= end).group_by(point, ThroughputRow.mirror_id).subquery()
        columns = [per_mirror.c.point]
        for metric, _ in METRICS:
            count = per_mirror.c[metric + "_bytes"]
            duration = per_mirror.c[metric + "_seconds"]
            columns.extend([func.sum(count / func.nullif(duration, 0) / 1_000_000).label(metric + "_value"),
                            func.count(count).label(metric + "_sampled"), func.sum(duration).label(metric + "_seconds")])
            for field, aggregate in (("start", func.min), ("end", func.max), ("oldest", func.min), ("newest", func.max)):
                columns.append(aggregate(per_mirror.c[metric + "_" + field]).label(metric + "_" + field))
        with self.transaction() as session:
            return {row["point"]: dict(row) for row in session.execute(select(*columns).group_by(per_mirror.c.point)).mappings()}
