"""Site-wide Webhook catalog, address checks, and delivery."""

from __future__ import annotations

import copy
import ipaddress
import socket
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
from sqlalchemy import func, select

from backend.admin.audit import persist_audit_event
from backend.channel.errors import (
    ChannelRequestInvalid,
    WebhookInUse,
    WebhookNotFound,
    WebhookUrlRejected,
)
from backend.channel.models import WebhookRow
from backend.channel.store import get_channel_store
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.secrets import decrypt_secret, encrypt_secret
from backend.core.time import utc_now

__all__ = [
    "Delivery",
    "WebhookRecord",
    "create_webhook",
    "delete_webhook",
    "deliver",
    "get_webhook",
    "get_webhook_store",
    "list_webhooks",
    "set_poster",
    "set_resolver",
    "update_webhook",
]

_METADATA_HOSTS = frozenset({"metadata.google.internal"})
_TIMEOUT_SEC = 30.0

Resolver = Callable[..., list[Any]]
Poster = Callable[[str, Any, dict[str, str]], tuple[int, str | None]]


@dataclass
class WebhookRecord:
    id: str
    name: str
    url: str
    secret_ciphertext: str | None
    last_delivery_at: datetime | None
    last_delivery_ok: bool | None
    last_delivery_error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Delivery:
    ok: bool
    status_code: int | None
    error: str | None


def _default_resolve(host: str, port: int, family: int, socktype: int) -> list[Any]:
    return socket.getaddrinfo(host, port, family, socktype)


def _default_post(url: str, payload: Any, headers: dict[str, str]) -> tuple[int, str | None]:
    response = httpx.post(
        url,
        json=payload,
        headers=headers,
        timeout=_TIMEOUT_SEC,
        follow_redirects=False,
    )
    if response.status_code >= 400:
        return response.status_code, f"HTTP {response.status_code}"
    return response.status_code, None


_resolve: Resolver = _default_resolve
_poster: Poster = _default_post


def set_resolver(resolver: Resolver) -> Resolver:
    global _resolve
    previous = _resolve
    _resolve = resolver
    return previous


def set_poster(poster: Poster) -> Poster:
    global _poster
    previous = _poster
    _poster = poster
    return previous


def new_webhook_id() -> str:
    return f"whk_{uuid.uuid4().hex[:12]}"


