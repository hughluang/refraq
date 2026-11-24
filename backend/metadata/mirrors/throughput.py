"""Historical measured CDC payload rates for the current Operations scope."""

from datetime import UTC, datetime, timedelta
from math import floor
from typing import Literal

from pydantic import Field

from backend.core.time import Instant, format_instant, utc_now
from backend.metadata.mirrors.errors import MirrorError
from backend.metadata.mirrors.schemas import StrictModel
from backend.metadata.mirrors.throughput_store import COMPACTION_SECONDS, aware


class ThroughputRate(StrictModel):
    value: float | None
    sampled: int = Field(ge=0)
    missing: int = Field(ge=0)
    interval_start: Instant | None
    interval_end: Instant | None
    oldest_observation: Instant | None
    newest_observation: Instant | None
    measured_seconds: float = Field(ge=0)


class ThroughputPoint(StrictModel):
    at: Instant
    bucket_start: Instant
    received: ThroughputRate
    committed: ThroughputRate


class ThroughputResponse(StrictModel):
    observed_at: Instant
    window_start: Instant
    window_end: Instant
    hours: Literal[1, 6, 24]
    unit: Literal["MB/s"]
    mirror_count: int
    source_count: int
    points: list[ThroughputPoint]


def _rate(row, metric, mirror_count):
    result = dict(value=row.get(metric + "_value"), sampled=row.get(metric + "_sampled", 0),
                  missing=mirror_count - row.get(metric + "_sampled", 0), measured_seconds=row.get(metric + "_seconds", 0))
    for field, column in (("interval_start", "start"), ("interval_end", "end"),
                           ("oldest_observation", "oldest"), ("newest_observation", "newest")):
        value = row.get(metric + "_" + column)
        result[field] = format_instant(aware(value), timespec="microseconds") if value is not None else None
    return result


def read_throughput(*, store, read_scope, source_id=None, runtime_id=None, hours=6, now=None):
    if hours not in (1, 6, 24):
        raise ValueError("Unsupported throughput window")
    now = now or utc_now()
    mirrors, bindings = read_scope()
    source_ids = {mirror["source_id"] for mirror in mirrors}
    if source_id is not None and source_id not in source_ids:
        raise MirrorError("MIRROR_NOT_FOUND", 404)
    scope = [mirror for mirror in mirrors if (source_id is None or mirror["source_id"] == source_id)
             and (runtime_id is None or (bindings.get(mirror["source_id"], {}).get("runtime_instance_id") or "unassigned") == runtime_id)]
    # Align chart boundaries with compacted observation bins. The current open
    # half-minute is omitted rather than presented as a complete measurement.
    end = datetime.fromtimestamp(floor(now.timestamp() / COMPACTION_SECONDS) * COMPACTION_SECONDS, UTC)
    start = end - timedelta(hours=hours)
    step = (end - start) / 24
    mirror_ids = {mirror["id"] for mirror in scope}
    aggregates = store.throughput_rates(mirror_ids, start=start, end=end)
    points = []
    for index in range(24):
        rates = {metric: _rate(aggregates.get(index, {}), metric, len(scope)) for metric in ("received", "committed")}
        points.append(dict(at=format_instant(start + step * (index + 1)), bucket_start=format_instant(start + step * index), **rates))
    return dict(observed_at=format_instant(now, timespec="microseconds"), window_start=format_instant(start),
                window_end=format_instant(end), hours=hours, unit="MB/s", mirror_count=len(scope),
                source_count=len({mirror["source_id"] for mirror in scope}), points=points)
