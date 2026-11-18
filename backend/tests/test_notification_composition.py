"""Offline notification runtime assembly checks; no lifespan or external services."""

from contextlib import contextmanager
import ast
from pathlib import Path
import json
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from backend.admin.deps import get_current_user
from backend.admin.role_store import RoleRecord, get_role_store
from backend.admin.user_store import UserRecord
from backend.core.config import Settings, reset_settings_cache
from backend.main import app
from backend.worker import tasks
from backend.worker.api import ensure_system_schedules, patch_schedule, delete_schedule
from backend.worker.errors import ScheduleSystemImmutable, ScheduleUndeletable
from backend.worker.parameters import (
    NOTIFICATION_SCHEDULE_KEY, NOTIFICATION_TASK_NAME, assemble_system_parameters,
)
from backend.worker.scheduler import DatabaseScheduler
from backend.tests.test_layout_imports import _is_published_import
from backend.admin.notifications import service as notification_service
from backend.worker.schedules import get_schedule_store


ORIGINS = {"https://primary.invalid": "reviewed-a", "https://fallback.invalid": "reviewed-b"}
BUDGET = {
    "max_attempts_per_route": 2, "retry_delays_seconds": [3],
    "timeout_seconds": 1, "batch_size": 2, "interval_seconds": 5,
}


def test_only_enqueue_is_product_surface_and_alembic_discovers_real_models():
    assert notification_service.__all__ == ["enqueue_notification"]
    assert _is_published_import("admin", "admin.notifications.service")
    for module in ("configuration", "delivery", "models", "router"):
        assert not _is_published_import("admin", f"admin.notifications.{module}")
    env = Path(__file__).resolve().parents[1] / "alembic" / "env.py"
    tree = ast.parse(env.read_text())
    assert any(isinstance(node, ast.Import) and any(
        alias.name == "backend.admin.notifications.models" for alias in node.names
    ) for node in tree.body)


def configure(monkeypatch):
    monkeypatch.setenv("REFRAQ_NOTIFICATION_REVIEWED_ORIGINS", json.dumps(ORIGINS))
    monkeypatch.setenv("REFRAQ_NOTIFICATION_DELIVERY", json.dumps(BUDGET))
    reset_settings_cache()
    assemble_system_parameters()
    ensure_system_schedules()


@pytest.mark.parametrize("field,value", [
    ("max_attempts_per_route", 0), ("max_attempts_per_route", True),
    ("retry_delays_seconds", []), ("retry_delays_seconds", [-1]),
    ("retry_delays_seconds", [float("inf")]),
    ("timeout_seconds", 0), ("timeout_seconds", float("nan")),
    ("batch_size", 0), ("interval_seconds", 0),
])
def test_explicit_budget_validation(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, REFRAQ_STORE_BACKEND="memory",
                 REFRAQ_NOTIFICATION_DELIVERY={**BUDGET, field: value})


@pytest.mark.parametrize("origin", [
    "http://primary.invalid", "https://primary.invalid/path?secret=hidden",
    "https://user:secret@primary.invalid", "https://primary.invalid:443",
])
def test_reviewed_policy_accepts_origins_not_routes(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, REFRAQ_STORE_BACKEND="memory",
                 REFRAQ_NOTIFICATION_REVIEWED_ORIGINS={origin: "reviewed"})


def test_deployment_defaults_are_unconfigured_and_repr_excludes_policy():
    settings = Settings(_env_file=None, REFRAQ_STORE_BACKEND="memory")
    assert settings.notification_reviewed_origins == {}
    assert settings.notification_delivery is None
    settings = Settings(_env_file=None, REFRAQ_STORE_BACKEND="memory",
                        REFRAQ_NOTIFICATION_REVIEWED_ORIGINS=ORIGINS,
                        REFRAQ_NOTIFICATION_DELIVERY=BUDGET)
    assert "primary.invalid" not in repr(settings)
    assert settings.notification_delivery.batch_size == 2


@pytest.mark.parametrize("missing", ["REFRAQ_NOTIFICATION_DELIVERY", "REFRAQ_NOTIFICATION_REVIEWED_ORIGINS"])
def test_absent_deployment_config_disables_duty_and_never_sends(monkeypatch, caplog, missing):
    configure(monkeypatch)
    monkeypatch.delenv(missing)
    reset_settings_cache()
    ensure_system_schedules()
    record = get_schedule_store().get_by_key(NOTIFICATION_SCHEDULE_KEY)
    assert not record.enabled and record.next_run_at is None
    send = Mock(side_effect=AssertionError("must not deliver"))
    transaction = Mock(side_effect=AssertionError("must not open database"))
    monkeypatch.setattr(tasks, "deliver_due", send)
    monkeypatch.setattr(tasks, "session_scope", transaction)
    assert tasks.deliver_notifications.run() == {
        "status": "blocked", "code": "NOTIFICATION_DEPLOYMENT_UNCONFIGURED",
    }
    assert "notification delivery blocked" in caplog.text
    assert "primary.invalid" not in caplog.text
    send.assert_not_called()
    transaction.assert_not_called()


