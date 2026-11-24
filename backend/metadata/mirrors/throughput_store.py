"""Compact eligible payload-byte intervals without inventing measurements."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from math import ceil

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.db import Base
from backend.core.time import format_instant, parse_instant

RETENTION = timedelta(hours=25)
COMPACTION_SECONDS = 30
METRICS = (("received", "captured_bytes"), ("committed", "committed_bytes"))


class ThroughputRow(Base):
    __tablename__ = "source_mirror_throughput"
    __table_args__ = (
        Index("ix_mirror_throughput_scope_time", "source_id", "bucket_at"),
        Index("ix_mirror_throughput_mirror_time", "mirror_id", "bucket_at"),
        Index("ix_mirror_throughput_time", "bucket_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mirror_id: Mapped[str] = mapped_column(String(64), ForeignKey("source_mirrors.id", ondelete="CASCADE"), nullable=False)
    capture_generation: Mapped[str] = mapped_column(String(128), nullable=False)
    generation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    authority: Mapped[dict] = mapped_column(JSON, nullable=False)
    bucket_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_bytes: Mapped[int | None] = mapped_column(BigInteger)
    received_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    received_intervals: Mapped[list] = mapped_column(JSON, nullable=False)
    received_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_oldest: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_newest: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_bytes: Mapped[int | None] = mapped_column(BigInteger)
    committed_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    committed_intervals: Mapped[list] = mapped_column(JSON, nullable=False)
    committed_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_oldest: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_newest: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def aware(value):
    # SQLite's test adapter loses timezone metadata; all persisted times are UTC.
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def new_bin(source_id, authority, sample):
    bucket = datetime.fromtimestamp(ceil(sample.interval_end.timestamp() / COMPACTION_SECONDS) * COMPACTION_SECONDS, UTC)
    lineage = [source_id, sample.mirror_id, sample.capture_generation, sample.generation_id, authority, bucket.isoformat()]
    result = dict(id=sha256(json.dumps(lineage, sort_keys=True).encode()).hexdigest(), source_id=source_id,
                  mirror_id=sample.mirror_id, capture_generation=sample.capture_generation,
                  generation_id=sample.generation_id, authority=authority, bucket_at=bucket)
    for metric, _ in METRICS:
        result.update({metric + "_bytes": None, metric + "_seconds": 0.0, metric + "_intervals": [],
                       **{metric + "_" + name: None for name in ("start", "end", "oldest", "newest")}})
    return result


def overlaps(intervals, sample):
    return any(parse_instant(start) < sample.interval_end and parse_instant(end) > sample.interval_start
               for start, end in intervals)


def add_interval(row, metric, value, sample):
    """Only disjoint intervals contribute; zero remains an observed measurement."""
    row[metric + "_bytes"] = (row[metric + "_bytes"] or 0) + value
    row[metric + "_seconds"] += (sample.interval_end - sample.interval_start).total_seconds()
    intervals = [(parse_instant(start), parse_instant(end)) for start, end in row[metric + "_intervals"]]
    intervals.append((sample.interval_start, sample.interval_end))
    merged = []
    for start, end in sorted(intervals):
        if merged and merged[-1][1] == start:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    row[metric + "_intervals"] = [[format_instant(start, timespec="microseconds"), format_instant(end, timespec="microseconds")]
                                 for start, end in merged]
    for name, value, combine in (("start", sample.interval_start, min), ("end", sample.interval_end, max),
                                 ("oldest", sample.observed_at, min), ("newest", sample.observed_at, max)):
        previous = aware(row[metric + "_" + name])
        row[metric + "_" + name] = combine(previous, value) if previous is not None else value


def row_value(row):
    return {column.name: getattr(row, column.name) for column in ThroughputRow.__table__.columns}


def aggregate_rates(rows, *, start, end):
    """Match the SQL adapter's per-Mirror averages over 24 chart buckets."""
    step = (end - start) / 24
    grouped = defaultdict(list)
    for row in rows:
        grouped[ceil((aware(row["bucket_at"]) - start) / step) - 1].append(row)
    result = {}
    for index, bucket in grouped.items():
        point = {}
        for metric, _ in METRICS:
            measured = [row for row in bucket if row[metric + "_bytes"] is not None]
            mirrors = defaultdict(lambda: [0, 0.0])
            for row in measured:
                total = mirrors[row["mirror_id"]]
                total[0] += row[metric + "_bytes"]
                total[1] += row[metric + "_seconds"]
            point[metric + "_value"] = sum(count / seconds / 1_000_000 for count, seconds in mirrors.values()) if mirrors else None
            point[metric + "_sampled"] = len(mirrors)
            point[metric + "_seconds"] = sum(seconds for _, seconds in mirrors.values())
            for field, aggregate in (("start", min), ("end", max), ("oldest", min), ("newest", max)):
                point[metric + "_" + field] = aggregate((aware(row[metric + "_" + field]) for row in measured), default=None)
        result[index] = point
    return result
