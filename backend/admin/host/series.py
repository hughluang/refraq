"""Map Prometheus CPU series into the host read."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from backend.admin.host.errors import HostSeriesUnavailable
from backend.admin.host.prometheus import query_instant, query_range
from backend.admin.host.schemas import (
    ChartsOut,
    CpuModeOut,
    CpuTileOut,
    HostReadOut,
    HostSpan,
    SampleOut,
    TilesOut,
)
from backend.core.time import format_instant, utc_now

# Bounded query windows. Retained matches the store time-retention limit.
SPAN_SECONDS: dict[HostSpan, int] = {
    "hour": 3600,
    "day": 86400,
    "retained": 1_296_000,
}

ONLINE_QUERY = 'count(last_over_time(node_cpu_seconds_total{mode="idle"}[60s]))'
BUSY_QUERY = (
    '(sum(rate(node_cpu_seconds_total{mode!~"idle|iowait|guest|guest_nice"}[120s]))'
    " / "
    'sum(rate(node_cpu_seconds_total{mode!~"guest|guest_nice"}[120s])))'
    " and "
    "count(last_over_time(node_cpu_seconds_total[60s]))"
)
MODE_QUERY = "rate(node_cpu_seconds_total[120s])"
QUEUE_QUERY = "node_procs_running"


def step_seconds(window: int) -> int:
    """Whole seconds. Dividing by 719 keeps both inclusive endpoints at or under 720."""
    return max(30, (window + 718) // 719)


def read_host(span: HostSpan) -> HostReadOut:
    window = SPAN_SECONDS[span]
    step = step_seconds(window)
    end = utc_now().replace(microsecond=0)
    end_unix = int(end.timestamp())
    start_unix = end_unix - window
    instants = list(range(start_unix, end_unix + 1, step))
    allowed = set(instants)

    online = _count(query_instant(ONLINE_QUERY, time=end_unix))
    busy = _scalar(query_instant(BUSY_QUERY, time=end_unix))
    modes = _modes(query_range(MODE_QUERY, start=start_unix, end=end_unix, step=step), allowed)
    queue = _queue(query_range(QUEUE_QUERY, start=start_unix, end=end_unix, step=step), allowed)
    trimmed = _trim(instants, [*modes.values(), queue])
    if trimmed is None:
        charts = ChartsOut(cpu_modes=[], run_queue=[])
        response_start = start_unix
    else:
        charts = ChartsOut(
            cpu_modes=[
                CpuModeOut(mode=mode, samples=_samples(trimmed, values))
                for mode, values in modes.items()
                if any(ts in values for ts in trimmed)
            ],
            run_queue=_samples(trimmed, queue) if any(ts in queue for ts in trimmed) else [],
        )
        response_start = trimmed[0]
    return HostReadOut(
        span=span,
        start=_instant(response_start),
        end=format_instant(end),
        step_seconds=step,
        tiles=TilesOut(cpu=CpuTileOut(online_count=online, busy_share=busy)),
        charts=charts,
    )


def _result(body: dict) -> list:
    data = body.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("result"), list):
        raise HostSeriesUnavailable()
    return data["result"]


def _finite(raw: object) -> float | None:
    try:
        number = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _scalar(body: dict) -> float | None:
    result = _result(body)
    if not result:
        return None
    value = result[0].get("value") if isinstance(result[0], dict) else None
    if not isinstance(value, list) or len(value) < 2:
        return None
    return _finite(value[1])


def _count(body: dict) -> int | None:
    number = _scalar(body)
    if number is None:
        return None
    return int(round(number))


def _points(values: object, allowed: set[int]) -> dict[int, float]:
    parsed: dict[int, float] = {}
    if not isinstance(values, list):
        return parsed
    for pair in values:
        if not isinstance(pair, list) or len(pair) < 2:
            continue
        number = _finite(pair[1])
        if number is None:
            continue
        try:
            ts = int(round(float(pair[0])))
        except (TypeError, ValueError):
            continue
        if ts in allowed:
            parsed[ts] = number
    return parsed


def _modes(body: dict, allowed: set[int]) -> dict[str, dict[int, float]]:
    modes: dict[str, dict[int, float]] = {}
    for item in _result(body):
        if not isinstance(item, dict):
            continue
        metric = item.get("metric")
        mode = metric.get("mode") if isinstance(metric, dict) else None
        if not isinstance(mode, str) or not mode:
            continue
        points = _points(item.get("values"), allowed)
        if mode not in modes:
            modes[mode] = {}
        modes[mode].update(points)
    return modes


def _queue(body: dict, allowed: set[int]) -> dict[int, float]:
    queue: dict[int, float] = {}
    for item in _result(body):
        if not isinstance(item, dict):
            continue
        for ts, value in _points(item.get("values"), allowed).items():
            queue.setdefault(ts, value)
    return queue


def _trim(instants: list[int], series: list[dict[int, float]]) -> list[int] | None:
    occupied = [ts for ts in instants if any(ts in item for item in series)]
    if not occupied:
        return None
    first = occupied[0]
    return [ts for ts in instants if ts >= first]


def _samples(instants: list[int], values: dict[int, float]) -> list[SampleOut]:
    return [
        SampleOut(t=_instant(ts), v=values.get(ts))
        for ts in instants
    ]


def _instant(ts: int) -> str:
    return format_instant(datetime.fromtimestamp(ts, UTC))