def test_periodic_duty_is_hidden_locked_undeletable_store_only(monkeypatch):
    configure(monkeypatch)
    record = get_schedule_store().get_by_key(NOTIFICATION_SCHEDULE_KEY)
    assert record.hidden and record.locked and record.undeletable and record.store_only
    assert record.enabled and record.owner_ref is None
    assert record.interval_seconds == BUDGET["interval_seconds"]
    assert record.task_name == NOTIFICATION_TASK_NAME == tasks.deliver_notifications.name
    with pytest.raises(ScheduleSystemImmutable):
        patch_schedule(record.id, enabled=False)
    with pytest.raises(ScheduleUndeletable):
        delete_schedule(record.id)
    scheduler = DatabaseScheduler(app=tasks.deliver_notifications.app, lazy=True)
    entry = scheduler._load_entries()[NOTIFICATION_SCHEDULE_KEY]
    assert entry.task == NOTIFICATION_TASK_NAME
    assert entry.kwargs == {}
    ensure_system_schedules()
    assert get_schedule_store().get_by_key(NOTIFICATION_SCHEDULE_KEY).id == record.id


def test_worker_consumes_due_and_delivers_in_same_management_transaction(monkeypatch):
    configure(monkeypatch)
    session = object()
    committed = []

    @contextmanager
    def transaction():
        yield session
        committed.append(True)

    consume = Mock(return_value={"status": "system"})
    send = Mock(return_value=2)
    monkeypatch.setattr(tasks, "session_scope", transaction)
    monkeypatch.setattr(tasks, "consume_due_tick", consume)
    monkeypatch.setattr(tasks, "deliver_due", send)
    assert tasks.deliver_notifications.run() == {"status": "processed", "processed": 2}
    assert consume.call_args.kwargs["session"] is session
    assert send.call_args.args == (session,)
    assert dict(send.call_args.kwargs["policy"].origins) == ORIGINS
    assert send.call_args.kwargs["budget"].retry_delays_seconds == (3,)
    assert committed == [True]
    consume.return_value = {"status": "not_due"}
    send.reset_mock()
    assert tasks.deliver_notifications.run() == {"status": "not_due"}
    send.assert_not_called()


def test_main_mount_permissions_validation_redaction_and_empty_policy(monkeypatch):
    # No lifespan: authentication uses memory stores, HTTP database adapter is replaced.
    import backend.core.db as db_module

    role = RoleRecord(id="notification-role", key="notification-role", name="Notifications",
                      permissions=[], locked=False, created_at=0)
    get_role_store().insert(role)
    user = UserRecord(id="operator", account="operator", display_name="Operator",
                      role_id=role.id, status="active", password_hash="unused", created_at=0)

    session = Mock()
    monkeypatch.setattr(db_module, "get_session_factory", lambda: lambda: session)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        client = TestClient(app)
        for method, path in [("GET", "/settings/notification-channel"),
                             ("PUT", "/settings/notification-channel"),
                             ("POST", "/settings/notification-channel/test")]:
            result = client.request(method, path, json={} if method == "PUT" else None)
            assert result.status_code == 403
        role.permissions = ["settings:read"]
        get_role_store().save(role)
        session.get.return_value = None
        result = client.get("/settings/notification-channel")
        assert result.status_code == 200
        assert result.json()["channel"]["delivery_state"] == {"state": "unconfigured"}
        assert "https_url" not in result.text and "credential" not in result.text
        role.permissions = ["settings:write"]
        get_role_store().save(role)
        payload = {"primary": {"https_url": "https://secret.invalid/private-token", "credential": {
            "header_name": "Authorization", "secret": "hidden-credential"}},
            "fallback": {}, "responder": "operator"}
        result = client.put("/settings/notification-channel", json=payload)
        assert result.status_code == 422
        assert "private-token" not in result.text and "hidden-credential" not in result.text
        assert result.headers["content-type"].startswith("application/problem+json")
        payload["fallback"] = {"https_url": "https://fallback.invalid/hidden", "credential": {
            "header_name": "Authorization", "secret": "fallback-hidden"}}
        result = client.put("/settings/notification-channel", json=payload)
        assert result.status_code == 422
        assert result.json()["code"] == "NOTIFICATION_ROUTE_INVALID"
        assert "private-token" not in result.text and "hidden-credential" not in result.text
        session.scalar.assert_not_called()
        session.rollback.assert_called_once()
    finally:
        app.dependency_overrides.pop(get_current_user, None)
