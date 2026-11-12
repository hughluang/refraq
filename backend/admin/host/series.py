"""Map Prometheus host series into the host read."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import httpx

from backend.admin.host.errors import HostSeriesUnavailable
from backend.admin.host.prometheus import PrometheusRead
from backend.admin.host.schemas import (
    ChartsOut,
    CpuModeOut,
    CpuTileOut,
    DiskChartOut,
    FilesystemChartOut,
    PostgresChartOut,
    PressureOut,
    PressureSideOut,
    FilesystemTileOut,
    HostReadOut,
    HostSpan,
    MemoryTileOut,
    PostgresTileOut,
    SampleOut,
    ServiceChartOut,
    SwapTileOut,
    TilesOut,
)
from backend.core.config import get_settings
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
MODE_QUERY = "avg by (mode) (rate(node_cpu_seconds_total[120s]))"
QUEUE_QUERY = "node_procs_running"
MEMORY_TOTAL_QUERY = "last_over_time(node_memory_MemTotal_bytes[60s])"
MEMORY_AVAILABLE_QUERY = "last_over_time(node_memory_MemAvailable_bytes[60s])"
SWAP_TOTAL_QUERY = "last_over_time(node_memory_SwapTotal_bytes[60s])"
SWAP_FREE_QUERY = "last_over_time(node_memory_SwapFree_bytes[60s])"
FILESYSTEM_SIZE_QUERY = "last_over_time(node_filesystem_size_bytes[60s])"
FILESYSTEM_AVAIL_QUERY = "last_over_time(node_filesystem_avail_bytes[60s])"
FILESYSTEM_INODES_QUERY = "last_over_time(node_filesystem_files_free[60s])"
FILESYSTEM_AVAIL_RANGE_QUERY = "node_filesystem_avail_bytes"
DISK_BUSY_QUERY = "rate(node_disk_io_time_seconds_total[120s])"
DISK_QUEUE_QUERY = "rate(node_disk_io_time_weighted_seconds_total[120s])"
PRESSURE_QUERIES: dict[tuple[str, str], str] = {
    ("cpu", "waiting"): "rate(node_pressure_cpu_waiting_seconds_total[120s])",
    ("cpu", "stalled"): "rate(node_pressure_cpu_stalled_seconds_total[120s])",
    ("memory", "waiting"): "rate(node_pressure_memory_waiting_seconds_total[120s])",
    ("memory", "stalled"): "rate(node_pressure_memory_stalled_seconds_total[120s])",
    ("io", "waiting"): "rate(node_pressure_io_waiting_seconds_total[120s])",
    ("io", "stalled"): "rate(node_pressure_io_stalled_seconds_total[120s])",
}
POSTGRES_DATA_MOUNT = "/var/lib/postgresql"
BACKENDS_TILE_QUERY = "last_over_time(pg_stat_database_numbackends[60s])"
MAX_CONNECTIONS_QUERY = "last_over_time(pg_settings_max_connections[60s])"
BACKENDS_RANGE_QUERY = "pg_stat_database_numbackends"
IDLE_QUERY = 'pg_stat_activity_count{state="idle in transaction"}'
IDLE_ABORTED_QUERY = 'pg_stat_activity_count{state="idle in transaction (aborted)"}'
TEMP_FILES_QUERY = "pg_stat_database_temp_files"
TEMP_BYTES_QUERY = "pg_stat_database_temp_bytes"
CHECKPOINT_QUERIES = {
    "checkpoint_timed": "pg_stat_checkpointer_num_timed_total",
    "checkpoint_requested": "pg_stat_checkpointer_num_requested_total",
    "checkpoint_write_time": "pg_stat_checkpointer_write_time_total",
    "checkpoint_sync_time": "pg_stat_checkpointer_sync_time_total",
    "checkpoint_buffers_written": "pg_stat_checkpointer_buffers_written_total",
}
SERVICE_NAMES = (
    "postgres",
    "redis",
    "api",
    "worker",
    "beat",
    "mcp",
    "entity-mcp",
    "web",
)
SERVICE_LABEL = "container_label_com_docker_compose_service"
_SERVICE_SELECTOR = SERVICE_LABEL + '=~"' + "|".join(SERVICE_NAMES) + '"'


def _service_cpu_query(rate_window: int) -> str:
    return (
        "sum by ("
        + SERVICE_LABEL
        + ") (rate(container_cpu_usage_seconds_total{"
        + _SERVICE_SELECTOR
        + "}["
        + str(rate_window)
        + "s]))"
    )


def _service_memory_query() -> str:
    return (
        "sum by ("
        + SERVICE_LABEL
        + ") (container_memory_working_set_bytes{"
        + _SERVICE_SELECTOR
        + "})"
    )


def step_seconds(window: int) -> int:
    """Whole seconds. Dividing by 719 keeps both inclusive endpoints at or under 720."""
    return max(30, (window + 718) // 719)


def read_host(span: HostSpan) -> HostReadOut:
    base_url = get_settings().refraq_prometheus_url
    with httpx.Client(
        timeout=5.0,
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
    ) as client:
        return _read_host(span, PrometheusRead(client, base_url))


def _read_host(span: HostSpan, store: PrometheusRead) -> HostReadOut:
    query_instant = store.query_instant
    query_range = store.query_range
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
    filesystems = _filesystem_ranges(
        query_range(FILESYSTEM_AVAIL_RANGE_QUERY, start=start_unix, end=end_unix, step=step),
        allowed,
    )
    disk_busy = _grouped(
        query_range(DISK_BUSY_QUERY, start=start_unix, end=end_unix, step=step),
        allowed,
        "device",
    )
    disk_queue = _grouped(
        query_range(DISK_QUEUE_QUERY, start=start_unix, end=end_unix, step=step),
        allowed,
        "device",
    )
    pressure = {
        key: _queue(query_range(query, start=start_unix, end=end_unix, step=step), allowed)
        for key, query in PRESSURE_QUERIES.items()
    }
    postgres_series = {
        "backends": _summed(
            query_range(BACKENDS_RANGE_QUERY, start=start_unix, end=end_unix, step=step),
            allowed,
        ),
        "idle_in_transaction": _summed(
            query_range(IDLE_QUERY, start=start_unix, end=end_unix, step=step),
            allowed,
        ),
        "idle_in_transaction_aborted": _summed(
            query_range(IDLE_ABORTED_QUERY, start=start_unix, end=end_unix, step=step),
            allowed,
        ),
        **{
            name: _queue(query_range(query, start=start_unix, end=end_unix, step=step), allowed)
            for name, query in CHECKPOINT_QUERIES.items()
        },
        "temp_files": _summed(
            query_range(TEMP_FILES_QUERY, start=start_unix, end=end_unix, step=step),
            allowed,
        ),
        "temp_bytes": _summed(
            query_range(TEMP_BYTES_QUERY, start=start_unix, end=end_unix, step=step),
            allowed,
        ),
    }
    rate_window = max(step, 120)
    service_cpu = _by_service(
        query_range(
            _service_cpu_query(rate_window),
            start=start_unix,
            end=end_unix,
            step=step,
        ),
        allowed,
    )
    service_memory = _by_service(
        query_range(
            _service_memory_query(),
            start=start_unix,
            end=end_unix,
            step=step,
        ),
        allowed,
    )
    service_cpu_seconds = {
        name: {ts: value * step for ts, value in points.items()}
        for name, points in service_cpu.items()
    }
    trimmed = _trim(
        instants,
        [
            *modes.values(),
            queue,
            *[values for _key, values in filesystems],
            *[values for _name, values in disk_busy],
            *[values for _name, values in disk_queue],
            *pressure.values(),
            *postgres_series.values(),
            *service_cpu_seconds.values(),
            *service_memory.values(),
        ],
    )
    chart_instants = trimmed if trimmed is not None else []
    postgres = _postgres_charts(chart_instants, postgres_series)
    services = _service_charts(
        instants if trimmed is None else trimmed,
        service_cpu_seconds,
        service_memory,
    )
    if trimmed is None:
        charts = ChartsOut(
            cpu_modes=[],
            run_queue=[],
            filesystems=[],
            disks=[],
            pressure=_pressure(instants, pressure),
            postgres=postgres,
            services=services,
        )
        response_start = start_unix
    else:
        charts = ChartsOut(
            cpu_modes=[
                CpuModeOut(mode=mode, samples=_samples(trimmed, values))
                for mode, values in modes.items()
                if any(ts in values for ts in trimmed)
            ],
            run_queue=_samples(trimmed, queue) if any(ts in queue for ts in trimmed) else [],
            filesystems=_filesystem_charts(trimmed, filesystems),
            disks=_disk_charts(trimmed, disk_busy, disk_queue),
            pressure=_pressure(trimmed, pressure),
            postgres=postgres,
            services=services,
        )
        response_start = trimmed[0]
    return HostReadOut(
        span=span,
        start=_instant(response_start),
        end=format_instant(end),
        step_seconds=step,
        tiles=TilesOut(
            cpu=CpuTileOut(online_count=online, busy_share=busy),
            memory=_memory(end_unix, store),
            swap=_swap(end_unix, store),
            filesystems=_filesystems(end_unix, store),
            postgres=_postgres_tiles(end_unix, store),
        ),
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


def _by_service(body: dict, allowed: set[int]) -> dict[str, dict[int, float]]:
    known = set(SERVICE_NAMES)
    found: dict[str, dict[int, float]] = {}
    for item in _result(body):
        if not isinstance(item, dict):
            continue
        metric = item.get("metric")
        if not isinstance(metric, dict):
            continue
        name = metric.get(SERVICE_LABEL)
        if not isinstance(name, str) or name not in known:
            continue
        slot = found.get(name)
        if slot is None:
            slot = {}
            found[name] = slot
        for ts, value in _points(item.get("values"), allowed).items():
            slot[ts] = slot.get(ts, 0.0) + value
    return found


def _service_charts(
    instants: list[int],
    cpu_seconds: dict[str, dict[int, float]],
    memory: dict[str, dict[int, float]],
) -> list[ServiceChartOut]:
    return [
        ServiceChartOut(
            service=name,
            cpu_seconds=_samples(instants, cpu_seconds.get(name, {})),
            memory_bytes=_samples(instants, memory.get(name, {})),
        )
        for name in SERVICE_NAMES
    ]


def _postgres_charts(
    instants: list[int], series: dict[str, dict[int, float]]
) -> PostgresChartOut:
    return PostgresChartOut.model_validate(
        {name: _aligned(instants, values) for name, values in series.items()}
    )


def _postgres_tiles(end_unix: int, store: PrometheusRead) -> PostgresTileOut:
    query_instant = store.query_instant
    return PostgresTileOut(
        backends=_summed_instant(query_instant(BACKENDS_TILE_QUERY, time=end_unix)),
        max_connections=_scalar(query_instant(MAX_CONNECTIONS_QUERY, time=end_unix)),
    )


def _summed_instant(body: dict) -> float | None:
    rows = _labeled_values(body)
    if not rows:
        return None
    return sum(value for _labels, value in rows)


def _summed(body: dict, allowed: set[int]) -> dict[int, float]:
    totals: dict[int, float] = {}
    for item in _result(body):
        if not isinstance(item, dict):
            continue
        for ts, value in _points(item.get("values"), allowed).items():
            totals[ts] = totals.get(ts, 0.0) + value
    return totals


def _memory(end_unix: int, store: PrometheusRead) -> MemoryTileOut:
    query_instant = store.query_instant
    total = _scalar(query_instant(MEMORY_TOTAL_QUERY, time=end_unix))
    available = _scalar(query_instant(MEMORY_AVAILABLE_QUERY, time=end_unix))
    used = None if total is None or available is None else total - available
    return MemoryTileOut(used_bytes=used, total_bytes=total)


def _swap(end_unix: int, store: PrometheusRead) -> SwapTileOut:
    query_instant = store.query_instant
    total = _scalar(query_instant(SWAP_TOTAL_QUERY, time=end_unix))
    free = _scalar(query_instant(SWAP_FREE_QUERY, time=end_unix))
    used = None if total is None or free is None else total - free
    return SwapTileOut(used_bytes=used, total_bytes=total)


def _filesystems(end_unix: int, store: PrometheusRead) -> list[FilesystemTileOut]:
    query_instant = store.query_instant
    sizes = _labeled_values(query_instant(FILESYSTEM_SIZE_QUERY, time=end_unix))
    available = _labeled_values(query_instant(FILESYSTEM_AVAIL_QUERY, time=end_unix))
    inodes = _labeled_values(query_instant(FILESYSTEM_INODES_QUERY, time=end_unix))
    order: list[tuple[str, str]] = []
    size_by: dict[tuple[str, str], float] = {}
    avail_by: dict[tuple[str, str], float] = {}
    inode_by: dict[tuple[str, str], float] = {}
    _collect_filesystems(sizes, size_by, order)
    _collect_filesystems(available, avail_by, order)
    _collect_filesystems(inodes, inode_by, None)
    tiles: list[FilesystemTileOut] = []
    for key in order:
        total = size_by.get(key)
        free_bytes = avail_by.get(key)
        used = None if total is None or free_bytes is None else total - free_bytes
        share = None if used is None or not total else used / total
        tiles.append(
            FilesystemTileOut(
                mount=key[0],
                type=key[1],
                used_bytes=used,
                total_bytes=total,
                used_share=share,
                free_inodes=inode_by.get(key),
            )
        )
    return tiles


def _collect_filesystems(
    rows: list[tuple[dict[str, str], float]],
    dest: dict[tuple[str, str], float],
    order: list[tuple[str, str]] | None,
) -> None:
    for labels, number in rows:
        mount = labels.get("mountpoint")
        fstype = labels.get("fstype")
        if not mount or not fstype or mount == POSTGRES_DATA_MOUNT:
            continue
        key = (mount, fstype)
        if key in dest:
            continue
        dest[key] = number
        if order is not None and key not in order:
            order.append(key)


def _filesystem_ranges(
    body: dict, allowed: set[int]
) -> list[tuple[tuple[str, str], dict[int, float]]]:
    order: list[tuple[str, str]] = []
    found: dict[tuple[str, str], dict[int, float]] = {}
    for item in _result(body):
        if not isinstance(item, dict):
            continue
        metric = item.get("metric")
        if not isinstance(metric, dict):
            continue
        mount = metric.get("mountpoint")
        fstype = metric.get("fstype")
        if (
            not isinstance(mount, str)
            or not isinstance(fstype, str)
            or not mount
            or not fstype
            or mount == POSTGRES_DATA_MOUNT
        ):
            continue
        key = (mount, fstype)
        points = _points(item.get("values"), allowed)
        slot = found.get(key)
        if slot is None:
            if not points:
                continue
            slot = {}
            found[key] = slot
            order.append(key)
        for ts, value in points.items():
            slot.setdefault(ts, value)
    return [(key, found[key]) for key in order]


def _filesystem_charts(
    instants: list[int],
    series: list[tuple[tuple[str, str], dict[int, float]]],
) -> list[FilesystemChartOut]:
    charts: list[FilesystemChartOut] = []
    for key, values in series:
        available = _samples(instants, values)
        charts.append(
            FilesystemChartOut(
                mount=key[0],
                type=key[1],
                available=available,
                delta=_delta(available),
            )
        )
    return charts


def _grouped(
    body: dict, allowed: set[int], label: str
) -> list[tuple[str, dict[int, float]]]:
    order: list[str] = []
    found: dict[str, dict[int, float]] = {}
    for item in _result(body):
        if not isinstance(item, dict):
            continue
        metric = item.get("metric")
        if not isinstance(metric, dict):
            continue
        name = metric.get(label)
        if not isinstance(name, str) or not name:
            continue
        points = _points(item.get("values"), allowed)
        slot = found.get(name)
        if slot is None:
            if not points:
                continue
            slot = {}
            found[name] = slot
            order.append(name)
        for ts, value in points.items():
            slot.setdefault(ts, value)
    return [(name, found[name]) for name in order]


def _disk_charts(
    instants: list[int],
    busy: list[tuple[str, dict[int, float]]],
    queue: list[tuple[str, dict[int, float]]],
) -> list[DiskChartOut]:
    order: list[str] = []
    for name, _values in [*busy, *queue]:
        if name not in order:
            order.append(name)
    busy_by = dict(busy)
    queue_by = dict(queue)
    charts: list[DiskChartOut] = []
    for name in order:
        charts.append(
            DiskChartOut(
                device=name,
                busy_share=_aligned(instants, busy_by.get(name, {})),
                queue_length=_aligned(instants, queue_by.get(name, {})),
            )
        )
    return charts


def _pressure(
    instants: list[int],
    points: dict[tuple[str, str], dict[int, float]],
) -> PressureOut:
    def side(family: str) -> PressureSideOut:
        return PressureSideOut(
            waiting=_aligned(instants, points[(family, "waiting")]),
            stalled=_aligned(instants, points[(family, "stalled")]),
        )

    return PressureOut(cpu=side("cpu"), memory=side("memory"), io=side("io"))


def _aligned(instants: list[int], values: dict[int, float]) -> list[SampleOut]:
    if not any(ts in values for ts in instants):
        return []
    return _samples(instants, values)


def _delta(samples: list[SampleOut]) -> list[SampleOut]:
    derived: list[SampleOut] = []
    previous: float | None = None
    for index, sample in enumerate(samples):
        value = None
        if index > 0 and previous is not None and sample.v is not None:
            value = sample.v - previous
        derived.append(SampleOut(t=sample.t, v=value))
        previous = sample.v
    return derived


def _labeled_values(body: dict) -> list[tuple[dict[str, str], float]]:
    rows: list[tuple[dict[str, str], float]] = []
    for item in _result(body):
        if not isinstance(item, dict):
            continue
        metric = item.get("metric")
        value = item.get("value")
        if not isinstance(metric, dict) or not isinstance(value, list) or len(value) < 2:
            continue
        number = _finite(value[1])
        if number is None:
            continue
        labels = {str(key): label for key, label in metric.items() if isinstance(label, str)}
        rows.append((labels, number))
    return rows


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
