"""Jobs and schedules follow Source access via an opaque stamp."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.jobs.store import create_queued_job, get_job_store, reset_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.source_access import (  # noqa: E402
    create_membership,
    reset_source_access_store,
)
from backend.metadata.source_jobs import (  # noqa: E402
    enqueue_source_work_job,
    mint_source_due_job,
)
from backend.metadata.sources.access import seal_access  # noqa: E402
from backend.metadata.sources.store import (  # noqa: E402
    SourceRecord,
    get_source_store,
    reset_source_store,
)
from backend.worker.models import REAPER_SCHEDULE_KEY  # noqa: E402
from backend.worker.schedules import (  # noqa: E402
    ScheduledTaskRecord,
    get_schedule_store,
    reset_schedule_store,
)

_SOURCE_ACCESS = {
    "host": "127.0.0.1",
    "port": 5432,
    "username": "u",
    "password": "p",
    "ssl_mode": "require",
    "database": "MES",
    "schema": "public",
    "extra": {},
}


def _reset() -> None:
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_source_store()
    reset_source_access_store()
    reset_job_store()
    reset_schedule_store()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    _reset()
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
    monkeypatch.setattr(
        "backend.metadata.tasks.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    monkeypatch.setattr(
        "backend.metadata.tasks.run_join_detection_job",
        lambda job_id: {"status": "succeeded"},
    )
    monkeypatch.setattr(
        "backend.metadata.catalog_embed_jobs.runner.run_catalog_embed_job",
        lambda job_id: {"status": "succeeded"},
    )
    with TestClient(app) as test_client:
        _login(test_client, "admin", "secret")
        yield test_client


def _login(client: TestClient, account: str, password: str) -> None:
    resp = client.post("/auth/login", json={"account": account, "password": password})
    assert resp.status_code == 200, resp.text


def _create_source(client: TestClient, key: str) -> dict:
    resp = client.post(
        "/sources",
        json={
            "key": key,
            "name": key,
            "kind": "database",
            "engine": "postgresql",
            "access": dict(_SOURCE_ACCESS),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["source"]


def _structure_schedule_id(client: TestClient, source_id: str) -> str:
    listed = client.get(f"/sources/{source_id}/schedules")
    assert listed.status_code == 200, listed.text
    for item in listed.json()["items"]:
        if item["work_kind"] == "structure":
            return item["id"]
    raise AssertionError("structure schedule missing")


def _catalog_schedule_id(client: TestClient) -> str:
    listed = client.get("/schedules?limit=200")
    assert listed.status_code == 200, listed.text
    for item in listed.json()["items"]:
        if item["work_kind"] == "catalog_embed":
            return item["id"]
    raise AssertionError("catalog embed schedule missing")


def _ids(client: TestClient, path: str) -> set[str]:
    resp = client.get(path)
    assert resp.status_code == 200, resp.text
    return {item["id"] for item in resp.json()["items"]}


def _collector_role() -> str:
    role = create_role(
        get_role_store(),
        key="collector",
        name="Collector",
        permissions=["console:access", "jobs:run"],
    )
    return role.id


def _collector(account: str, role_id: str):
    return get_user_store().create_user(
        account=account,
        display_name=account,
        password_hash=hash_password(account),
        role_id=role_id,
        status="active",
    )


def _database_source(source_id: str, key: str) -> None:
    now = utc_now()
    get_source_store().create_source(
        SourceRecord(
            id=source_id,
            key=key,
            locator_key=f"src/postgresql/{key}",
            name=key,
            kind="database",
            status="active",
            description=None,
            engine="postgresql",
            access_ciphertext=seal_access("postgresql", dict(_SOURCE_ACCESS)),
            access_updated_at=now,
            created_at=now,
            updated_at=now,
        )
    )


def _schedule(
    *,
    schedule_id: str,
    key: str,
    source_id: str | None,
    access_stamp: str | None = None,
    hidden: bool = False,
    owner_ref: str | None = None,
) -> ScheduledTaskRecord:
    now = utc_now()
    kwargs = {"schedule_id": schedule_id}
    if source_id is not None:
        kwargs["source_id"] = source_id
    return ScheduledTaskRecord(
        id=schedule_id,
        key=key,
        name=key,
        enabled=True,
        interval_seconds=3600,
        cron=None,
        task_name="backend.example.task",
        args_json=[],
        kwargs_json=kwargs,
        hidden=hidden,
        owner_ref=owner_ref,
        access_stamp=access_stamp,
        last_run_at=now,
        next_run_at=now,
        created_at=now,
        updated_at=now,
    )


def test_create_queued_job_stores_only_an_explicit_stamp() -> None:
    _reset()
    kinds = (
        ("structure", {"source_id": "src_alpha"}),
        ("join_detection", {"source_id": "src_alpha"}),
        ("channel_run", {"channel_id": "chn_1", "source_id": "src_alpha"}),
        ("catalog_embed", {"source_id": "src_alpha"}),
        ("entity_table_drop", {"entity_version_id": "ver_1", "source_id": "src_alpha"}),
    )
    for kind, payload in kinds:
        job = create_queued_job(kind=kind, input=payload)
        assert job.access_stamp is None
    explicit = create_queued_job(
        kind="structure",
        input={"source_id": "src_other"},
        access_stamp="src_alpha",
    )
    assert explicit.access_stamp == "src_alpha"
    assert get_job_store().get(explicit.id).access_stamp == "src_alpha"  # type: ignore[union-attr]


def test_source_mint_writes_the_source_id_stamp(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset()
    monkeypatch.setattr(
        "backend.metadata.source_jobs.dispatch_queued_job",
        lambda job: job.id,
    )
    _database_source("src_alpha", "alpha")
    queued = enqueue_source_work_job(
        kind="structure",
        source_id="src_alpha",
        actor_user_id=None,
        trigger_ref="sched_alpha",
    )
    assert queued.access_stamp == "src_alpha"
    assert queued.input == {"source_id": "src_alpha"}

    now = utc_now()
    missing = mint_source_due_job(
        kind="structure",
        schedule_id="sched_missing",
        source_id=None,
        scheduled_for=now,
        now=now,
    )
    missing_job = get_job_store().get(missing["job_id"])
    assert missing_job is not None
    assert missing_job.access_stamp is None
    assert missing_job.input == {}

    bound = mint_source_due_job(
        kind="join_detection",
        schedule_id="sched_bound",
        source_id="src_alpha",
        scheduled_for=now + timedelta(seconds=1),
        now=now,
    )
    bound_job = get_job_store().get(bound["job_id"])
    assert bound_job is not None
    assert bound_job.access_stamp == "src_alpha"
    assert bound_job.input["source_id"] == "src_alpha"


def test_lists_treat_the_allow_list_as_opaque_text() -> None:
    _reset()
    bare = create_queued_job(kind="channel_run", input={"source_id": "src_beta"})
    alpha = create_queued_job(
        kind="structure", input={"note": "ignore"}, access_stamp="src_alpha"
    )
    beta = create_queued_job(
        kind="join_detection",
        input={"source_id": "src_alpha"},
        access_stamp="src_beta",
    )
    jobs = get_job_store()

    def job_ids(stamps: frozenset[str] | None) -> set[str]:
        rows, total = jobs.list(access_stamps=stamps)
        assert total == len(rows)
        return {row.id for row in rows}

    assert job_ids(None) == {bare.id, alpha.id, beta.id}
    assert job_ids(frozenset()) == {bare.id}
    assert job_ids(frozenset({"src_alpha"})) == {bare.id, alpha.id}

    schedules = get_schedule_store()
    hidden = schedules.upsert(
        _schedule(
            schedule_id="sched_hidden",
            key="system:hidden",
            source_id=None,
            hidden=True,
        )
    )
    plain = schedules.upsert(
        _schedule(schedule_id="sched_plain", key="plain", source_id="src_beta")
    )
    alpha_row = schedules.upsert(
        _schedule(
            schedule_id="sched_alpha",
            key="alpha",
            source_id="src_other",
            access_stamp="src_alpha",
            owner_ref="metadata:source:src_other",
        )
    )
    beta_row = schedules.upsert(
        _schedule(
            schedule_id="sched_beta",
            key="beta",
            source_id="src_alpha",
            access_stamp="src_beta",
            owner_ref="metadata:source:src_alpha",
        )
    )
    assert plain.access_stamp is None
    assert alpha_row.access_stamp == "src_alpha"

    def schedule_ids(
        stamps: frozenset[str] | None, *, include_hidden: bool = False
    ) -> set[str]:
        rows, total = schedules.list(
            include_hidden=include_hidden, access_stamps=stamps
        )
        assert total == len(rows)
        return {row.id for row in rows}

    assert hidden.id not in schedule_ids(None)
    assert schedule_ids(None, include_hidden=True) == {
        hidden.id,
        plain.id,
        alpha_row.id,
        beta_row.id,
    }
    assert schedule_ids(frozenset()) == {plain.id}
    assert schedule_ids(frozenset(), include_hidden=True) == {plain.id, hidden.id}
    assert schedule_ids(frozenset({"src_alpha"})) == {plain.id, alpha_row.id}


def test_upsert_does_not_infer_or_clear_a_stamp() -> None:
    _reset()
    store = get_schedule_store()
    created = store.upsert(
        _schedule(
            schedule_id="sched_keep",
            key="keep",
            source_id="src_alpha",
            access_stamp="src_alpha",
            owner_ref="metadata:source:src_alpha",
        )
    )
    assert created.access_stamp == "src_alpha"
    replaced = store.upsert(
        _schedule(
            schedule_id="sched_keep",
            key="keep",
            source_id="src_other",
            owner_ref="metadata:source:src_other",
        )
    )
    assert replaced.access_stamp == "src_alpha"
    assert store.get_by_id("sched_keep").access_stamp == "src_alpha"  # type: ignore[union-attr]

    moved = store.consume_due_cursor(
        "sched_keep",
        last_run_at=utc_now(),
        next_if_enabled=utc_now() + timedelta(hours=1),
    )
    assert moved is not None
    assert moved.access_stamp == "src_alpha"


def test_operations_lists_follow_jobs_run(client: TestClient) -> None:
    alpha = _create_source(client, "alpha")
    beta = _create_source(client, "beta")
    alpha_schedule = _structure_schedule_id(client, alpha["id"])
    beta_schedule = _structure_schedule_id(client, beta["id"])
    catalog_id = _catalog_schedule_id(client)
    catalog = get_schedule_store().get_by_id(catalog_id)
    reaper = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
    assert catalog is not None and catalog.access_stamp is None
    assert reaper is not None and reaper.access_stamp is None
    for source_id in (alpha["id"], beta["id"]):
        rows, _ = get_schedule_store().list_by_owner_ref(
            f"metadata:source:{source_id}"
        )
        assert rows
        assert {row.access_stamp for row in rows} == {source_id}
        assert {row.owner_ref for row in rows} == {f"metadata:source:{source_id}"}

    alpha_run = client.post(f"/schedules/{alpha_schedule}/run")
    beta_run = client.post(f"/schedules/{beta_schedule}/run")
    assert alpha_run.status_code == 202, alpha_run.text
    assert beta_run.status_code == 202, beta_run.text
    alpha_job = alpha_run.json()["job"]["id"]
    beta_job = beta_run.json()["job"]["id"]
    assert get_job_store().get(alpha_job).access_stamp == alpha["id"]  # type: ignore[union-attr]
    assert get_job_store().get(beta_job).access_stamp == beta["id"]  # type: ignore[union-attr]

    direct = create_queued_job(kind="structure", input={"source_id": alpha["id"]})
    channel = create_queued_job(
        kind="channel_run",
        input={"channel_id": "chn_1", "target": "draft"},
    )
    assert direct.access_stamp is None
    assert channel.access_stamp is None

    admin_jobs = _ids(client, "/jobs?limit=200")
    assert {alpha_job, beta_job, direct.id, channel.id} <= admin_jobs

    role_id = _collector_role()
    _collector("collector", role_id)
    _login(client, "collector", "collector")
    hidden = _ids(client, "/jobs?limit=200")
    assert direct.id in hidden
    assert channel.id in hidden
    assert alpha_job not in hidden
    assert beta_job not in hidden
    visible = _ids(client, "/schedules?limit=200")
    assert catalog_id in visible
    assert alpha_schedule not in visible
    assert beta_schedule not in visible
    assert reaper.id not in visible
    with_hidden = _ids(client, "/schedules?hidden=true&limit=200")
    assert reaper.id in with_hidden
    assert alpha_schedule not in with_hidden

    opened = client.get(f"/schedules/{catalog_id}")
    assert opened.status_code == 200, opened.text
    embedded = client.post(f"/schedules/{catalog_id}/run")
    assert embedded.status_code == 202, embedded.text
    embed_job = get_job_store().get(embedded.json()["job"]["id"])
    assert embed_job is not None
    assert embed_job.access_stamp is None
    assert embed_job.kind == "catalog_embed"
    assert embed_job.id in _ids(client, "/jobs?limit=200")

    create_membership(
        subject_type="user",
        subject_id=get_user_store().get_by_account("collector").id,  # type: ignore[union-attr]
        target=alpha["id"],
        level="maintainer",
    )
    granted_jobs = _ids(client, "/jobs?limit=200")
    assert alpha_job in granted_jobs
    assert beta_job not in granted_jobs
    assert direct.id in granted_jobs
    granted_schedules = _ids(client, "/schedules?limit=200")
    assert alpha_schedule in granted_schedules
    assert beta_schedule not in granted_schedules
    assert catalog_id in granted_schedules


@pytest.mark.parametrize("level", ["viewer", "steward"])
def test_weaker_level_cannot_manage_source_schedules(
    client: TestClient, level: str
) -> None:
    source = _create_source(client, f"src-{level}")
    schedule_id = _structure_schedule_id(client, source["id"])
    role_id = _collector_role()
    user = _collector(level, role_id)
    create_membership(
        subject_type="user",
        subject_id=user.id,
        target=source["id"],
        level=level,
    )
    _login(client, level, level)

    listed = client.get(f"/sources/{source['id']}/schedules")
    assert listed.status_code == 403
    assert listed.json()["code"] == "AUTH_FORBIDDEN"
    created = client.post(
        f"/sources/{source['id']}/schedules",
        json={"kind": "structure", "cron": "0 3 * * *", "enabled": True},
    )
    assert created.status_code == 403
    assert created.json()["code"] == "AUTH_FORBIDDEN"
    for method, path, body in (
        ("get", f"/schedules/{schedule_id}", None),
        ("get", f"/schedules/{schedule_id}/jobs", None),
        ("patch", f"/schedules/{schedule_id}", {"enabled": False}),
        ("delete", f"/schedules/{schedule_id}", None),
        ("post", f"/schedules/{schedule_id}/run", None),
    ):
        resp = client.request(method, path, json=body)
        if method == "get":
            assert resp.status_code == 404, resp.text
            assert resp.json()["code"] == "SCHEDULE_NOT_FOUND"
        else:
            assert resp.status_code == 403, resp.text
            assert resp.json()["code"] == "AUTH_FORBIDDEN"


def test_missing_level_matches_the_route_miss(client: TestClient) -> None:
    source = _create_source(client, "hidden-src")
    schedule_id = _structure_schedule_id(client, source["id"])
    role_id = _collector_role()
    _collector("outsider", role_id)
    _login(client, "outsider", "outsider")

    listed = client.get(f"/sources/{source['id']}/schedules")
    assert listed.status_code == 404
    assert listed.json()["code"] == "SOURCE_NOT_FOUND"
    created = client.post(
        f"/sources/{source['id']}/schedules",
        json={"kind": "join_detection", "cron": "0 5 * * *", "enabled": True},
    )
    assert created.status_code == 404
    assert created.json()["code"] == "SOURCE_NOT_FOUND"
    for path in (
        f"/schedules/{schedule_id}",
        f"/schedules/{schedule_id}/jobs",
    ):
        resp = client.get(path)
        assert resp.status_code == 404, resp.text
        assert resp.json()["code"] == "SCHEDULE_NOT_FOUND"
    patched = client.patch(f"/schedules/{schedule_id}", json={"enabled": False})
    assert patched.status_code == 404
    assert patched.json()["code"] == "SCHEDULE_NOT_FOUND"
    deleted = client.delete(f"/schedules/{schedule_id}")
    assert deleted.status_code == 404
    assert deleted.json()["code"] == "SCHEDULE_NOT_FOUND"
    ran = client.post(f"/schedules/{schedule_id}/run")
    assert ran.status_code == 404
    assert ran.json()["code"] == "SCHEDULE_NOT_FOUND"


def test_maintainer_manages_schedules_for_that_source(client: TestClient) -> None:
    alpha = _create_source(client, "kept")
    beta = _create_source(client, "other")
    alpha_schedule = _structure_schedule_id(client, alpha["id"])
    beta_schedule = _structure_schedule_id(client, beta["id"])
    role_id = _collector_role()
    user = _collector("keeper", role_id)
    create_membership(
        subject_type="user",
        subject_id=user.id,
        target=alpha["id"],
        level="maintainer",
    )
    _login(client, "keeper", "keeper")

    listed = client.get(f"/sources/{alpha['id']}/schedules")
    assert listed.status_code == 200, listed.text
    hidden = client.get(f"/sources/{beta['id']}/schedules")
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "SOURCE_NOT_FOUND"

    created = client.post(
        f"/sources/{alpha['id']}/schedules",
        json={"kind": "join_detection", "cron": "15 4 * * *", "enabled": True},
    )
    assert created.status_code == 201, created.text
    created_id = created.json()["schedule"]["id"]
    created_row = get_schedule_store().get_by_id(created_id)
    assert created_row is not None
    assert created_row.access_stamp == alpha["id"]

    shown = client.get(f"/schedules/{alpha_schedule}")
    assert shown.status_code == 200, shown.text
    jobs = client.get(f"/schedules/{alpha_schedule}/jobs")
    assert jobs.status_code == 200, jobs.text
    missed = client.get(f"/schedules/{beta_schedule}")
    assert missed.status_code == 404
    assert missed.json()["code"] == "SCHEDULE_NOT_FOUND"

    patched = client.patch(
        f"/schedules/{created_id}", json={"enabled": False, "name": "kept hours"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["schedule"]["enabled"] is False
    assert get_schedule_store().get_by_id(created_id).access_stamp == alpha["id"]  # type: ignore[union-attr]

    ran = client.post(f"/schedules/{alpha_schedule}/run")
    assert ran.status_code == 202, ran.text
    ran_job = get_job_store().get(ran.json()["job"]["id"])
    assert ran_job is not None
    assert ran_job.access_stamp == alpha["id"]

    denied = client.post(f"/schedules/{beta_schedule}/run")
    assert denied.status_code == 404
    assert denied.json()["code"] == "SCHEDULE_NOT_FOUND"

    removed = client.delete(f"/schedules/{created_id}")
    assert removed.status_code == 204, removed.text
    assert get_schedule_store().get_by_id(created_id) is None


def test_job_detail_logs_and_cancel_follow_the_stamp(client: TestClient) -> None:
    hidden = create_queued_job(
        kind="structure",
        input={"source_id": "src_beta"},
        access_stamp="src_beta",
        log_body="2026-01-01T00:00:00Z INFO secret",
    )
    plain = create_queued_job(
        kind="channel_run",
        input={"channel_id": "chn_1", "target": "draft"},
        log_body="2026-01-01T00:00:00Z INFO plain",
    )
    assert client.get(f"/jobs/{hidden.id}").status_code == 200

    role_id = _collector_role()
    reader = _collector("reader", role_id)
    _login(client, "reader", "reader")
    for path in (f"/jobs/{hidden.id}", f"/jobs/{hidden.id}/logs"):
        missed = client.get(path)
        assert missed.status_code == 404, missed.text
        assert missed.json()["code"] == "JOB_NOT_FOUND"
    denied = client.post(f"/jobs/{hidden.id}/cancel")
    assert denied.status_code == 404, denied.text
    assert denied.json()["code"] == "JOB_NOT_FOUND"
    stored = get_job_store().get(hidden.id)
    assert stored is not None
    assert stored.status == "queued"

    detail = client.get(f"/jobs/{plain.id}")
    assert detail.status_code == 200, detail.text
    logs = client.get(f"/jobs/{plain.id}/logs")
    assert logs.status_code == 200, logs.text
    assert "INFO plain" in logs.json()["body"]

    create_membership(
        subject_type="user",
        subject_id=reader.id,
        target="src_beta",
        level="maintainer",
    )
    opened = client.get(f"/jobs/{hidden.id}")
    assert opened.status_code == 200, opened.text
    opened_logs = client.get(f"/jobs/{hidden.id}/logs")
    assert opened_logs.status_code == 200, opened_logs.text
    assert "INFO secret" in opened_logs.json()["body"]
    cancelled = client.post(f"/jobs/{hidden.id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["job"]["status"] == "cancelled"


def test_channel_writer_cannot_cancel_a_hidden_source_job(client: TestClient) -> None:
    hidden = create_queued_job(
        kind="structure",
        input={"source_id": "src_beta", "channel_id": "chn_1"},
        access_stamp="src_beta",
    )
    role = create_role(
        get_role_store(),
        key="channel_author",
        name="Channel author",
        permissions=["console:access", "channel:write"],
    )
    get_user_store().create_user(
        account="author",
        display_name="Author",
        password_hash=hash_password("author"),
        role_id=role.id,
        status="active",
    )
    _login(client, "author", "author")
    denied = client.post(f"/jobs/{hidden.id}/cancel")
    assert denied.status_code == 404, denied.text
    assert denied.json()["code"] == "JOB_NOT_FOUND"
    stored = get_job_store().get(hidden.id)
    assert stored is not None
    assert stored.status == "queued"
