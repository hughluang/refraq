"""Offline failure and HTTP adapter contracts."""

from contextlib import contextmanager
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.tests.test_notifications import config, notification_clock, policy, replace, session
from backend.admin.notifications.configuration import read_channel, request_route_test, ensure_routes_verified
from backend.admin.notifications.delivery import DeliveryBudget, deliver_due
from backend.admin.notifications.errors import NotificationDeliveryUnconfirmed
from backend.admin.notifications.models import NotificationEventRow
from backend.admin.notifications.service import enqueue_notification


@pytest.mark.parametrize("redirect", [False, True])
def test_persisted_bounded_retry_then_independent_fallback(session, policy, notification_clock, redirect):
    enqueued_at = notification_clock.now()
    replace(session, policy)
    enqueue_notification(session, event_id="episode-1", event_type="cdc.buffer_blocked",
        scope={"source_id": "source-1"}, evidence={"state": "blocked"}, severity="critical",
        responder="site-oncall", safe_action="inspect_buffer")
    session.commit()
    assert session.get(NotificationEventRow, "episode-1").next_attempt_at == enqueued_at
    seen = []
    def handler(request):
        seen.append(request.url.host)
        if request.url.host == "primary.invalid":
            if redirect:
                return httpx.Response(302, headers={"Location": "https://fallback.invalid/stolen"})
            raise httpx.ConnectError("https://primary.invalid/top-secret", request=request)
        assert request.headers.get("X-Api-Key") == "fallback-secret"
        assert "authorization" not in request.headers
        return httpx.Response(204)
    budget = DeliveryBudget(2, (10,), 1, 1)
    def tick():
        result = deliver_due(session, policy=policy, budget=budget, now=notification_clock.now(), transport=httpx.MockTransport(handler))
        session.commit()
        session.expire_all()
        return result
    assert tick() == 1
    row = session.get(NotificationEventRow, "episode-1")
    assert row.attempts == 1
    assert row.next_attempt_at == enqueued_at + timedelta(seconds=10)
    notification_clock.advance(timedelta(seconds=9))
    assert tick() == 0
    notification_clock.advance(timedelta(seconds=1))
    assert tick() == 1
    assert tick() == 1
    row = session.get(NotificationEventRow, "episode-1")
    assert row.state == "delivered"
    assert row.outcomes == {"primary": "failed", "fallback": "delivered"}
    assert [attempt["route"] for attempt in row.attempt_history] == ["primary", "primary", "fallback"]
    assert "top-secret" not in str(row.attempt_history)
    notification_clock.set(enqueued_at + timedelta(days=1))
    assert tick() == 0
    assert seen == ["primary.invalid", "primary.invalid", "fallback.invalid"]
    assert "top-secret" not in str(read_channel(session))


def test_failed_test_still_exercises_fallback_and_never_admits(session, policy, notification_clock):
    replace(session, policy)
    request_route_test(session, actor_user_id="operator", actor_token_id=None)
    session.commit()
    seen = []
    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(503, text="top-secret")
    budget = DeliveryBudget(1, (), 1, 1)
    for _ in range(2):
        deliver_due(session, policy=policy, budget=budget, now=notification_clock.now(), transport=httpx.MockTransport(handler))
        session.commit()
    assert seen == ["primary.invalid", "fallback.invalid"]
    assert read_channel(session)["channel"]["delivery_state"] == {"state": "failed", "primary": "failed", "fallback": "failed"}
    with pytest.raises(NotificationDeliveryUnconfirmed):
        ensure_routes_verified(session)


def test_configuration_change_invalidates_pending_test(session, policy, notification_clock):
    replace(session, policy)
    pending = request_route_test(session, actor_user_id="operator", actor_token_id=None)
    session.commit()
    replace(session, policy)
    session.commit()
    def handler(request):
        pytest.fail("Superseded tests must not deliver")
    deliver_due(session, policy=policy, budget=DeliveryBudget(1, (), 1, 1),
        now=notification_clock.now(), transport=httpx.MockTransport(handler))
    session.commit()
    assert session.get(NotificationEventRow, pending["operation_id"]).state == "failed"
    with pytest.raises(NotificationDeliveryUnconfirmed):
        ensure_routes_verified(session)


def test_router_enforces_settings_permissions_and_returns_pending(session, policy):
    from backend.admin.notifications.router import create_router
    from backend.admin.deps import get_current_user
    from backend.admin.role_store import get_role_store
    from backend.admin.user_store import UserRecord
    from backend.admin.role_store import RoleRecord
    @contextmanager
    def transaction():
        yield session
        session.commit()
    app = FastAPI()
    app.include_router(create_router(policy=policy, transaction=transaction))
    role = RoleRecord(id="role", key="notification-test", name="Notification test", permissions=["settings:read"], locked=False, created_at=0)
    get_role_store().insert(role)
    user = UserRecord(id="operator", account="operator", display_name="Operator", role_id="role", status="active", password_hash="unused", created_at=0)
    app.dependency_overrides[get_current_user] = lambda: user
    from backend.core.errors import AppError
    from fastapi.responses import JSONResponse
    @app.exception_handler(AppError)
    async def error(request, exc):
        return JSONResponse({"code": exc.code}, status_code=exc.http_status)
    client = TestClient(app)
    assert client.get("/settings/notification-channel").status_code == 200
    assert client.put("/settings/notification-channel", json=config()).status_code == 403
    assert client.post("/settings/notification-channel/test").status_code == 403
    role.permissions.append("settings:write")
    get_role_store().save(role)
    result = client.put("/settings/notification-channel", json=config())
    assert result.status_code == 200
    assert "top-secret" not in result.text
    pending = client.post("/settings/notification-channel/test")
    assert pending.status_code == 202
    assert pending.json()["state"] == "pending"
    assert client.get("/settings/notification-channel").json()["channel"]["delivery_state"]["state"] == "pending"
