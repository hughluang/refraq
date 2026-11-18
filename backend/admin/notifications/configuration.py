"""Encrypted site routing, admission proof and redacted configuration audit."""

from dataclasses import dataclass
import json
import re
from types import MappingProxyType
from uuid import uuid4
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.admin.audit import persist_audit_event
from backend.admin.notifications.errors import NotificationDeliveryUnconfirmed, NotificationRouteInvalid
from backend.admin.notifications.models import NotificationChannelRow, NotificationEventRow
from backend.core.secrets import encrypt_secret
from backend.core.time import utc_now

__all__ = ["EgressPolicy", "ensure_routes_verified"]

_RESERVED_HEADERS = frozenset({
    "host", "connection", "content-length", "content-type", "transfer-encoding",
    "te", "trailer", "upgrade", "proxy-authorization", "proxy-authenticate",
    "keep-alive", "idempotency-key", "accept", "accept-encoding", "cookie",
    "set-cookie", "forwarded", "via", "expect",
})


@dataclass(frozen=True)
class EgressPolicy:
    """Approved HTTPS origins mapped to independently assessed failure domains."""

    origins: dict[str, str]

    def __post_init__(self):
        object.__setattr__(self, "origins", MappingProxyType(dict(self.origins)))

    def destination(self, url: str) -> tuple[str, str]:
        try:
            parsed = urlsplit(url)
            port = parsed.port
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                    or parsed.password is not None or parsed.fragment
                    or any(ord(c) <= 32 or ord(c) >= 127 for c in url)
                    or "\\" in url):
                raise ValueError
            host = parsed.hostname.lower()
            if ":" in host:
                host = f"[{host}]"
            origin = f"https://{host}" + (f":{port}" if port and port != 443 else "")
            domain = self.origins.get(origin)
            if not domain:
                raise ValueError
            return origin, domain
        except (ValueError, TypeError):
            raise NotificationRouteInvalid() from None


def validate_routes(payload: dict, policy: EgressPolicy) -> dict:
    try:
        routes = {}
        domains = []
        origins = []
        for name in ("primary", "fallback"):
            route = payload[name]
            url = route["https_url"]
            credential = route["credential"]
            header = credential["header_name"]
            secret = credential["secret"]
            if (not isinstance(url, str) or len(url) > 4096
                    or not isinstance(header, str)
                    or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}", header)
                    or header.lower() in _RESERVED_HEADERS
                    or header.lower().startswith(("proxy-", "sec-", "x-forwarded-"))
                    or not isinstance(secret, str) or not secret.strip() or len(secret) > 8192
                    or any(ord(c) < 32 or ord(c) >= 127 for c in secret)):
                raise NotificationRouteInvalid()
            origin, domain = policy.destination(url)
            origins.append(origin)
            domains.append(domain)
            routes[name] = {"https_url": url, "credential": {"header_name": header, "secret": secret}}
        if origins[0] == origins[1] or domains[0] == domains[1]:
            raise NotificationRouteInvalid()
        responder = payload["responder"]
        if not isinstance(responder, str) or not re.fullmatch(r"[A-Za-z0-9_.:@+-]{1,128}", responder):
            raise NotificationRouteInvalid()
        return routes
    except (KeyError, TypeError):
        raise NotificationRouteInvalid() from None


def read_channel(session: Session) -> dict:
    row = session.get(NotificationChannelRow, "site")
    return {"channel": {
        "configured": row is not None,
        "primary_configured": row is not None,
        "fallback_configured": row is not None,
        "responder": row.responder if row else None,
        "delivery_state": row.delivery_state if row else {"state": "unconfigured"},
        "last_test_at": row.last_test_at if row else None,
        "last_fault_code": row.last_fault_code if row else None,
    }}


def replace_channel(session: Session, payload: dict, *, policy: EgressPolicy,
                    actor_user_id: str, actor_token_id: str | None) -> dict:
    routes = validate_routes(payload, policy)
    row = session.scalar(select(NotificationChannelRow).where(NotificationChannelRow.id == "site").with_for_update())
    if row is None:
        try:
            with session.begin_nested():
                row = NotificationChannelRow(id="site", revision=uuid4().hex,
                    routes_ciphertext=encrypt_secret(json.dumps(routes)), responder=payload["responder"],
                    delivery_state={})
                session.add(row)
                session.flush()
        except IntegrityError:
            row = session.scalar(select(NotificationChannelRow).where(NotificationChannelRow.id == "site").with_for_update())
    row.revision = uuid4().hex
    row.routes_ciphertext = encrypt_secret(json.dumps(routes))
    row.responder = payload["responder"]
    row.delivery_state = {"state": "untested", "primary": "untested", "fallback": "untested"}
    row.last_test_at = None
    row.last_fault_code = None
    row.test_operation_id = None
    persist_audit_event(session=session, actor_user_id=actor_user_id, actor_token_id=actor_token_id,
        resource_type="notification_channel", resource_id="site", action="notification_channel.replace",
        result="success", detail={"revision": row.revision, "primary_configured": True, "fallback_configured": True})
    return read_channel(session)


def request_route_test(session: Session, *, actor_user_id: str, actor_token_id: str | None) -> dict:
    row = session.scalar(select(NotificationChannelRow).where(NotificationChannelRow.id == "site").with_for_update())
    if row is None:
        raise NotificationRouteInvalid()
    operation_id = uuid4().hex
    row.test_operation_id = operation_id
    row.last_test_at = utc_now()
    row.delivery_state = {"state": "pending", "primary": "pending", "fallback": "pending"}
    session.add(NotificationEventRow(id=operation_id, dedup_key=operation_id,
        channel_revision=row.revision, kind="test", payload={"event_id": operation_id,
        "event_type": "notification.route_test", "responder": row.responder}, route="primary",
        state="pending", attempts=0, next_attempt_at=utc_now(), outcomes={}))
    persist_audit_event(session=session, actor_user_id=actor_user_id, actor_token_id=actor_token_id,
        resource_type="notification_channel", resource_id="site", action="notification_channel.test",
        result="success", detail={"operation_id": operation_id, "state": "pending"})
    session.flush()
    return {"operation_id": operation_id, "state": "pending"}


def ensure_routes_verified(session: Session) -> None:
    row = session.get(NotificationChannelRow, "site")
    if row is None or any(row.delivery_state.get(route) != "delivered" for route in ("primary", "fallback")):
        raise NotificationDeliveryUnconfirmed()