def assert_webhook_url(url: str) -> None:
    """Refuse a URL that is not https or that names a blocked address."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise WebhookUrlRejected()
    host = parsed.hostname
    if not host or host.lower().rstrip(".") in _METADATA_HOSTS:
        raise WebhookUrlRejected()
    port = parsed.port or 443
    literal = _literal_ip(host)
    if literal is not None:
        _refuse_ip(literal)
        return
    try:
        found = _resolve(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError as exc:
        raise WebhookUrlRejected() from exc
    if not found:
        raise WebhookUrlRejected()
    for item in found:
        address = item[4][0]
        parsed_ip = _literal_ip(address)
        if parsed_ip is None:
            raise WebhookUrlRejected()
        _refuse_ip(parsed_ip)


def deliver(record: WebhookRecord, payload: Any) -> Delivery:
    """POST JSON and store the latest delivery result on the Webhook."""
    secret = _secret(record)
    try:
        assert_webhook_url(record.url)
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        status, error = _poster(record.url, payload, headers)
        result = Delivery(ok=error is None and status < 400, status_code=status, error=error)
    except WebhookUrlRejected:
        result = Delivery(ok=False, status_code=None, error="Webhook URL is not allowed")
    except Exception as exc:  # noqa: BLE001
        result = Delivery(ok=False, status_code=None, error=_short(str(exc)))
    get_webhook_store().note_delivery(
        record.id,
        at=utc_now(),
        ok=result.ok,
        error=None if result.ok else _short(result.error or "delivery failed"),
    )
    return result


def present(record: WebhookRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "url": record.url,
        "secret_set": record.secret_ciphertext is not None,
        "last_delivery_at": record.last_delivery_at,
        "last_delivery_ok": record.last_delivery_ok,
        "last_delivery_error": record.last_delivery_error,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def list_webhooks(
    *, q: str | None, limit: int, offset: int
) -> tuple[list[WebhookRecord], int]:
    return get_webhook_store().list_webhooks(q=(q or "").strip() or None, limit=limit, offset=offset)


def get_webhook(webhook_id: str) -> WebhookRecord:
    record = get_webhook_store().get(webhook_id)
    if record is None:
        raise WebhookNotFound()
    return record


def create_webhook(
    *,
    name: str,
    url: str,
    secret: str | None,
    actor_user_id: str,
    actor_token_id: str | None,
) -> WebhookRecord:
    assert_webhook_url(url)
    now = utc_now()
    record = WebhookRecord(
        id=new_webhook_id(),
        name=name.strip(),
        url=url,
        secret_ciphertext=_cipher(_clean_secret(secret)),
        last_delivery_at=None,
        last_delivery_ok=None,
        last_delivery_error=None,
        created_at=now,
        updated_at=now,
    )
    saved = get_webhook_store().create(record)
    _audit(actor_user_id, actor_token_id, saved.id, "webhook.create", {"name": saved.name})
    return saved


def update_webhook(
    *,
    webhook_id: str,
    name: str | None,
    url: str | None,
    secret: str | None,
    secret_set: bool,
    actor_user_id: str,
    actor_token_id: str | None,
) -> WebhookRecord:
    record = get_webhook(webhook_id)
    if name is not None:
        record.name = name.strip()
    if url is not None:
        assert_webhook_url(url)
        record.url = url
    if secret_set:
        record.secret_ciphertext = _cipher(_clean_secret(secret))
    record.updated_at = utc_now()
    saved = get_webhook_store().save(record)
    _audit(actor_user_id, actor_token_id, saved.id, "webhook.update", {"name": saved.name})
    return saved


def delete_webhook(
    *,
    webhook_id: str,
    actor_user_id: str,
    actor_token_id: str | None,
) -> None:
    if get_webhook_store().get(webhook_id) is None:
        raise WebhookNotFound()
    if webhook_referenced(webhook_id):
        raise WebhookInUse()
    if not get_webhook_store().delete(webhook_id):
        raise WebhookNotFound()
    _audit(actor_user_id, actor_token_id, webhook_id, "webhook.delete", {})


def test_webhook(
    *,
    webhook_id: str,
    actor_user_id: str,
    actor_token_id: str | None,
) -> tuple[WebhookRecord, Delivery]:
    record = get_webhook(webhook_id)
    result = deliver(record, {"event": "webhook.test", "webhook_id": webhook_id})
    saved = get_webhook(webhook_id)
    _audit(actor_user_id, actor_token_id, webhook_id, "webhook.test", {"ok": result.ok})
    return saved, result


def webhook_referenced(webhook_id: str) -> bool:
    store = get_channel_store()
    offset = 0
    while True:
        rows, total = store.list_channels(q=None, active=None, limit=200, offset=offset)
        for row in rows:
            if _graph_uses(row.draft_graph, webhook_id):
                return True
            version_offset = 0
            while True:
                versions, version_total = store.list_versions(
                    row.id, limit=200, offset=version_offset
                )
                for version in versions:
                    if _graph_uses(version.graph, webhook_id):
                        return True
                version_offset += len(versions)
                if not versions or version_offset >= version_total:
                    break
        offset += len(rows)
        if not rows or offset >= total:
            return False


def _graph_uses(graph: dict[str, Any] | None, webhook_id: str) -> bool:
    if not isinstance(graph, dict):
        return False
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "action.webhook":
            continue
        config = node.get("config") or {}
        if isinstance(config, dict) and config.get("webhook_id") == webhook_id:
            return True
    return False


def _clean_secret(secret: str | None) -> str | None:
    if secret is None:
        return None
    if not 1 <= len(secret) <= 512:
        raise ChannelRequestInvalid("Secret must be 1 to 512 characters")
    return secret


def _cipher(secret: str | None) -> str | None:
    if secret is None:
        return None
    return encrypt_secret(secret)


def _secret(record: WebhookRecord) -> str | None:
    if record.secret_ciphertext is None:
        return None
    return decrypt_secret(record.secret_ciphertext)


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _refuse_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise WebhookUrlRejected()


def _short(message: str) -> str:
    return message[:500]


def _audit(
    actor_user_id: str,
    actor_token_id: str | None,
    resource_id: str,
    action: str,
    detail: dict[str, Any],
) -> None:
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="webhook",
        resource_id=resource_id,
        action=action,
        result="success",
        detail=detail,
    )


class MemoryWebhookStore:
    def __init__(self) -> None:
        self._rows: dict[str, WebhookRecord] = {}
        self._lock = threading.Lock()

    def create(self, record: WebhookRecord) -> WebhookRecord:
        with self._lock:
            self._rows[record.id] = copy.copy(record)
            return copy.copy(record)

    def get(self, webhook_id: str) -> WebhookRecord | None:
        with self._lock:
            record = self._rows.get(webhook_id)
            return None if record is None else copy.copy(record)

    def list_webhooks(
        self, *, q: str | None, limit: int, offset: int
    ) -> tuple[list[WebhookRecord], int]:
        with self._lock:
            rows = list(self._rows.values())
        if q:
            folded = q.lower()
            rows = [row for row in rows if folded in row.name.lower()]
        rows.sort(key=lambda row: (row.created_at, row.id), reverse=True)
        total = len(rows)
        return [copy.copy(row) for row in rows[offset : offset + limit]], total

    def save(self, record: WebhookRecord) -> WebhookRecord:
        with self._lock:
            if record.id not in self._rows:
                raise WebhookNotFound()
            self._rows[record.id] = copy.copy(record)
            return copy.copy(record)

    def note_delivery(
        self, webhook_id: str, *, at: datetime, ok: bool, error: str | None
    ) -> None:
        with self._lock:
            record = self._rows.get(webhook_id)
            if record is None:
                return
            record.last_delivery_at = at
            record.last_delivery_ok = ok
            record.last_delivery_error = error

    def delete(self, webhook_id: str) -> bool:
        with self._lock:
            return self._rows.pop(webhook_id, None) is not None


def _from_row(row: WebhookRow) -> WebhookRecord:
    return WebhookRecord(
        id=row.id,
        name=row.name,
        url=row.url,
        secret_ciphertext=row.secret_ciphertext,
        last_delivery_at=row.last_delivery_at,
        last_delivery_ok=None if row.last_delivery_ok is None else bool(row.last_delivery_ok),
        last_delivery_error=row.last_delivery_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlWebhookStore:
    def create(self, record: WebhookRecord) -> WebhookRecord:
        with session_scope() as session:
            session.add(
                WebhookRow(
                    id=record.id,
                    name=record.name,
                    url=record.url,
                    secret_ciphertext=record.secret_ciphertext,
                    last_delivery_at=record.last_delivery_at,
                    last_delivery_ok=record.last_delivery_ok,
                    last_delivery_error=record.last_delivery_error,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )
            session.flush()
            return copy.copy(record)

    def get(self, webhook_id: str) -> WebhookRecord | None:
        with session_scope() as session:
            row = session.get(WebhookRow, webhook_id)
            return None if row is None else _from_row(row)

    def list_webhooks(
        self, *, q: str | None, limit: int, offset: int
    ) -> tuple[list[WebhookRecord], int]:
        with session_scope() as session:
            stmt = select(WebhookRow)
            if q:
                stmt = stmt.where(WebhookRow.name.icontains(q, autoescape=True))
            total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
            rows = session.scalars(
                stmt.order_by(WebhookRow.created_at.desc(), WebhookRow.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            return [_from_row(row) for row in rows], total

    def save(self, record: WebhookRecord) -> WebhookRecord:
        with session_scope() as session:
            row = session.get(WebhookRow, record.id)
            if row is None:
                raise WebhookNotFound()
            row.name = record.name
            row.url = record.url
            row.secret_ciphertext = record.secret_ciphertext
            row.updated_at = record.updated_at
            session.flush()
            return _from_row(row)

    def note_delivery(
        self, webhook_id: str, *, at: datetime, ok: bool, error: str | None
    ) -> None:
        with session_scope() as session:
            row = session.get(WebhookRow, webhook_id)
            if row is None:
                return
            row.last_delivery_at = at
            row.last_delivery_ok = ok
            row.last_delivery_error = error

    def delete(self, webhook_id: str) -> bool:
        with session_scope() as session:
            row = session.get(WebhookRow, webhook_id)
            if row is None:
                return False
            session.delete(row)
            return True


_memory_singleton: MemoryWebhookStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_webhook_store() -> MemoryWebhookStore | SqlWebhookStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryWebhookStore()
            return _memory_singleton
    return SqlWebhookStore()
