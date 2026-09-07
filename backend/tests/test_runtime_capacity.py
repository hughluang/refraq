"""Runtime capacity: load shed, admission share, /metrics."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.core.bulkhead import (
    ActorShareExceeded,
    CapacityExceeded,
    PeekBulkhead,
    get_peek_bulkhead,
    reset_peek_bulkhead,
)
from backend.core.admission import await_admitted
from backend.core.errors import (
    AdmissionActorLimitExceeded,
    AdmissionCapacityExceeded,
    PlatformCapacityExceeded,
    PlatformTimeout,
)
from backend.core.load_shed import LoadSheddingMiddleware
from backend.core.db import map_platform_db_error, reset_db_singletons, session_scope
from backend.core.runtime import (
    get_runtime_capacity,
    reset_runtime_capacity,
    set_process_role,
)
from backend.core.worker_runtime import init_parent_worker_runtime
from backend.main import app


def test_healthz_and_metrics_bypass_and_render() -> None:
    with TestClient(app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        body = metrics.text
        assert "refraq_http_inflight" in body
        assert "refraq_admission_slots_limit" in body
        assert "refraq_admission_actor_share_limit" in body
        assert "refraq_db_pool_size" in body


def test_peek_bulkhead_share_and_total() -> None:
    cabin = PeekBulkhead(slots=2, share=1)
    hold = threading.Event()

    def _block() -> str:
        hold.wait(timeout=2)
        return "ok"

    first = cabin.submit_nowait("u1", _block)
    with pytest.raises(ActorShareExceeded) as share:
        cabin.submit_nowait("u1", _block)
    assert share.value.limit == 1
    second = cabin.submit_nowait("u2", _block)
    with pytest.raises(CapacityExceeded) as full:
        cabin.submit_nowait("u3", _block)
    assert full.value.limit == 2
    hold.set()
    assert first.result(timeout=2) == "ok"
    assert second.result(timeout=2) == "ok"
    cabin.shutdown()


def test_await_admitted_maps_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFRAQ_ADMISSION_SLOTS", "2")
    monkeypatch.setenv("REFRAQ_ADMISSION_ACTOR_SHARE", "1")
    reset_runtime_capacity()
    reset_peek_bulkhead()
    hold = threading.Event()

    def _block() -> str:
        hold.wait(timeout=2)
        return "ok"

    async def _run() -> None:
        t1 = asyncio.create_task(await_admitted("user-a", _block))
        await asyncio.sleep(0.05)
        with pytest.raises(AdmissionActorLimitExceeded) as share:
            await await_admitted("user-a", lambda: "no")
        assert share.value.http_status == 429
        assert share.value.extra_headers()["Retry-After"] == "1"
        t2 = asyncio.create_task(await_admitted("user-b", _block))
        await asyncio.sleep(0.05)
        with pytest.raises(AdmissionCapacityExceeded) as cabin:
            await await_admitted("user-c", lambda: "no")
        assert cabin.value.http_status == 503
        hold.set()
        assert await t1 == "ok"
        assert await t2 == "ok"

    asyncio.run(_run())
    reset_peek_bulkhead()
    reset_runtime_capacity()


def test_load_shed_returns_problem_details(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFRAQ_HTTP_MAX_INFLIGHT", "1")
    reset_runtime_capacity()
    started = threading.Event()
    release = threading.Event()

    async def inner(scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            return
        path = scope.get("path") or ""
        if path == "/metrics":
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/plain")],
                }
            )
            await send({"type": "http.response.body", "body": b"metrics"})
            return
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    async def _call(app, path: str) -> tuple[int, bytes, dict[str, str]]:
        status_box: list[int] = []
        body = bytearray()
        headers: dict[str, str] = {}

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, object]) -> None:
            if message["type"] == "http.response.start":
                status_box.append(int(message["status"]))  # type: ignore[arg-type]
                raw = message.get("headers") or []
                for key, value in raw:  # type: ignore[misc]
                    headers[key.decode("latin-1").lower()] = value.decode("latin-1")
            elif message["type"] == "http.response.body":
                body.extend(message.get("body") or b"")  # type: ignore[arg-type]

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 123),
                "server": ("127.0.0.1", 80),
            },
            receive,
            send,
        )
        return status_box[0], bytes(body), headers

    async def _run() -> None:
        wrapped = LoadSheddingMiddleware(inner)
        first = asyncio.create_task(_call(wrapped, "/sources"))
        for _ in range(50):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        status, body, headers = await _call(wrapped, "/sources")
        assert status == 503
        assert b"PLATFORM_CAPACITY_EXCEEDED" in body
        assert headers.get("retry-after") == "1"
        metrics_status, _metrics_body, _ = await _call(wrapped, "/metrics")
        assert metrics_status == 200
        release.set()
        first_status, first_body, _ = await first
        assert first_status == 200
        assert first_body == b"ok"

    asyncio.run(_run())
    reset_runtime_capacity()


def test_role_defaults_and_actor_share() -> None:
    set_process_role("api")
    reset_runtime_capacity()
    api = get_runtime_capacity()
    assert api.role == "api"
    assert api.pool_size == 8
    assert api.max_overflow == 4
    assert api.thread_tokens == 8
    assert api.admission_slots == 32
    assert api.admission_actor_share == 8
    assert api.statement_timeout_ms == 30_000
    assert api.uvicorn_limit_concurrency == api.http_max_inflight + 32

    set_process_role("mcp")
    reset_runtime_capacity()
    mcp = get_runtime_capacity()
    assert mcp.pool_size == 5
    assert mcp.max_overflow == 3
    assert mcp.thread_tokens == 4
    assert mcp.admission_slots == 16
    assert mcp.admission_actor_share == 8
    assert mcp.uvicorn_limit_concurrency is None

    set_process_role("worker")
    reset_runtime_capacity()
    worker = get_runtime_capacity()
    assert worker.thread_tokens == 0
    assert worker.admission_slots == 0
    assert worker.admission_actor_share == 0
    assert worker.statement_timeout_ms is None
    assert worker.http_max_inflight == 0

    set_process_role("api")
    reset_runtime_capacity()


def test_api_honors_explicit_zero_admission_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REFRAQ_ADMISSION_SLOTS", "0")
    set_process_role("api")
    reset_runtime_capacity()
    cap = get_runtime_capacity()
    assert cap.admission_slots == 0
    assert cap.admission_actor_share == 0
    reset_runtime_capacity()


def test_init_parent_worker_runtime_logs_banner(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("REFRAQ_PROCESS_ROLE", "worker")
    reset_runtime_capacity()
    with caplog.at_level(logging.INFO, logger="backend.core.runtime"):
        init_parent_worker_runtime()
    assert "runtime capacity role=worker" in caplog.text
    assert "admission_slots=0" in caplog.text
    reset_runtime_capacity()


def test_init_parent_worker_runtime_marks_role_before_banner(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("REFRAQ_PROCESS_ROLE", raising=False)
    set_process_role("api")
    reset_runtime_capacity()
    with caplog.at_level(logging.INFO, logger="backend.core.runtime"):
        init_parent_worker_runtime()
    assert get_runtime_capacity().role == "worker"
    assert "runtime capacity role=worker" in caplog.text
    set_process_role("api")
    reset_runtime_capacity()


def test_worker_process_role_engine_omits_statement_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REFRAQ_PROCESS_ROLE", "worker")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:5432/refraq"
    )
    reset_runtime_capacity()
    reset_db_singletons()
    captured: dict[str, object] = {}
    from backend.core import db as db_mod

    real_create_engine = db_mod.create_engine

    def _capture(url: str, **kwargs: object):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return real_create_engine("sqlite://")

    monkeypatch.setattr(db_mod, "create_engine", _capture)
    db_mod.get_engine()
    connect_args = captured.get("connect_args")
    assert isinstance(connect_args, dict)
    options = str(connect_args.get("options") or "")
    assert "statement_timeout" not in options
    assert "TimeZone=UTC" in options
    reset_db_singletons()
    reset_runtime_capacity()


def test_platform_capacity_error_headers() -> None:
    exc = PlatformCapacityExceeded()
    assert exc.http_status == 503
    assert exc.extra_headers() == {"Retry-After": "1"}


def test_platform_timeout_has_no_retry_after() -> None:
    exc = PlatformTimeout()
    assert exc.http_status == 504
    assert exc.extra_headers() == {}


def test_map_platform_db_error_pool_timeout() -> None:
    from sqlalchemy.exc import TimeoutError as PoolTimeoutError

    mapped = map_platform_db_error(PoolTimeoutError())
    assert isinstance(mapped, PlatformCapacityExceeded)


def test_map_platform_db_error_query_canceled() -> None:
    from sqlalchemy.exc import OperationalError

    class QueryCanceled(Exception):
        sqlstate = "57014"

    wrapped = OperationalError("SELECT 1", {}, QueryCanceled())
    mapped = map_platform_db_error(wrapped)
    assert isinstance(mapped, PlatformTimeout)
    assert mapped.extra_headers() == {}


def test_map_platform_db_error_too_many_connections() -> None:
    class TooMany(Exception):
        sqlstate = "53300"

    mapped = map_platform_db_error(TooMany())
    assert isinstance(mapped, PlatformCapacityExceeded)


def test_map_platform_db_error_connection_timeout_type() -> None:
    class ConnectionTimeout(Exception):
        pass

    mapped = map_platform_db_error(ConnectionTimeout())
    assert isinstance(mapped, PlatformCapacityExceeded)


def test_map_platform_db_error_ignores_other() -> None:
    assert map_platform_db_error(RuntimeError("driver")) is None


def test_session_scope_maps_query_canceled(monkeypatch: pytest.MonkeyPatch) -> None:
    class QueryCanceled(Exception):
        sqlstate = "57014"

    class _Session:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise QueryCanceled()

        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

        def commit(self) -> None:
            return None

    monkeypatch.setattr(
        "backend.core.db.get_session_factory", lambda: (lambda: _Session())
    )
    with pytest.raises(PlatformTimeout):
        with session_scope() as session:
            session.execute("SELECT 1")  # type: ignore[arg-type]


def test_hybrid_does_not_swallow_platform_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.metadata.catalog import search_hybrid

    monkeypatch.setattr(
        search_hybrid, "embed_texts", lambda _texts, **_kw: [[0.1, 0.2]]
    )
    monkeypatch.setattr(search_hybrid, "current_generation", lambda: 1)

    class _Store:
        def nearest_embeddings(self, **_kw: object) -> list[str]:
            raise PlatformTimeout()

    monkeypatch.setattr(search_hybrid, "get_catalog_store", lambda: _Store())
    with pytest.raises(PlatformTimeout):
        search_hybrid.vector_page(
            query="orders",
            kind="object",
            id_of=lambda item: item,
            limit=10,
            offset=0,
        )


def _fallback_count(reason: str) -> float:
    from prometheus_client import generate_latest

    from backend.core.metrics import REGISTRY

    prefix = f'refraq_catalog_search_vector_errors_total{{reason="{reason}"}}'
    total = 0.0
    for line in generate_latest(REGISTRY).decode().splitlines():
        if line.startswith(prefix + " "):
            total += float(line.rsplit(" ", 1)[-1])
    return total


def _hybrid_count(outcome: str) -> float:
    from prometheus_client import generate_latest

    from backend.core.metrics import REGISTRY

    prefix = f'refraq_catalog_search_hybrid_total{{outcome="{outcome}"}}'
    total = 0.0
    for line in generate_latest(REGISTRY).decode().splitlines():
        if line.startswith(prefix + " "):
            total += float(line.rsplit(" ", 1)[-1])
    return total


def test_vector_embed_timeout_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.admin.model_services.errors import ModelServiceUnavailable
    from backend.metadata.catalog import search_hybrid
    from backend.metadata.errors import CatalogSearchEmbedFailed

    def _boom(*_args: object, **_kwargs: object) -> list[list[float]]:
        raise ModelServiceUnavailable("Cannot reach embeddings URL")

    monkeypatch.setattr(search_hybrid, "embed_texts", _boom)
    before = _fallback_count("embed_failed")
    with pytest.raises(CatalogSearchEmbedFailed):
        search_hybrid.vector_page(
            query="orders",
            kind="object",
            id_of=lambda item: item,
            limit=10,
            offset=0,
        )
    assert _fallback_count("embed_failed") == before + 1


def test_vector_no_vectors_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.metadata.catalog import search_hybrid
    from backend.metadata.errors import CatalogSearchEmbedFailed

    monkeypatch.setattr(search_hybrid, "embed_texts", lambda *_a, **_k: [])
    before = _fallback_count("no_vectors")
    with pytest.raises(CatalogSearchEmbedFailed):
        search_hybrid.vector_page(
            query="orders",
            kind="object",
            id_of=lambda item: item,
            limit=10,
            offset=0,
        )
    assert _fallback_count("no_vectors") == before + 1


def test_vector_empty_neighbors_is_empty_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.metadata.catalog import search_hybrid

    monkeypatch.setattr(search_hybrid, "embed_texts", lambda *_a, **_k: [[0.1, 0.2]])
    monkeypatch.setattr(search_hybrid, "current_generation", lambda: 1)

    class _Store:
        def nearest_embeddings(self, **_kw: object) -> list[str]:
            return []

    monkeypatch.setattr(search_hybrid, "get_catalog_store", lambda: _Store())
    before = _fallback_count("no_neighbors")
    before_vec = _hybrid_count("vector")
    page, truncated = search_hybrid.vector_page(
        query="orders",
        kind="object",
        id_of=lambda item: item,
        limit=10,
        offset=0,
    )
    assert page == []
    assert truncated is False
    assert _fallback_count("no_neighbors") == before
    assert _hybrid_count("vector") == before_vec + 1


def test_vector_page_records_vector_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.metadata.catalog import search_hybrid

    monkeypatch.setattr(search_hybrid, "embed_texts", lambda *_a, **_k: [[0.1, 0.2]])
    monkeypatch.setattr(search_hybrid, "current_generation", lambda: 1)

    class _Store:
        def nearest_embeddings(self, **_kw: object) -> list[str]:
            return ["a"]

        def get_objects_by_ids(self, ids: list[str]) -> list[str]:
            return ids

    monkeypatch.setattr(search_hybrid, "get_catalog_store", lambda: _Store())
    before = _hybrid_count("vector")
    page, truncated = search_hybrid.vector_page(
        query="orders",
        kind="object",
        id_of=lambda item: item,
        limit=10,
        offset=0,
    )
    assert page == ["a"]
    assert truncated is False
    assert _hybrid_count("vector") == before + 1


def test_project_embedding_truncates_and_passes_short() -> None:
    from backend.metadata.catalog.embedding import project_embedding

    short = [0.3, 0.4]
    assert project_embedding(short, dim=4) == short
    long = [3.0, 4.0] + [0.0] * 10
    out = project_embedding(long, dim=2)
    assert out == [0.6, 0.8]


def test_embed_texts_projects_long_native_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.metadata.catalog import embedding as embedding_mod

    monkeypatch.setattr(
        embedding_mod,
        "post_openai_embeddings",
        lambda **_kw: [[3.0, 4.0] + [0.0] * 20],
    )
    monkeypatch.setattr(
        embedding_mod,
        "get_embedding_runtime",
        lambda: type(
            "R",
            (),
            {"url": "http://embed.test", "model": "m", "secret": None},
        )(),
    )
    embedding_mod.set_embed_fn_for_tests(None)
    monkeypatch.setattr(embedding_mod, "EMBEDDING_OUTPUT_DIM", 2)
    assert embedding_mod.embed_texts(["q"]) == [[0.6, 0.8]]


def test_post_openai_embeddings_posts_model_and_input_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.admin.model_services import openai_compat

    captured: dict[str, object] = {}

    class _Resp:
        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"data":[{"index":0,"embedding":[0.1,0.2]}]}'

    def _urlopen(req: object, timeout: int = 0) -> _Resp:
        captured["payload"] = json.loads(req.data.decode("utf-8"))  # type: ignore[attr-defined]
        return _Resp()

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    vectors = openai_compat.post_openai_embeddings(
        url="http://embed.test/v1/embeddings",
        model="m",
        api_key=None,
        texts=["q"],
    )
    assert vectors == [[0.1, 0.2]]
    assert captured["payload"] == {"model": "m", "input": ["q"]}


def _seed_admin() -> None:
    from backend.admin.roles import seed_roles
    from backend.admin.role_store import get_role_store
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store

    roles = get_role_store()
    seed_roles(roles)
    super_admin = roles.get_by_key("super_admin")
    assert super_admin is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=super_admin.id,
        status="active",
    )


def _login_admin(client: TestClient) -> None:
    login = client.post("/auth/login", json={"account": "admin", "password": "secret"})
    assert login.status_code == 200


def test_vector_search_uses_admission_and_leaves_short_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.metadata.catalog.embedding import set_embed_fn_for_tests

    monkeypatch.setenv("REFRAQ_ADMISSION_SLOTS", "1")
    monkeypatch.setenv("REFRAQ_ADMISSION_ACTOR_SHARE", "1")
    reset_runtime_capacity()
    reset_peek_bulkhead()
    set_embed_fn_for_tests(lambda _texts: [[0.1, 0.2]])
    _seed_admin()
    hold = threading.Event()

    def _block() -> str:
        hold.wait(timeout=2)
        return "held"

    with TestClient(app) as client:
        _login_admin(client)
        future = get_peek_bulkhead().submit_nowait("other-user", _block)
        search = client.get("/catalog/objects/search", params={"q": "orders"})
        assert search.status_code == 503, search.text
        assert search.json()["code"] == "ADMISSION_CAPACITY_EXCEEDED"
        me = client.get("/auth/me")
        assert me.status_code == 200
        hold.set()
        assert future.result(timeout=2) == "held"
    set_embed_fn_for_tests(None)
    reset_peek_bulkhead()
    reset_runtime_capacity()


def test_lexical_search_and_guest_share_do_not_block_each_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.core.admission import GUEST_ACTOR
    from backend.metadata.catalog.embedding import set_embed_fn_for_tests

    monkeypatch.setenv("REFRAQ_ADMISSION_SLOTS", "1")
    monkeypatch.setenv("REFRAQ_ADMISSION_ACTOR_SHARE", "1")
    reset_runtime_capacity()
    reset_peek_bulkhead()
    set_embed_fn_for_tests(None)
    _seed_admin()
    hold = threading.Event()

    def _block() -> str:
        hold.wait(timeout=2)
        return "held"

    with TestClient(app) as client:
        _login_admin(client)
        future = get_peek_bulkhead().submit_nowait(GUEST_ACTOR, _block)
        search = client.get("/catalog/objects/search", params={"q": "orders"})
        assert search.status_code == 200, search.text
        me = client.get("/auth/me")
        assert me.status_code == 200
        hold.set()
        assert future.result(timeout=2) == "held"
    reset_peek_bulkhead()
    reset_runtime_capacity()
