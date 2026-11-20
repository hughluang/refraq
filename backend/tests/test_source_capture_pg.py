"""Real isolated PostgreSQL capture storage and HTTP integration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.admin.audit_store import SqlAuditStore
from backend.tests import test_integration_persistent as persistent
from backend.tests.test_sources_jobs import _access
from backend.metadata.capture.control import capture_status
from backend.metadata.capture.configuration import CaptureCredential
from backend.metadata.sources.service import update_source
from backend.metadata.sources.store import get_source_store
from backend.core.secrets import decrypt_secret
from backend.core.db import get_engine, session_scope
from backend.core.time import utc_now
from backend.metadata.models import CatalogObjectRow
from backend.metadata.catalog.store.sql import SqlCatalogStore
from sqlalchemy.exc import StatementError

pytestmark = pytest.mark.integration


@pytest.fixture
def capture_pg_client(monkeypatch):
    database = "refraq_capture_test_" + uuid.uuid4().hex[:12]
    url = make_url(persistent.INTEGRATION_DATABASE_URL).set(database=database)
    maintenance = make_url(persistent._MAINTENANCE_DATABASE_URL)
    monkeypatch.setattr(
        persistent,
        "INTEGRATION_DATABASE_URL",
        url.render_as_string(hide_password=False),
    )
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "capture-integration-test-key")
    if not persistent._services_available():
        pytest.skip("Refraq integration PostgreSQL and Redis are unavailable")
    try:
        yield from persistent.persistent_client.__wrapped__(monkeypatch)
    finally:
        engine = create_engine(maintenance, isolation_level="AUTOCOMMIT")
        try:
            with engine.connect() as connection:
                connection.execute(
                    text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
                )
        finally:
            engine.dispose()


def test_capture_postgres_http_and_concurrent_revisions(capture_pg_client):
    client = capture_pg_client
    assert (
        client.post(
            "/auth/login", json={"account": "root", "password": "s3cret"}
        ).status_code
        == 200
    )
    credential = {"username": "pg-capture-user", "password": "pg-capture-password"}
    response = client.post(
        "/sources",
        json={
            "key": "pg-capture",
            "name": "PG capture",
            "engine": "postgresql",
            "access": _access(),
            "capture_credential": credential,
            "snapshot_window": {"start": "23:00", "end": "01:00"},
        },
    )
    assert response.status_code == 201, response.text
    source_id = response.json()["source"]["id"]
    record = get_source_store().get_source(source_id)
    assert (
        json.loads(decrypt_secret(record.capture_credential_ciphertext)) == credential
    )
    assert record.capture_revision == 1
    engine = create_engine(persistent.INTEGRATION_DATABASE_URL)
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT capture_credential_ciphertext, capture_revision, snapshot_window FROM sources WHERE id=:id"
            ),
            {"id": source_id},
        ).one()
        assert credential["username"] not in row[0]
        assert credential["password"] not in row[0]
        assert row[1] == 1
        assert row[2] == {"start": "23:00", "end": "01:00"}
    engine.dispose()

    def rotate(index):
        update_source(
            source_id,
            capture_credential=CaptureCredential(
                username="rotated", password=f"password-{index}"
            ),
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(rotate, range(12)))
    assert get_source_store().get_source(source_id).capture_revision == 13
    control = capture_status(source_id)
    assert control['control']['control_revision'] == 13
    assert len(control['operations']) == 13
    assert len({op['operation_id'] for op in control['operations']}) == 13
    for path in (
        "/sources",
        f"/sources/{source_id}",
        f"/sources/{source_id}/access",
        "/audit/events",
    ):
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert credential["username"] not in response.text
        assert credential["password"] not in response.text
        assert "password-" not in response.text
    assert (
        client.patch(f"/sources/{source_id}", json={"name": "Retained"}).status_code
        == 200
    )
    assert get_source_store().get_source(source_id).capture_revision == 13
    clear = client.patch(f"/sources/{source_id}", json={"capture_credential": None})
    assert clear.status_code == 200, clear.text
    assert clear.json()["source"]["capture_state"] == "disabled"
    assert get_source_store().get_source(source_id).capture_revision == 14
    timestamp = clear.json()["source"]["capture_credential_updated_at"]
    again = client.patch(f"/sources/{source_id}", json={"capture_credential": None})
    assert again.json()["source"]["capture_credential_updated_at"] == timestamp
    assert get_source_store().get_source(source_id).capture_revision == 14


@pytest.mark.parametrize("intent", ["replace", "clear"])
def test_patch_and_success_audit_commit_together(capture_pg_client, monkeypatch, intent):
    client = capture_pg_client
    client.post("/auth/login", json={"account": "root", "password": "s3cret"})
    actor = client.get("/auth/me").json()["user"]["id"]
    token = client.post("/tokens", json={"name": "patch", "expires_at": None}).json()
    client.cookies.clear()
    client.headers.update({"Authorization": f"Bearer {token['secret']}"})
    created = client.post("/sources", json={
        "key": "atomic", "name": "Before", "engine": "postgresql", "access": _access(),
        "capture_credential": {"username": "initial", "password": "initial-test"},
    })
    assert created.status_code == 201
    source_id = created.json()["source"]["id"]
    payload = {
        "name": "After", "snapshot_window": {"start": "23:00", "end": "01:00"},
        "capture_credential": {"username": "other", "password": "other-test"} if intent == "replace" else None,
    }

    def events():
        with session_scope() as session:
            return session.execute(text(
                "SELECT actor_user_id, actor_token_id, detail FROM audit_events "
                "WHERE resource_type='source' AND resource_id=:id "
                "AND action='source.update' AND result='success'"
            ), {"id": source_id}).all()

    store = get_source_store()
    before = store.get_source(source_id)
    control_before = capture_status(source_id)
    write = SqlAuditStore.create_on

    def fail_after_insert(self, session, record):
        result = write(self, session, record)
        if record.action == "source.update":
            raise RuntimeError("injected audit failure")
        return result

    with monkeypatch.context() as fault:
        fault.setattr(SqlAuditStore, "create_on", fail_after_insert)
        with pytest.raises(RuntimeError, match="injected audit failure"):
            client.patch(f"/sources/{source_id}", json=payload)
    assert events() == []
    unchanged = store.get_source(source_id) == before
    assert unchanged, "failed PATCH changed the stored Source"
    assert capture_status(source_id) == control_before

    assert client.patch(f"/sources/{source_id}", json=payload).status_code == 200
    after = store.get_source(source_id)
    assert after.capture_revision == before.capture_revision + 1
    assert after.name == "After"
    assert after.snapshot_window == payload["snapshot_window"]
    assert (after.capture_credential_ciphertext is None) == (intent == "clear")
    assert events() == [(actor, token["token"]["id"], {
        "fields": ["capture_credential", "name", "snapshot_window"], "capture_credential": intent,
    })]


def test_capture_database_errors_and_engine_change_are_transactional(
    capture_pg_client, monkeypatch
):
    client = capture_pg_client
    client.post("/auth/login", json={"account": "root", "password": "s3cret"})
    response = client.post(
        "/sources",
        json={
            "key": "engine-change",
            "name": "Engine",
            "engine": "postgresql",
            "access": _access(),
        },
    )
    assert response.status_code == 201, response.text
    source_id = response.json()["source"]["id"]
    now = utc_now()
    with session_scope() as session:
        session.add(
            CatalogObjectRow(
                id="obj_engine_change",
                source_id=source_id,
                locator_key="old-locator",
                object_type="table",
                schema_name="public",
                name="orders",
                is_present=True,
                business_semantics_ready=False,
                created_at=now,
                updated_at=now,
            )
        )
    original = SqlCatalogStore.recompute_locators_for_source

    def fail_after_recompute(self, *args, **kwargs):
        assert kwargs.get("session") is not None
        original(self, *args, **kwargs)
        raise RuntimeError("abort engine change")

    monkeypatch.setattr(
        SqlCatalogStore, "recompute_locators_for_source", fail_after_recompute
    )
    with pytest.raises(RuntimeError, match="abort engine change"):
        update_source(source_id, engine="mssql", access=_access(ssl_mode="disable"))
    assert get_source_store().get_source(source_id).engine == "postgresql"
    with session_scope() as session:
        assert (
            session.get(CatalogObjectRow, "obj_engine_change").locator_key
            == "old-locator"
        )
    monkeypatch.setattr(SqlCatalogStore, "recompute_locators_for_source", original)
    update_source(source_id, engine="mssql", access=_access(ssl_mode="disable"))
    assert get_source_store().get_source(source_id).engine == "mssql"
    with session_scope() as session:
        assert (
            session.get(CatalogObjectRow, "obj_engine_change").locator_key
            != "old-locator"
        )

    marker = "encrypted-capture-parameter-marker"
    with pytest.raises(StatementError) as error:
        with get_engine().begin() as connection:
            connection.execute(
                text("SELECT :secret FROM capture_missing_relation"), {"secret": marker}
            )
    assert marker not in str(error.value)
    assert get_engine().hide_parameters is True
