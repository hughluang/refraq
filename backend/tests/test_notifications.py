"""Offline contracts for the Foundation notification boundary."""

from datetime import datetime, timezone
import json

import httpx
import pytest
from sqlalchemy import create_engine, select, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.admin.models import AuditEventRow
from backend.admin.notifications.configuration import (
    EgressPolicy, replace_channel, read_channel, request_route_test,
    ensure_routes_verified,
)
from backend.admin.notifications.models import NotificationChannelRow, NotificationEventRow
from backend.admin.notifications.errors import NotificationRouteInvalid, NotificationDeliveryUnconfirmed
from backend.core.time import FixedClock, reset_clock, set_clock


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(element, compiler, **kw):
    return "JSON"


@pytest.fixture(params=[
    pytest.param(datetime(2025, 11, 19, tzinfo=timezone.utc), id="2025-11-19"),
    pytest.param(datetime(2027, 11, 19, tzinfo=timezone.utc), id="2027-11-19"),
])
def notification_clock(request):
    clock = FixedClock(request.param)
    set_clock(clock)
    try:
        yield clock
    finally:
        reset_clock()


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "offline-notification-test-key")
    from backend.core.config import reset_settings_cache
    reset_settings_cache()
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def connect(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None
    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")
    for table in (AuditEventRow.__table__, NotificationChannelRow.__table__, NotificationEventRow.__table__):
        table.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def policy():
    return EgressPolicy({"https://primary.invalid": "primary-provider", "https://fallback.invalid": "fallback-provider"})


def config():
    return {"primary": {"https_url": "https://primary.invalid/secret-path?token=hidden", "credential": {"header_name": "Authorization", "secret": "Bearer top-secret"}}, "fallback": {"https_url": "https://fallback.invalid/other", "credential": {"header_name": "X-Api-Key", "secret": "fallback-secret"}}, "responder": "site-oncall"}


def replace(session, policy):
    return replace_channel(session, config(), policy=policy, actor_user_id="operator", actor_token_id=None)


def test_config_is_encrypted_projection_and_audit_are_redacted_and_atomic(session, policy):
    result = replace(session, policy)
    assert result["channel"]["configured"] is True
    assert result["channel"]["delivery_state"] == {"state": "untested", "primary": "untested", "fallback": "untested"}
    stored = session.get(NotificationChannelRow, "site")
    audit = session.scalar(select(AuditEventRow))
    for secret in ("primary.invalid", "secret-path", "top-secret", "fallback-secret"):
        assert secret not in stored.routes_ciphertext
        assert secret not in json.dumps(result)
        assert secret not in json.dumps(audit.detail)
    session.rollback()
    assert session.get(NotificationChannelRow, "site") is None
    assert session.scalar(select(AuditEventRow)) is None


@pytest.mark.parametrize("change", ["http", "header", "same-domain", "unapproved", "newline"])
def test_unapproved_or_unsafe_routes_rejected_without_secret_errors(session, policy, change):
    payload = config()
    if change == "http":
        payload["primary"]["https_url"] = "http://primary.invalid/top-secret"
    elif change == "header":
        payload["primary"]["credential"]["header_name"] = "Host"
    elif change == "same-domain":
        payload["fallback"]["https_url"] = "https://primary.invalid/other"
    elif change == "unapproved":
        payload["primary"]["https_url"] = "https://unknown.invalid/top-secret"
    else:
        payload["primary"]["credential"]["secret"] = "top-secret\r\nInjected: true"
    with pytest.raises(NotificationRouteInvalid) as exc:
        replace_channel(session, payload, policy=policy, actor_user_id="operator", actor_token_id=None)
    assert "top-secret" not in str(exc.value)
    assert session.get(NotificationChannelRow, "site") is None


def test_event_outbox_deduplicates_in_caller_transaction_and_rejects_raw_evidence(session):
    from backend.admin.notifications.service import enqueue_notification
    args = dict(event_id="episode-1", event_type="cdc.buffer_blocked", scope={"source_id": "source-1"},
        evidence={"history_epoch": "epoch_1", "observed_at": "2026-11-18T00:00:00Z", "state": "blocked", "observed": 42},
        severity="critical", responder="site-oncall", safe_action="inspect_buffer")
    first = enqueue_notification(session, **args)
    assert enqueue_notification(session, **args) == first
    assert len(session.scalars(select(NotificationEventRow)).all()) == 1
    session.rollback()
    assert session.scalars(select(NotificationEventRow)).all() == []
    args["evidence"] = {"exception": "password=top-secret"}
    with pytest.raises(NotificationRouteInvalid):
        enqueue_notification(session, **args)


def test_test_request_is_pending_until_both_routes_deliver(session, policy, notification_clock):
    from backend.admin.notifications.delivery import DeliveryBudget, deliver_due
    replace(session, policy)
    pending = request_route_test(session, actor_user_id="operator", actor_token_id=None)
    session.commit()
    assert session.get(NotificationEventRow, pending["operation_id"]).next_attempt_at == notification_clock.now()
    with pytest.raises(NotificationDeliveryUnconfirmed):
        ensure_routes_verified(session)
    seen = []
    def handler(request):
        seen.append((request.url.host, request.headers["idempotency-key"]))
        return httpx.Response(204)
    budget = DeliveryBudget(max_attempts_per_route=2, retry_delays_seconds=(10,), timeout_seconds=1, batch_size=1)
    deliver_due(session, policy=policy, budget=budget, now=notification_clock.now(), transport=httpx.MockTransport(handler))
    session.commit()
    assert read_channel(session)["channel"]["delivery_state"]["state"] == "pending"
    deliver_due(session, policy=policy, budget=budget, now=notification_clock.now(), transport=httpx.MockTransport(handler))
    session.commit()
    ensure_routes_verified(session)
    assert seen == [("primary.invalid", pending["operation_id"]), ("fallback.invalid", pending["operation_id"])]
    assert read_channel(session)["channel"]["delivery_state"] == {"state": "verified", "primary": "delivered", "fallback": "delivered"}
