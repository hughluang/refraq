"""Host read: permission, span, CPU series, and an unreachable store."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")

from backend.admin.permissions import (  # noqa: E402
    ALL_PERMISSIONS,
    GRANTING_PERMISSIONS,
    PERMISSION_DESCRIPTIONS,
)
from backend.admin.role_store import MemoryRoleStore, reset_role_store  # noqa: E402
from backend.admin.roles import (  # noqa: E402
    OPERATOR_DEFAULT_PERMISSIONS,
    create_role,
    effective_permissions,
    seed_roles,
)
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.session_store import (  # noqa: E402
    MemorySessionStore,
    reset_session_store,
)
from backend.admin.user_store import MemoryUserStore, reset_user_store  # noqa: E402
from backend.core.config import get_settings, reset_settings_cache  # noqa: E402
from backend.core.errors import CODE_REQUEST_INVALID  # noqa: E402
from backend.core.time import FixedClock, format_instant, reset_clock, set_clock  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tests.problem import assert_problem  # noqa: E402

END = datetime(2026, 11, 12, tzinfo=UTC)
END_TEXT = "2026-11-12T00:00:00Z"
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
PRESSURE_CPU_WAITING_QUERY = "rate(node_pressure_cpu_waiting_seconds_total[120s])"
PRESSURE_CPU_STALLED_QUERY = "rate(node_pressure_cpu_stalled_seconds_total[120s])"
PRESSURE_MEMORY_WAITING_QUERY = "rate(node_pressure_memory_waiting_seconds_total[120s])"
PRESSURE_MEMORY_STALLED_QUERY = "rate(node_pressure_memory_stalled_seconds_total[120s])"
PRESSURE_IO_WAITING_QUERY = "rate(node_pressure_io_waiting_seconds_total[120s])"
PRESSURE_IO_STALLED_QUERY = "rate(node_pressure_io_stalled_seconds_total[120s])"
BACKENDS_TILE_QUERY = "last_over_time(pg_stat_database_numbackends[60s])"
MAX_CONNECTIONS_QUERY = "last_over_time(pg_settings_max_connections[60s])"
BACKENDS_RANGE_QUERY = "pg_stat_database_numbackends"
IDLE_QUERY = 'pg_stat_activity_count{state="idle in transaction"}'
IDLE_ABORTED_QUERY = 'pg_stat_activity_count{state="idle in transaction (aborted)"}'
CHECKPOINT_TIMED_QUERY = "pg_stat_checkpointer_num_timed_total"
CHECKPOINT_REQUESTED_QUERY = "pg_stat_checkpointer_num_requested_total"
CHECKPOINT_WRITE_QUERY = "pg_stat_checkpointer_write_time_total"
CHECKPOINT_SYNC_QUERY = "pg_stat_checkpointer_sync_time_total"
CHECKPOINT_BUFFERS_QUERY = "pg_stat_checkpointer_buffers_written_total"
TEMP_FILES_QUERY = "pg_stat_database_temp_files"
TEMP_BYTES_QUERY = "pg_stat_database_temp_bytes"
SERVICE_LABEL = "container_label_com_docker_compose_service"
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
MAINTAINER_KEYS = [
    "console:access",
    "sources:read",
    "metadata:read",
    "catalog:sample",
    "query:run",
    "metadata:write",
    "sources:write",
    "jobs:run",
]


class _Response:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


def _vector(raw: str | None) -> dict:
    if raw is None:
        result: list[dict] = []
    else:
        result = [{"metric": {}, "value": [0, raw]}]
    return {"status": "success", "data": {"resultType": "vector", "result": result}}


def _matrix(rows: list[dict]) -> dict:
    return {"status": "success", "data": {"resultType": "matrix", "result": rows}}


def _series(labels: dict[str, str], points: list[tuple[int, str]]) -> dict:
    return {
        "metric": labels,
        "values": [[ts, value] for ts, value in points],
    }


def _instant(labels: dict[str, str], raw: str) -> dict:
    return {"metric": labels, "value": [0, raw]}


def _vector_rows(rows: list[dict]) -> dict:
    return {"status": "success", "data": {"resultType": "vector", "result": rows}}


class _Store:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.online: str | None = "4"
        self.busy: str | None = "0.25"
        self.modes: list[dict] = []
        self.queue: list[dict] = []
        self.instant: dict[str, list[dict]] = {}
        self.ranges: dict[str, list[dict]] = {}
        self.fail: Exception | None = None
        self.status_code = 200

    def __call__(self, url: str, params: dict | None = None, timeout: float | None = None):
        if self.fail is not None:
            raise self.fail
        query = str((params or {}).get("query", ""))
        self.calls.append((url, {key: str(value) for key, value in (params or {}).items()}))
        if self.status_code != 200:
            return _Response({"status": "error", "data": {"result": []}}, self.status_code)
        if "query_range" in url:
            if query == QUEUE_QUERY:
                return _Response(_matrix(self.queue))
            if query == MODE_QUERY:
                return _Response(_matrix(self.modes))
            return _Response(_matrix(self.ranges.get(query, [])))
        if query == ONLINE_QUERY:
            return _Response(_vector(self.online))
        if query == BUSY_QUERY:
            return _Response(_vector(self.busy))
        return _Response(_vector_rows(self.instant.get(query, [])))


def _unix(moment: datetime) -> int:
    return int(moment.timestamp())


@pytest.fixture
def store_bundle():
    reset_user_store()
    reset_role_store()
    reset_session_store()
    role_store = MemoryRoleStore()
    seed_roles(role_store)
    user_store = MemoryUserStore()
    super_admin = role_store.get_by_key("super_admin")
    operator = role_store.get_by_key("operator")
    assert super_admin is not None and operator is not None
    user_store.create_user(
        account="root",
        display_name="Root",
        password_hash=hash_password("s3cret"),
        role_id=super_admin.id,
    )
    user_store.create_user(
        account="op",
        display_name="Operator",
        password_hash=hash_password("op-pass"),
        role_id=operator.id,
    )
    session_store = MemorySessionStore()
    yield user_store, role_store, session_store
    app.dependency_overrides.clear()
    reset_user_store()
    reset_role_store()
    reset_session_store()


@pytest.fixture
def client(store_bundle):
    user_store, role_store, session_store = store_bundle
    from backend.admin.role_store import get_role_store
    from backend.admin.session_store import get_session_store
    from backend.admin.user_store import get_user_store

    app.dependency_overrides[get_user_store] = lambda: user_store
    app.dependency_overrides[get_role_store] = lambda: role_store
    app.dependency_overrides[get_session_store] = lambda: session_store
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def frozen_end():
    set_clock(FixedClock(END))
    yield END
    reset_clock()


@pytest.fixture
def prometheus(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REFRAQ_PROMETHEUS_URL", "http://prometheus:9090")
    reset_settings_cache()
    store = _Store()
    monkeypatch.setattr("backend.admin.host.prometheus.httpx.get", store)
    yield store
    reset_settings_cache()


def _login(client: TestClient, account: str = "root", password: str = "s3cret") -> None:
    response = client.post("/auth/login", json={"account": account, "password": password})
    assert response.status_code == 200


def _user(store_bundle, account: str, permissions: list[str]) -> None:
    user_store, role_store, _sessions = store_bundle
    role = create_role(
        role_store,
        key=account,
        name=account,
        permissions=permissions,
    )
    user_store.create_user(
        account=account,
        display_name=account,
        password_hash=hash_password("s3cret"),
        role_id=role.id,
    )


def test_host_read_is_appended_after_inbound_credential_write() -> None:
    assert ALL_PERMISSIONS[-2:] == ("inbound_credential:write", "host:read")
    assert PERMISSION_DESCRIPTIONS["host:read"] == "View host and Postgres occupancy"
    assert "host:read" not in OPERATOR_DEFAULT_PERMISSIONS
    assert "host:read" not in GRANTING_PERMISSIONS
    roles = MemoryRoleStore()
    seed_roles(roles)
    super_admin = roles.get_by_key("super_admin")
    operator = roles.get_by_key("operator")
    assert super_admin is not None and operator is not None
    assert "host:read" not in super_admin.permissions
    assert "host:read" in effective_permissions(super_admin)
    assert "host:read" not in effective_permissions(operator)


def test_prometheus_url_defaults_without_being_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REFRAQ_PROMETHEUS_URL", raising=False)
    reset_settings_cache()
    assert get_settings().refraq_prometheus_url == "http://prometheus:9090"
    reset_settings_cache()


def test_host_read_requires_a_session_or_pat(client: TestClient) -> None:
    response = client.get("/host")
    assert_problem(response, status=401, code="AUTH_UNAUTHENTICATED")


def test_operator_cannot_read_host(client: TestClient) -> None:
    _login(client, "op", "op-pass")
    response = client.get("/host")
    assert_problem(response, status=403, code="AUTH_FORBIDDEN")


def test_jobs_run_does_not_grant_host_read(client: TestClient, store_bundle) -> None:
    _user(store_bundle, "runner", ["console:access", "jobs:run"])
    _login(client, "runner")
    response = client.get("/host")
    assert_problem(response, status=403, code="AUTH_FORBIDDEN")


def test_source_maintainer_keys_do_not_grant_host_read(
    client: TestClient, store_bundle
) -> None:
    _user(store_bundle, "maintainer", MAINTAINER_KEYS)
    _login(client, "maintainer")
    response = client.get("/host")
    assert_problem(response, status=403, code="AUTH_FORBIDDEN")


def test_unknown_span_is_rejected(client: TestClient) -> None:
    _login(client)
    response = client.get("/host", params={"span": "week"})
    assert_problem(response, status=422, code=CODE_REQUEST_INVALID)


def test_pat_with_host_read_and_no_session_can_read(
    client: TestClient, store_bundle, frozen_end: datetime, prometheus: _Store
) -> None:
    _user(store_bundle, "reader", ["console:access", "tokens:write", "host:read"])
    _login(client, "reader")
    created = client.post(
        "/tokens",
        json={
            "name": "host",
            "expires_at": format_instant(END.replace(year=2027)),
        },
    )
    assert created.status_code == 201, created.text
    secret = created.json()["secret"]
    client.cookies.clear()
    end_unix = _unix(frozen_end)
    prometheus.modes = [_series({"mode": "user"}, [(end_unix - 86400, "0.5")])]
    prometheus.queue = [_series({}, [(end_unix - 86400, "2")])]
    response = client.get("/host", headers={"Authorization": f"Bearer {secret}"})
    assert response.status_code == 200, response.text
    assert response.json()["span"] == "day"


@pytest.mark.parametrize(
    ("span", "step", "window", "start_text", "points"),
    [
        ("hour", 30, 3600, "2026-11-11T23:00:00Z", 121),
        ("day", 121, 86400, "2026-11-11T00:00:00Z", 715),
        ("retained", 1803, 1_296_000, "2026-10-28T00:00:00Z", 719),
    ],
)
def test_span_sets_step_and_keeps_each_series_at_or_under_720_points(
    client: TestClient,
    frozen_end: datetime,
    prometheus: _Store,
    span: str,
    step: int,
    window: int,
    start_text: str,
    points: int,
) -> None:
    _login(client)
    end_unix = _unix(frozen_end)
    start_unix = end_unix - window
    prometheus.modes = [_series({"mode": "user"}, [(start_unix, "0.5")])]
    prometheus.queue = [_series({}, [(start_unix, "2")])]
    response = client.get("/host", params={"span": span})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["span"] == span
    assert body["start"] == start_text
    assert body["end"] == END_TEXT
    assert body["step_seconds"] == step
    assert "cpu" in body["tiles"]
    assert "cpu_modes" in body["charts"]
    assert "run_queue" in body["charts"]
    assert "entity_id" not in body
    assert "channel_id" not in body
    mode_samples = body["charts"]["cpu_modes"][0]["samples"]
    queue_samples = body["charts"]["run_queue"]
    assert body["charts"]["cpu_modes"][0]["mode"] == "user"
    assert len(mode_samples) == points
    assert len(queue_samples) == points
    assert points <= 720
    assert mode_samples[0] == {"t": start_text, "v": 0.5}
    assert mode_samples[1]["v"] is None
    assert queue_samples[0]["v"] == 2
    assert queue_samples[1]["v"] is None
    range_calls = [params for url, params in prometheus.calls if "query_range" in url]
    assert range_calls
    assert {params["step"] for params in range_calls} == {str(step)}
    assert {params["start"] for params in range_calls} == {str(start_unix)}
    assert {params["end"] for params in range_calls} == {str(end_unix)}
    assert {params["time"] for _url, params in prometheus.calls if "time" in params} == {
        str(end_unix)
    }
    queries = [params["query"] for _url, params in prometheus.calls]
    assert ONLINE_QUERY in queries
    assert BUSY_QUERY in queries
    assert MODE_QUERY in queries
    assert QUEUE_QUERY in queries
    assert all(url.startswith("http://prometheus:9090/api/v1/") for url, _params in prometheus.calls)


def test_omitted_span_is_the_last_24_hours(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 86400
    prometheus.modes = [_series({"mode": "user"}, [(start_unix, "0.5")])]
    prometheus.queue = [_series({}, [(start_unix, "2")])]
    response = client.get("/host")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["span"] == "day"
    assert body["start"] == "2026-11-11T00:00:00Z"
    assert body["end"] == END_TEXT
    assert body["step_seconds"] == 121


def test_cpu_tiles_and_modes_keep_guest_out_of_the_share(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 86400
    prometheus.modes = [
        _series({"mode": "user"}, [(start_unix, "0.5")]),
        _series({"mode": "guest"}, [(start_unix, "0.4")]),
        _series({"mode": "guest_nice"}, [(start_unix, "0.05")]),
        _series({"mode": "idle"}, [(start_unix, "0.8")]),
        _series({"mode": "iowait"}, [(start_unix, "0.05")]),
    ]
    prometheus.queue = [_series({}, [(start_unix, "2")])]
    response = client.get("/host", params={"span": "day"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tiles"]["cpu"] == {"online_count": 4, "busy_share": 0.25}
    assert [series["mode"] for series in body["charts"]["cpu_modes"]] == [
        "user",
        "guest",
        "guest_nice",
        "idle",
        "iowait",
    ]
    assert body["charts"]["run_queue"][0]["v"] == 2
    queries = [params["query"] for _url, params in prometheus.calls]
    assert MODE_QUERY in queries
    assert not any("node_load" in query for query in queries)
    assert not any(query.startswith("rate(") and "node_procs_running" in query for query in queries)


def test_tile_without_a_sample_in_60_seconds_is_null_not_zero(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 86400
    prometheus.online = None
    prometheus.busy = "NaN"
    prometheus.modes = [_series({"mode": "user"}, [(start_unix, "0.5")])]
    prometheus.queue = [_series({}, [(start_unix, "2")])]
    response = client.get("/host")
    assert response.status_code == 200, response.text
    tile = response.json()["tiles"]["cpu"]
    assert tile["online_count"] is None
    assert tile["busy_share"] is None
    assert response.json()["charts"]["cpu_modes"][0]["samples"][0]["v"] == 0.5


def test_empty_store_keeps_the_query_window(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    prometheus.online = None
    prometheus.busy = None
    response = client.get("/host", params={"span": "retained"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["span"] == "retained"
    assert body["start"] == "2026-10-28T00:00:00Z"
    assert body["end"] == END_TEXT
    assert body["step_seconds"] == 1803
    assert body["tiles"]["cpu"] == {"online_count": None, "busy_share": None}
    assert body["tiles"]["memory"] == {"used_bytes": None, "total_bytes": None}
    assert body["tiles"]["swap"] == {"used_bytes": None, "total_bytes": None}
    assert body["tiles"]["filesystems"] == []
    assert body["charts"]["cpu_modes"] == []
    assert body["charts"]["run_queue"] == []
    assert body["charts"]["filesystems"] == []
    assert body["charts"]["disks"] == []
    assert body["charts"]["pressure"] == {
        "cpu": {"waiting": [], "stalled": []},
        "memory": {"waiting": [], "stalled": []},
        "io": {"waiting": [], "stalled": []},
    }


def test_leading_gap_trims_start_without_changing_step(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    original = datetime(2026, 11, 11, tzinfo=UTC)
    trimmed = datetime(2026, 11, 11, 0, 4, 2, tzinfo=UTC)
    last = datetime(2026, 11, 11, 23, 59, 54, tzinfo=UTC)
    prometheus.modes = [
        _series(
            {"mode": "user"},
            [(_unix(trimmed), "0.5"), (_unix(last), "0.25")],
        )
    ]
    prometheus.queue = [_series({}, [(_unix(last), "2")])]
    response = client.get("/host", params={"span": "day"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["start"] == "2026-11-11T00:04:02Z"
    assert body["end"] == END_TEXT
    assert body["step_seconds"] == 121
    samples = body["charts"]["cpu_modes"][0]["samples"]
    queue = body["charts"]["run_queue"]
    assert len(samples) == 713
    assert len(queue) == 713
    assert samples[0] == {"t": "2026-11-11T00:04:02Z", "v": 0.5}
    assert samples[1]["v"] is None
    assert samples[-1] == {"t": "2026-11-11T23:59:54Z", "v": 0.25}
    assert queue[0]["v"] is None
    assert queue[-1]["v"] == 2
    range_calls = [params for url, params in prometheus.calls if "query_range" in url]
    assert {params["start"] for params in range_calls} == {str(_unix(original))}
    assert {params["step"] for params in range_calls} == {"121"}


def test_a_present_series_keeps_the_leading_window(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start = datetime(2026, 11, 11, tzinfo=UTC)
    last = datetime(2026, 11, 11, 23, 59, 54, tzinfo=UTC)
    prometheus.modes = [_series({"mode": "user"}, [(_unix(start), "0.5")])]
    prometheus.queue = [_series({}, [(_unix(last), "2")])]
    response = client.get("/host", params={"span": "day"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["start"] == "2026-11-11T00:00:00Z"
    assert body["step_seconds"] == 121
    assert body["charts"]["cpu_modes"][0]["samples"][0]["v"] == 0.5
    assert body["charts"]["run_queue"][0]["v"] is None
    assert body["charts"]["run_queue"][-1]["v"] == 2


def test_memory_tile_is_total_minus_available(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    prometheus.instant[MEMORY_TOTAL_QUERY] = [_instant({}, "1000")]
    prometheus.instant[MEMORY_AVAILABLE_QUERY] = [_instant({}, "400")]
    response = client.get("/host")
    assert response.status_code == 200, response.text
    assert response.json()["tiles"]["memory"] == {"used_bytes": 600, "total_bytes": 1000}
    queries = [params["query"] for _url, params in prometheus.calls]
    assert MEMORY_TOTAL_QUERY in queries
    assert MEMORY_AVAILABLE_QUERY in queries
    assert {params["time"] for url, params in prometheus.calls if params["query"] == MEMORY_TOTAL_QUERY} == {
        str(_unix(frozen_end))
    }


def test_memory_tile_stays_null_when_the_series_is_absent(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    response = client.get("/host")
    assert response.status_code == 200, response.text
    assert response.json()["tiles"]["memory"] == {"used_bytes": None, "total_bytes": None}
    queries = [params["query"] for _url, params in prometheus.calls]
    assert MEMORY_TOTAL_QUERY in queries
    assert MEMORY_AVAILABLE_QUERY in queries


def test_memory_used_stays_null_when_available_is_absent(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    prometheus.instant[MEMORY_TOTAL_QUERY] = [_instant({}, "1000")]
    response = client.get("/host")
    assert response.status_code == 200, response.text
    assert response.json()["tiles"]["memory"] == {"used_bytes": None, "total_bytes": 1000}
    assert frozen_end == END


def test_swap_tile_is_total_minus_free(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    prometheus.instant[SWAP_TOTAL_QUERY] = [_instant({}, "200")]
    prometheus.instant[SWAP_FREE_QUERY] = [_instant({}, "50")]
    response = client.get("/host")
    assert response.status_code == 200, response.text
    assert response.json()["tiles"]["swap"] == {"used_bytes": 150, "total_bytes": 200}
    queries = [params["query"] for _url, params in prometheus.calls]
    assert SWAP_TOTAL_QUERY in queries
    assert SWAP_FREE_QUERY in queries
    assert {params["time"] for _url, params in prometheus.calls if params["query"] == SWAP_TOTAL_QUERY} == {
        str(_unix(frozen_end))
    }


def test_swap_tile_keeps_zero_when_both_readings_are_zero(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    prometheus.instant[SWAP_TOTAL_QUERY] = [_instant({}, "0")]
    prometheus.instant[SWAP_FREE_QUERY] = [_instant({}, "0")]
    response = client.get("/host")
    assert response.status_code == 200, response.text
    assert response.json()["tiles"]["swap"] == {"used_bytes": 0, "total_bytes": 0}
    assert frozen_end == END


def test_swap_tile_stays_null_when_the_series_is_absent(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    response = client.get("/host")
    assert response.status_code == 200, response.text
    assert response.json()["tiles"]["swap"] == {"used_bytes": None, "total_bytes": None}
    queries = [params["query"] for _url, params in prometheus.calls]
    assert SWAP_TOTAL_QUERY in queries
    assert SWAP_FREE_QUERY in queries
    assert frozen_end == END


def test_filesystem_rows_follow_the_collector_mount_and_type(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    root = {"mountpoint": "/", "fstype": "ext4", "device": "/dev/sda1"}
    tmp = {"mountpoint": "/run", "fstype": "tmpfs", "device": "tmpfs"}
    data = {"mountpoint": "/data", "fstype": "xfs", "device": "/dev/sdc1"}
    prometheus.instant[FILESYSTEM_SIZE_QUERY] = [
        _instant(root, "1000"),
        _instant(tmp, "100"),
        _instant(data, "800"),
    ]
    prometheus.instant[FILESYSTEM_AVAIL_QUERY] = [
        _instant(root, "250"),
        _instant(tmp, "40"),
        _instant(data, "200"),
    ]
    prometheus.instant[FILESYSTEM_INODES_QUERY] = [
        _instant(root, "42"),
        _instant(tmp, "7"),
    ]
    response = client.get("/host")
    assert response.status_code == 200, response.text
    assert response.json()["tiles"]["filesystems"] == [
        {
            "mount": "/",
            "type": "ext4",
            "used_bytes": 750,
            "total_bytes": 1000,
            "used_share": 0.75,
            "free_inodes": 42,
        },
        {
            "mount": "/run",
            "type": "tmpfs",
            "used_bytes": 60,
            "total_bytes": 100,
            "used_share": 0.6,
            "free_inodes": 7,
        },
        {
            "mount": "/data",
            "type": "xfs",
            "used_bytes": 600,
            "total_bytes": 800,
            "used_share": 0.75,
            "free_inodes": None,
        },
    ]
    queries = [params["query"] for _url, params in prometheus.calls]
    assert FILESYSTEM_SIZE_QUERY in queries
    assert FILESYSTEM_AVAIL_QUERY in queries
    assert FILESYSTEM_INODES_QUERY in queries
    assert {
        params["time"]
        for _url, params in prometheus.calls
        if params["query"] == FILESYSTEM_SIZE_QUERY
    } == {str(_unix(frozen_end))}


def test_postgres_data_directory_is_not_a_host_filesystem(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    root = {"mountpoint": "/", "fstype": "ext4", "device": "/dev/sda1"}
    data = {"mountpoint": "/var/lib/postgresql", "fstype": "ext4", "device": "/dev/sdb1"}
    prometheus.instant[FILESYSTEM_SIZE_QUERY] = [
        _instant(root, "1000"),
        _instant(data, "99999"),
    ]
    prometheus.instant[FILESYSTEM_AVAIL_QUERY] = [
        _instant(root, "250"),
        _instant(data, "111"),
    ]
    response = client.get("/host")
    assert response.status_code == 200, response.text
    rows = response.json()["tiles"]["filesystems"]
    assert [row["mount"] for row in rows] == ["/"]
    assert rows[0]["used_bytes"] == 750
    assert frozen_end == END


def test_filesystem_charts_are_available_bytes_and_the_previous_sample_delta(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 86400
    root = {"mountpoint": "/", "fstype": "ext4", "device": "/dev/sda1"}
    logs = {"mountpoint": "/var", "fstype": "ext4", "device": "/dev/sda2"}
    data = {"mountpoint": "/var/lib/postgresql", "fstype": "ext4", "device": "/dev/sdb1"}
    prometheus.ranges[FILESYSTEM_AVAIL_RANGE_QUERY] = [
        _series(root, [(start_unix, "100"), (start_unix + 121, "80"), (start_unix + 242, "90")]),
        _series(logs, [(start_unix, "500"), (start_unix + 242, "480")]),
        _series(data, [(start_unix, "1")]),
    ]
    response = client.get("/host", params={"span": "day"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["start"] == "2026-11-11T00:00:00Z"
    charts = body["charts"]["filesystems"]
    assert [chart["mount"] for chart in charts] == ["/", "/var"]
    root_chart = charts[0]
    assert root_chart["type"] == "ext4"
    assert len(root_chart["available"]) == 715
    assert len(root_chart["available"]) <= 720
    assert len(root_chart["delta"]) == 715
    assert [sample["v"] for sample in root_chart["available"][:4]] == [100, 80, 90, None]
    assert [sample["v"] for sample in root_chart["delta"][:4]] == [None, -20, 10, None]
    assert root_chart["available"][0]["t"] == "2026-11-11T00:00:00Z"
    log_chart = charts[1]
    assert [sample["v"] for sample in log_chart["available"][:3]] == [500, None, 480]
    assert [sample["v"] for sample in log_chart["delta"][:3]] == [None, None, None]
    query_call = next(
        params for _url, params in prometheus.calls if params.get("query") == FILESYSTEM_AVAIL_RANGE_QUERY
    )
    assert query_call["start"] == str(start_unix)
    assert query_call["end"] == str(_unix(frozen_end))
    assert query_call["step"] == "121"
    assert "rate(" not in query_call["query"]


def test_filesystem_samples_keep_an_earlier_start(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    filesystem_at = datetime(2026, 11, 11, 0, 4, 2, tzinfo=UTC)
    cpu_at = datetime(2026, 11, 11, 0, 6, 3, tzinfo=UTC)
    prometheus.modes = [_series({"mode": "user"}, [(_unix(cpu_at), "0.5")])]
    prometheus.ranges[FILESYSTEM_AVAIL_RANGE_QUERY] = [
        _series({"mountpoint": "/", "fstype": "ext4"}, [(_unix(filesystem_at), "250")])
    ]
    response = client.get("/host", params={"span": "day"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["start"] == "2026-11-11T00:04:02Z"
    assert body["step_seconds"] == 121
    available = body["charts"]["filesystems"][0]["available"]
    assert available[0] == {"t": "2026-11-11T00:04:02Z", "v": 250}
    assert body["charts"]["filesystems"][0]["delta"][0]["v"] is None
    assert body["charts"]["cpu_modes"][0]["samples"][0]["v"] is None
    assert body["charts"]["cpu_modes"][0]["samples"][1]["v"] == 0.5
    assert frozen_end == END


def test_disk_charts_are_per_device_rates(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 3600
    prometheus.modes = [_series({"mode": "user"}, [(start_unix, "0.5")])]
    prometheus.ranges[DISK_BUSY_QUERY] = [
        _series({"device": "sda"}, [(start_unix, "0.2")]),
        _series({"device": "sdb"}, [(start_unix, "0.5")]),
    ]
    prometheus.ranges[DISK_QUEUE_QUERY] = [
        _series({"device": "sda"}, [(start_unix, "1.25")]),
        _series({"device": "sdb"}, [(start_unix, "4")]),
        _series({"device": "vdc"}, [(start_unix, "9")]),
    ]
    response = client.get("/host", params={"span": "hour"})
    assert response.status_code == 200, response.text
    disks = response.json()["charts"]["disks"]
    assert [disk["device"] for disk in disks] == ["sda", "sdb", "vdc"]
    assert len(disks[0]["busy_share"]) == 121
    assert len(disks[0]["busy_share"]) <= 720
    assert disks[0]["busy_share"][0]["v"] == 0.2
    assert disks[0]["busy_share"][1]["v"] is None
    assert disks[1]["busy_share"][0]["v"] == 0.5
    assert disks[0]["queue_length"][0]["v"] == 1.25
    assert disks[1]["queue_length"][0]["v"] == 4
    assert disks[2]["busy_share"] == []
    assert disks[2]["queue_length"][0]["v"] == 9
    queries = [params["query"] for _url, params in prometheus.calls]
    assert DISK_BUSY_QUERY in queries
    assert DISK_QUEUE_QUERY in queries
    assert not any("sum(" in query and "node_disk_" in query for query in queries)
    disk_steps = {
        params["step"]
        for _url, params in prometheus.calls
        if params.get("query") in {DISK_BUSY_QUERY, DISK_QUEUE_QUERY}
    }
    assert disk_steps == {"30"}


def test_missing_pressure_series_stays_empty(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 3600
    prometheus.modes = [_series({"mode": "user"}, [(start_unix, "0.5")])]
    prometheus.ranges[PRESSURE_CPU_WAITING_QUERY] = [_series({}, [(start_unix, "0.01")])]
    prometheus.ranges[PRESSURE_MEMORY_WAITING_QUERY] = [_series({}, [(start_unix, "0.02")])]
    prometheus.ranges[PRESSURE_MEMORY_STALLED_QUERY] = [_series({}, [(start_unix, "0")])]
    response = client.get("/host", params={"span": "hour"})
    assert response.status_code == 200, response.text
    pressure = response.json()["charts"]["pressure"]
    assert len(pressure["cpu"]["waiting"]) == 121
    assert len(pressure["cpu"]["waiting"]) <= 720
    assert pressure["cpu"]["waiting"][0]["v"] == 0.01
    assert pressure["cpu"]["waiting"][1]["v"] is None
    assert pressure["cpu"]["stalled"] == []
    assert pressure["memory"]["waiting"][0]["v"] == 0.02
    assert pressure["memory"]["stalled"][0]["v"] == 0
    assert pressure["io"] == {"waiting": [], "stalled": []}
    queries = [params["query"] for _url, params in prometheus.calls]
    assert PRESSURE_CPU_WAITING_QUERY in queries
    assert PRESSURE_CPU_STALLED_QUERY in queries
    assert PRESSURE_MEMORY_WAITING_QUERY in queries
    assert PRESSURE_MEMORY_STALLED_QUERY in queries
    assert PRESSURE_IO_WAITING_QUERY in queries
    assert PRESSURE_IO_STALLED_QUERY in queries
    assert {
        params["step"]
        for _url, params in prometheus.calls
        if params.get("query") == PRESSURE_CPU_STALLED_QUERY
    } == {"30"}


def test_connection_tile_sums_backends_against_max_connections(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    prometheus.instant[BACKENDS_TILE_QUERY] = [
        _instant({"datid": "1", "datname": "refraq"}, "3"),
        _instant({"datid": "2", "datname": "postgres"}, "4"),
    ]
    prometheus.instant[MAX_CONNECTIONS_QUERY] = [_instant({}, "100")]
    prometheus.instant["last_over_time(pg_settings_superuser_reserved_connections[60s])"] = [
        _instant({}, "3")
    ]
    response = client.get("/host")
    assert response.status_code == 200, response.text
    postgres = response.json()["tiles"]["postgres"]
    assert postgres["backends"] == 7
    assert postgres["max_connections"] == 100
    queries = [params["query"] for _url, params in prometheus.calls]
    assert BACKENDS_TILE_QUERY in queries
    assert MAX_CONNECTIONS_QUERY in queries
    assert not any("superuser_reserved" in query for query in queries)
    assert not any("rate(" in query and "pg_stat_database_numbackends" in query for query in queries)
    assert "entity_id" not in response.text
    assert "channel_id" not in response.text
    tile_times = {
        params["time"]
        for _url, params in prometheus.calls
        if params.get("query") in {BACKENDS_TILE_QUERY, MAX_CONNECTIONS_QUERY}
    }
    assert tile_times == {str(_unix(frozen_end))}


def test_postgres_tile_without_a_sample_is_null_and_a_recorded_zero_stays_zero(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    absent = client.get("/host")
    assert absent.status_code == 200, absent.text
    assert absent.json()["tiles"]["postgres"] == {"backends": None, "max_connections": None}

    prometheus.instant[BACKENDS_TILE_QUERY] = [_instant({"datname": "refraq"}, "0")]
    prometheus.instant[MAX_CONNECTIONS_QUERY] = [_instant({}, "0")]
    recorded = client.get("/host")
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["tiles"]["postgres"] == {"backends": 0, "max_connections": 0}
    assert frozen_end == END


def test_backends_chart_is_the_recorded_sum_over_the_span(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 3600
    prometheus.ranges[BACKENDS_RANGE_QUERY] = [
        _series({"datid": "1", "datname": "refraq"}, [(start_unix, "3"), (start_unix + 30, "5")]),
        _series({"datid": "2", "datname": "postgres"}, [(start_unix, "4"), (start_unix + 30, "6")]),
    ]
    response = client.get("/host", params={"span": "hour"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["start"] == "2026-11-11T23:00:00Z"
    assert body["step_seconds"] == 30
    samples = body["charts"]["postgres"]["backends"]
    assert len(samples) == 121
    assert len(samples) <= 720
    assert samples[0] == {"t": "2026-11-11T23:00:00Z", "v": 7}
    assert samples[1] == {"t": "2026-11-11T23:00:30Z", "v": 11}
    assert samples[2]["v"] is None
    query = next(
        params for _url, params in prometheus.calls if params.get("query") == BACKENDS_RANGE_QUERY
    )
    assert "rate(" not in query["query"]
    assert query["step"] == "30"
    assert query["start"] == str(start_unix)
    assert query["end"] == str(_unix(frozen_end))


def test_idle_in_transaction_charts_are_recorded_state_sums(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 3600
    prometheus.ranges[IDLE_QUERY] = [
        _series(
            {"datname": "refraq", "state": "idle in transaction"},
            [(start_unix, "2"), (start_unix + 30, "2")],
        ),
        _series(
            {"datname": "postgres", "state": "idle in transaction"},
            [(start_unix, "1"), (start_unix + 30, "2")],
        ),
    ]
    prometheus.ranges[IDLE_ABORTED_QUERY] = [
        _series(
            {"datname": "refraq", "state": "idle in transaction (aborted)"},
            [(start_unix + 30, "1")],
        )
    ]
    response = client.get("/host", params={"span": "hour"})
    assert response.status_code == 200, response.text
    postgres = response.json()["charts"]["postgres"]
    idle = postgres["idle_in_transaction"]
    aborted = postgres["idle_in_transaction_aborted"]
    assert len(idle) == 121
    assert len(idle) <= 720
    assert idle[0]["v"] == 3
    assert idle[1]["v"] == 4
    assert aborted[0]["v"] is None
    assert aborted[1]["v"] == 1
    queries = [params["query"] for _url, params in prometheus.calls]
    assert IDLE_QUERY in queries
    assert IDLE_ABORTED_QUERY in queries
    assert not any("rate(" in query and "pg_stat_activity_count" in query for query in queries)


def test_checkpoint_charts_are_recorded_counters(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 3600
    prometheus.ranges[CHECKPOINT_TIMED_QUERY] = [
        _series({}, [(start_unix, "11"), (start_unix + 30, "14")])
    ]
    prometheus.ranges[CHECKPOINT_REQUESTED_QUERY] = [
        _series({}, [(start_unix, "4"), (start_unix + 30, "4")])
    ]
    prometheus.ranges[CHECKPOINT_WRITE_QUERY] = [
        _series({}, [(start_unix, "2500.5"), (start_unix + 30, "2600.5")])
    ]
    prometheus.ranges[CHECKPOINT_SYNC_QUERY] = [
        _series({}, [(start_unix, "12.5"), (start_unix + 30, "12.5")])
    ]
    prometheus.ranges[CHECKPOINT_BUFFERS_QUERY] = [
        _series({}, [(start_unix, "80"), (start_unix + 30, "90")])
    ]
    response = client.get("/host", params={"span": "hour"})
    assert response.status_code == 200, response.text
    postgres = response.json()["charts"]["postgres"]
    timed = postgres["checkpoint_timed"]
    assert len(timed) == 121
    assert len(timed) <= 720
    assert timed[0]["v"] == 11
    assert timed[1]["v"] == 14
    assert postgres["checkpoint_requested"][0]["v"] == 4
    assert postgres["checkpoint_requested"][1]["v"] == 4
    assert postgres["checkpoint_write_time"][0]["v"] == 2500.5
    assert postgres["checkpoint_write_time"][1]["v"] == 2600.5
    assert postgres["checkpoint_sync_time"][0]["v"] == 12.5
    assert postgres["checkpoint_buffers_written"][0]["v"] == 80
    assert postgres["checkpoint_buffers_written"][1]["v"] == 90
    queries = [params["query"] for _url, params in prometheus.calls]
    for query in (
        CHECKPOINT_TIMED_QUERY,
        CHECKPOINT_REQUESTED_QUERY,
        CHECKPOINT_WRITE_QUERY,
        CHECKPOINT_SYNC_QUERY,
        CHECKPOINT_BUFFERS_QUERY,
    ):
        assert query in queries
        assert not query.startswith("rate(")
    assert frozen_end == END


def test_temporary_file_charts_are_recorded_sums(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 3600
    prometheus.ranges[TEMP_FILES_QUERY] = [
        _series({"datid": "1", "datname": "refraq"}, [(start_unix, "2"), (start_unix + 30, "2")]),
        _series({"datid": "2", "datname": "postgres"}, [(start_unix, "3"), (start_unix + 30, "4")]),
    ]
    prometheus.ranges[TEMP_BYTES_QUERY] = [
        _series({"datid": "1", "datname": "refraq"}, [(start_unix, "1000"), (start_unix + 30, "1000")]),
        _series({"datid": "2", "datname": "postgres"}, [(start_unix, "500"), (start_unix + 30, "800")]),
    ]
    response = client.get("/host", params={"span": "hour"})
    assert response.status_code == 200, response.text
    postgres = response.json()["charts"]["postgres"]
    files = postgres["temp_files"]
    payload = postgres["temp_bytes"]
    assert len(files) == 121
    assert len(files) <= 720
    assert len(payload) <= 720
    assert files[0]["v"] == 5
    assert files[1]["v"] == 6
    assert payload[0]["v"] == 1500
    assert payload[1]["v"] == 1800
    queries = [params["query"] for _url, params in prometheus.calls]
    assert TEMP_FILES_QUERY in queries
    assert TEMP_BYTES_QUERY in queries
    assert not any(
        "rate(" in query and "pg_stat_database_temp_" in query for query in queries
    )


def test_a_recorded_postgres_zero_stays_zero_and_a_missing_series_stays_empty(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 3600
    prometheus.ranges[CHECKPOINT_TIMED_QUERY] = [_series({}, [(start_unix, "0")])]
    response = client.get("/host", params={"span": "hour"})
    assert response.status_code == 200, response.text
    body = response.json()
    postgres = body["charts"]["postgres"]
    assert postgres["checkpoint_timed"][0]["v"] == 0
    assert postgres["checkpoint_requested"] == []
    assert postgres["checkpoint_write_time"] == []
    assert postgres["checkpoint_sync_time"] == []
    assert postgres["checkpoint_buffers_written"] == []
    assert postgres["idle_in_transaction"] == []
    assert postgres["idle_in_transaction_aborted"] == []
    assert postgres["temp_files"] == []
    assert postgres["temp_bytes"] == []
    assert postgres["backends"] == []
    assert body["tiles"]["cpu"] == {"online_count": 4, "busy_share": 0.25}
    assert "entity_id" not in response.text
    assert "channel_id" not in response.text
    assert frozen_end == END


def test_postgres_sample_keeps_an_earlier_start(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    postgres_at = datetime(2026, 11, 11, 0, 4, 2, tzinfo=UTC)
    cpu_at = datetime(2026, 11, 11, 0, 6, 3, tzinfo=UTC)
    prometheus.modes = [_series({"mode": "user"}, [(_unix(cpu_at), "0.5")])]
    prometheus.ranges[BACKENDS_RANGE_QUERY] = [
        _series({"datname": "refraq"}, [(_unix(postgres_at), "3")]),
        _series({"datname": "postgres"}, [(_unix(postgres_at), "4")]),
    ]
    response = client.get("/host", params={"span": "day"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["start"] == "2026-11-11T00:04:02Z"
    assert body["step_seconds"] == 121
    assert body["charts"]["postgres"]["backends"][0] == {
        "t": "2026-11-11T00:04:02Z",
        "v": 7,
    }
    assert body["charts"]["cpu_modes"][0]["samples"][0]["v"] is None
    assert body["charts"]["cpu_modes"][0]["samples"][1]["v"] == 0.5
    assert frozen_end == END


def test_added_readings_keep_the_cpu_keys(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 86400
    prometheus.modes = [_series({"mode": "user"}, [(start_unix, "0.5")])]
    prometheus.queue = [_series({}, [(start_unix, "2")])]
    response = client.get("/host", params={"span": "day"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) >= {"span", "start", "end", "step_seconds", "tiles", "charts"}
    assert "entity_id" not in response.text
    assert "channel_id" not in response.text
    assert set(body["tiles"]) == {"cpu", "memory", "swap", "filesystems", "postgres"}
    assert set(body["tiles"]["cpu"]) == {"online_count", "busy_share"}
    assert body["tiles"]["cpu"] == {"online_count": 4, "busy_share": 0.25}
    assert set(body["charts"]) == {
        "cpu_modes",
        "run_queue",
        "filesystems",
        "disks",
        "pressure",
        "postgres",
        "services",
    }
    assert [series["mode"] for series in body["charts"]["cpu_modes"]] == ["user"]
    assert len(body["charts"]["cpu_modes"][0]["samples"]) == 715
    assert len(body["charts"]["run_queue"]) <= 720
    assert body["charts"]["run_queue"][0]["v"] == 2


def test_service_charts_are_rate_then_sum_times_step_and_keep_gaps(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 3600
    label = SERVICE_LABEL
    prometheus.ranges[_service_cpu_query(120)] = [
        _series({label: "api"}, [(start_unix, "2"), (start_unix + 30, "1")]),
        _series({label: "api"}, [(start_unix, "1"), (start_unix + 30, "0")]),
        _series({label: "worker"}, [(start_unix, "4")]),
        _series({label: "beat"}, [(start_unix, "0"), (start_unix + 30, "0")]),
        _series({label: "ensure-entity-db"}, [(start_unix, "100")]),
    ]
    prometheus.ranges[_service_memory_query()] = [
        _series({label: "api"}, [(start_unix, "1000"), (start_unix + 30, "1100")]),
        _series({label: "api"}, [(start_unix, "500"), (start_unix + 30, "700")]),
        _series({label: "worker"}, [(start_unix, "200")]),
        _series({label: "redis"}, [(start_unix + 30, "64")]),
        _series({label: "beat"}, [(start_unix, "0")]),
        _series({label: "ensure-entity-db"}, [(start_unix, "99999")]),
    ]
    response = client.get("/host", params={"span": "hour"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["step_seconds"] == 30
    services = body["charts"]["services"]
    assert [row["service"] for row in services] == list(SERVICE_NAMES)
    assert "ensure-entity-db" not in response.text
    assert "entity_id" not in response.text
    assert "channel_id" not in response.text
    by_name = {row["service"]: row for row in services}
    api = by_name["api"]
    assert len(api["cpu_seconds"]) == 121
    assert len(api["cpu_seconds"]) <= 720
    assert len(api["memory_bytes"]) == 121
    assert api["cpu_seconds"][0] == {"t": "2026-11-11T23:00:00Z", "v": 90}
    assert api["cpu_seconds"][1] == {"t": "2026-11-11T23:00:30Z", "v": 30}
    assert api["cpu_seconds"][2]["v"] is None
    assert api["memory_bytes"][0]["v"] == 1500
    assert api["memory_bytes"][1]["v"] == 1800
    assert api["memory_bytes"][2]["v"] is None
    assert by_name["worker"]["cpu_seconds"][0]["v"] == 120
    assert by_name["worker"]["cpu_seconds"][1]["v"] is None
    assert by_name["worker"]["memory_bytes"][0]["v"] == 200
    assert by_name["worker"]["memory_bytes"][1]["v"] is None
    assert by_name["redis"]["cpu_seconds"][0]["v"] is None
    assert by_name["redis"]["cpu_seconds"][1]["v"] is None
    assert by_name["redis"]["memory_bytes"][0]["v"] is None
    assert by_name["redis"]["memory_bytes"][1]["v"] == 64
    assert by_name["beat"]["cpu_seconds"][0]["v"] == 0
    assert by_name["beat"]["memory_bytes"][0]["v"] == 0
    assert all(sample["v"] is None for sample in by_name["postgres"]["cpu_seconds"])
    assert all(sample["v"] is None for sample in by_name["postgres"]["memory_bytes"])
    assert all(sample["v"] is None for sample in by_name["mcp"]["cpu_seconds"])
    assert all(sample["v"] is None for sample in by_name["entity-mcp"]["memory_bytes"])
    assert all(sample["v"] is None for sample in by_name["web"]["cpu_seconds"])
    queries = [params["query"] for _url, params in prometheus.calls]
    cpu_query = _service_cpu_query(120)
    memory_query = _service_memory_query()
    assert cpu_query in queries
    assert memory_query in queries
    assert "rate(sum" not in cpu_query
    assert cpu_query.index("rate(") > cpu_query.index("sum by")
    assert "[120s]" in cpu_query
    assert "rate(" not in memory_query
    assert body["tiles"]["cpu"] == {"online_count": 4, "busy_share": 0.25}
    assert frozen_end == END


def test_empty_store_still_lists_the_eight_services_with_null_samples(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    prometheus.online = None
    prometheus.busy = None
    response = client.get("/host", params={"span": "hour"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["start"] == "2026-11-11T23:00:00Z"
    assert body["step_seconds"] == 30
    assert body["charts"]["cpu_modes"] == []
    assert body["charts"]["run_queue"] == []
    services = body["charts"]["services"]
    assert [row["service"] for row in services] == list(SERVICE_NAMES)
    assert "ensure-entity-db" not in response.text
    for row in services:
        assert len(row["cpu_seconds"]) == 121
        assert len(row["cpu_seconds"]) <= 720
        assert all(sample["v"] is None for sample in row["cpu_seconds"])
        assert all(sample["v"] is None for sample in row["memory_bytes"])
    assert frozen_end == END


def test_service_cpu_window_is_the_step_when_the_step_exceeds_120_seconds(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 86400
    prometheus.ranges[_service_cpu_query(121)] = [
        _series({SERVICE_LABEL: "api"}, [(start_unix, "2")])
    ]
    prometheus.ranges[_service_memory_query()] = [
        _series({SERVICE_LABEL: "api"}, [(start_unix, "10")])
    ]
    response = client.get("/host", params={"span": "day"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["step_seconds"] == 121
    api = next(row for row in body["charts"]["services"] if row["service"] == "api")
    assert len(api["cpu_seconds"]) == 715
    assert len(api["cpu_seconds"]) <= 720
    assert api["cpu_seconds"][0] == {"t": "2026-11-11T00:00:00Z", "v": 242}
    assert api["memory_bytes"][0]["v"] == 10
    assert api["memory_bytes"][1]["v"] is None
    queries = [params["query"] for _url, params in prometheus.calls]
    assert _service_cpu_query(121) in queries
    assert _service_cpu_query(120) not in queries
    assert "rate(" not in _service_memory_query()
    assert frozen_end == END


def test_a_service_sample_trims_the_leading_gap(
    client: TestClient, frozen_end: datetime, prometheus: _Store
) -> None:
    _login(client)
    start_unix = _unix(frozen_end) - 86400
    sample_at = start_unix + 121
    prometheus.ranges[_service_cpu_query(121)] = [
        _series({SERVICE_LABEL: "api"}, [(sample_at, "1")])
    ]
    response = client.get("/host", params={"span": "day"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["start"] == "2026-11-11T00:02:01Z"
    assert body["step_seconds"] == 121
    services = body["charts"]["services"]
    assert [row["service"] for row in services] == list(SERVICE_NAMES)
    api = next(row for row in services if row["service"] == "api")
    postgres = next(row for row in services if row["service"] == "postgres")
    assert len(api["cpu_seconds"]) == 714
    assert len(api["cpu_seconds"]) <= 720
    assert api["cpu_seconds"][0] == {"t": "2026-11-11T00:02:01Z", "v": 121}
    assert postgres["cpu_seconds"][0]["v"] is None
    assert postgres["memory_bytes"][0]["v"] is None
    assert body["charts"]["cpu_modes"] == []
    assert frozen_end == END


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("unreachable"), "status"],
)
def test_unreachable_store_is_unavailable_not_zeros(
    client: TestClient,
    frozen_end: datetime,
    prometheus: _Store,
    failure: object,
) -> None:
    _login(client)
    if failure == "status":
        prometheus.status_code = 500
    else:
        assert isinstance(failure, Exception)
        prometheus.fail = failure
    response = client.get("/host")
    assert_problem(response, status=503, code="HOST_SERIES_UNAVAILABLE")
    assert "retry-after" not in {key.lower() for key in response.headers}
    body = response.json()
    assert "tiles" not in body
    assert "charts" not in body
    assert body.get("online_count") is None
    assert frozen_end == END
