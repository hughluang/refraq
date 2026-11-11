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


class _Store:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.online: str | None = "4"
        self.busy: str | None = "0.25"
        self.modes: list[dict] = []
        self.queue: list[dict] = []
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
            return _Response(_matrix(self.modes))
        if query == ONLINE_QUERY:
            return _Response(_vector(self.online))
        if query == BUSY_QUERY:
            return _Response(_vector(self.busy))
        raise AssertionError(query)


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
    assert set(body["tiles"]) == {"cpu"}
    assert set(body["charts"]) == {"cpu_modes", "run_queue"}
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
    assert body["charts"] == {"cpu_modes": [], "run_queue": []}


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
