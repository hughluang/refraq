"""Bounded outbox delivery adapter; composition supplies approved budgets and egress."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import math

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.admin.notifications.configuration import EgressPolicy, validate_routes
from backend.admin.notifications.errors import NotificationRouteInvalid
from backend.admin.notifications.models import NotificationChannelRow, NotificationEventRow
from backend.core.secrets import decrypt_secret, SecretsDecryptError, SecretsMasterKeyMissing
from backend.core.time import format_instant

__all__ = ["DeliveryBudget", "deliver_due"]


@dataclass(frozen=True)
class DeliveryBudget:
    max_attempts_per_route: int
    retry_delays_seconds: tuple[float, ...]
    timeout_seconds: float
    batch_size: int

    def __post_init__(self):
        if (self.max_attempts_per_route < 1 or self.batch_size < 1
                or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0
                or len(self.retry_delays_seconds) != self.max_attempts_per_route - 1
                or any(not math.isfinite(delay) or delay <= 0 for delay in self.retry_delays_seconds)):
            raise ValueError("An explicit bounded delivery budget is required")


def _send(route: dict, payload: dict, budget: DeliveryBudget, transport: httpx.BaseTransport | None) -> str | None:
    credential = route["credential"]
    try:
        with httpx.Client(verify=True, follow_redirects=False, trust_env=False,
                         timeout=budget.timeout_seconds, transport=transport) as client:
            with client.stream("POST", route["https_url"], json=payload, headers={
                credential["header_name"]: credential["secret"],
                "Idempotency-Key": payload["event_id"],
            }) as response:
                if 200 <= response.status_code < 300:
                    return None
                if 300 <= response.status_code < 400:
                    return "NOTIFICATION_REDIRECT_REJECTED"
                return "NOTIFICATION_REMOTE_REJECTED"
    except httpx.HTTPError:
        return "NOTIFICATION_TRANSPORT_FAILED"


def deliver_due(session: Session, *, policy: EgressPolicy, budget: DeliveryBudget,
                now: datetime, transport: httpx.BaseTransport | None = None) -> int:
    """Deliver at most one attempt per selected event, holding claims through caller commit.

    Remote acceptance is at-least-once: receivers must deduplicate Idempotency-Key
    across a crash after remote acceptance and before management commit.
    """
    channel = session.scalar(select(NotificationChannelRow).where(NotificationChannelRow.id == "site").with_for_update())
    events = session.scalars(select(NotificationEventRow).where(
        NotificationEventRow.state.in_(["pending", "retry", "blocked"]),
        NotificationEventRow.next_attempt_at <= now,
    ).order_by(NotificationEventRow.next_attempt_at, NotificationEventRow.id)
        .limit(budget.batch_size).with_for_update(skip_locked=True)).all()
    for event in events:
        if channel is None:
            event.state = "blocked"
            event.last_fault_code = "NOTIFICATION_UNCONFIGURED"
            event.next_attempt_at = now + timedelta(seconds=budget.timeout_seconds)
            continue
        if event.channel_revision is None:
            event.channel_revision = channel.revision
        if event.channel_revision != channel.revision:
            if event.kind == "test":
                event.state = "failed"
                event.last_fault_code = "NOTIFICATION_CONFIGURATION_CHANGED"
                continue
            event.channel_revision = channel.revision
            event.route = "primary"
            event.attempts = 0
            event.outcomes = {}
        fault = None
        try:
            routes = json.loads(decrypt_secret(channel.routes_ciphertext))
            validate_routes({**routes, "responder": channel.responder}, policy)
            fault = _send(routes[event.route], event.payload, budget, transport)
        except (NotificationRouteInvalid, SecretsDecryptError, SecretsMasterKeyMissing, ValueError, KeyError, TypeError):
            fault = "NOTIFICATION_CONFIGURATION_INVALID"
        event.attempts += 1
        event.attempt_history = [*(event.attempt_history or []), {
            "route": event.route, "attempt": event.attempts,
            "observed_at": format_instant(now), "fault_code": fault,
        }]
        event.last_fault_code = fault
        outcomes = dict(event.outcomes)
        if fault is None:
            outcomes[event.route] = "delivered"
        elif event.attempts >= budget.max_attempts_per_route:
            outcomes[event.route] = "failed"
        else:
            event.state = "retry"
            event.next_attempt_at = now + timedelta(seconds=budget.retry_delays_seconds[event.attempts - 1])
        finished_route = event.route in outcomes
        if finished_route:
            if event.route == "primary" and (event.kind == "test" or fault is not None):
                event.route = "fallback"
                event.attempts = 0
                event.state = "pending"
                event.next_attempt_at = now
            elif event.kind == "test":
                event.state = "delivered" if all(value == "delivered" for value in outcomes.values()) else "failed"
                if fault is None and event.state == "failed":
                    event.last_fault_code = next(
                        attempt["fault_code"] for attempt in reversed(event.attempt_history)
                        if attempt["fault_code"] is not None
                    )
            else:
                event.state = "delivered" if fault is None else "failed"
        event.outcomes = outcomes
        if event.kind == "test" and channel.test_operation_id == event.id:
            state = {"retry": "pending", "delivered": "verified"}.get(event.state, event.state)
            channel.last_fault_code = event.last_fault_code
            channel.delivery_state = {"state": state,
                "primary": outcomes.get("primary", "pending"), "fallback": outcomes.get("fallback", "pending")}
        elif event.kind == "event":
            channel.last_fault_code = fault
            state = dict(channel.delivery_state)
            state["last_event"] = {"event_id": event.id, "state": event.state,
                "route": event.route, "outcomes": outcomes, "last_fault_code": fault}
            channel.delivery_state = state
    session.flush()
    return len(events)
