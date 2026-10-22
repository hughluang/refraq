"""Site-wide Email Account catalog and SMTP delivery."""

from __future__ import annotations

import copy
import re
import smtplib
import ssl
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from functools import lru_cache
from typing import Any, Callable

from sqlalchemy import func, select

from backend.admin.audit import persist_audit_event
from backend.channel.errors import (
    ChannelRequestInvalid,
    EmailAccountInUse,
    EmailAccountNotFound,
)
from backend.channel.models import EmailAccountRow
from backend.channel.store import get_channel_store
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.secrets import decrypt_secret, encrypt_secret
from backend.core.time import utc_now

__all__ = [
    "Delivery",
    "EmailAccountRecord",
    "TEST_BODY",
    "TEST_SUBJECT",
    "create_email_account",
    "delete_email_account",
    "deliver",
    "get_email_account",
    "get_email_account_store",
    "list_email_accounts",
    "prepare_message",
    "set_opener",
    "test_email_account",
    "update_email_account",
]

_TIMEOUT_SEC = 30.0
_MAX_RECIPIENTS = 50
_MAX_SUBJECT = 998
_MAX_BODY_BYTES = 256 * 1024
_ATOM = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
_MAILBOX = re.compile(rf"^(?:{_ATOM})(?:\.{_ATOM})*@(?:{_ATOM})(?:\.{_ATOM})*$")
_ENCRYPTION = frozenset({"none", "starttls", "implicit_tls"})
TEST_SUBJECT = "refraq email test"
TEST_BODY = "This is a test message from refraq."

Opener = Callable[["EmailAccountRecord", ssl.SSLContext | None], Any]


class SmtpDeliveryError(Exception):
    pass


@dataclass
class EmailAccountRecord:
    id: str
    name: str
    host: str
    port: int
    encryption: str
    username: str | None
    password_ciphertext: str | None
    from_address: str
    tls_skip_verify: bool
    last_delivery_at: datetime | None
    last_delivery_ok: bool | None
    last_delivery_error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Delivery:
    ok: bool
    error: str | None


def _default_open(record: EmailAccountRecord, context: ssl.SSLContext | None) -> smtplib.SMTP:
    if record.encryption == "implicit_tls":
        return smtplib.SMTP_SSL(
            record.host,
            record.port,
            timeout=_TIMEOUT_SEC,
            context=context,
        )
    return smtplib.SMTP(record.host, record.port, timeout=_TIMEOUT_SEC)


_open: Opener = _default_open


def set_opener(opener: Opener) -> Opener:
    global _open
    previous = _open
    _open = opener
    return previous


def new_email_account_id() -> str:
    return f"eml_{uuid.uuid4().hex[:12]}"


def is_mailbox(value: str) -> bool:
    return len(value) <= 254 and _MAILBOX.fullmatch(value) is not None


def prepare_message(to_text: str, subject: str, body: str) -> list[str]:
    """Return recipients or raise SmtpDeliveryError before any connection."""
    if not isinstance(to_text, str) or not isinstance(subject, str) or not isinstance(body, str):
        raise SmtpDeliveryError("Email fields must be text")
    recipients = [part.strip() for part in re.split(r"[,;]", to_text) if part.strip()]
    if not recipients:
        raise SmtpDeliveryError("To must contain one mailbox")
    if len(recipients) > _MAX_RECIPIENTS:
        raise SmtpDeliveryError("To has more than 50 recipients")
    if any(not is_mailbox(item) for item in recipients):
        raise SmtpDeliveryError("To must be one or more mailboxes")
    if len(subject) > _MAX_SUBJECT:
        raise SmtpDeliveryError("Subject is longer than 998 characters")
    if len(body.encode()) > _MAX_BODY_BYTES:
        raise SmtpDeliveryError("Body is larger than 256 KiB")
    return recipients


def deliver(
    record: EmailAccountRecord,
    recipients: list[str],
    subject: str,
    body: str,
) -> Delivery:
    """Send one message and store the latest delivery result."""
    try:
        _transmit(record, recipients, subject, body)
        result = Delivery(ok=True, error=None)
    except Exception as exc:  # noqa: BLE001
        result = Delivery(ok=False, error=_short(str(exc) or "delivery failed"))
    get_email_account_store().note_delivery(
        record.id,
        at=utc_now(),
        ok=result.ok,
        error=None if result.ok else _short(result.error or "delivery failed"),
    )
    return result


def present(record: EmailAccountRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "host": record.host,
        "port": record.port,
        "encryption": record.encryption,
        "username": record.username,
        "password_set": record.password_ciphertext is not None,
        "from": record.from_address,
        "tls_skip_verify": record.tls_skip_verify,
        "last_delivery_at": record.last_delivery_at,
        "last_delivery_ok": record.last_delivery_ok,
        "last_delivery_error": record.last_delivery_error,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def list_email_accounts(
    *, q: str | None, limit: int, offset: int
) -> tuple[list[EmailAccountRecord], int]:
    return get_email_account_store().list_accounts(
        q=(q or "").strip() or None, limit=limit, offset=offset
    )


def get_email_account(account_id: str) -> EmailAccountRecord:
    record = get_email_account_store().get(account_id)
    if record is None:
        raise EmailAccountNotFound()
    return record


def create_email_account(
    *,
    name: str,
    host: str,
    port: int,
    encryption: str,
    username: str | None,
    password: str | None,
    from_address: str,
    tls_skip_verify: bool,
    actor_user_id: str,
    actor_token_id: str | None,
) -> EmailAccountRecord:
    now = utc_now()
    record = EmailAccountRecord(
        id=new_email_account_id(),
        name=_clean_name(name),
        host=_clean_host(host),
        port=port,
        encryption=_clean_encryption(encryption),
        username=_clean_username(username),
        password_ciphertext=_cipher(_clean_password(password)),
        from_address=_clean_mailbox(from_address, "From"),
        tls_skip_verify=bool(tls_skip_verify),
        last_delivery_at=None,
        last_delivery_ok=None,
        last_delivery_error=None,
        created_at=now,
        updated_at=now,
    )
    saved = get_email_account_store().create(record)
    _audit(actor_user_id, actor_token_id, saved.id, "email_account.create", {"name": saved.name})
    return saved


def update_email_account(
    *,
    account_id: str,
    name: str | None,
    host: str | None,
    port: int | None,
    encryption: str | None,
    username: str | None,
    username_set: bool,
    password: str | None,
    password_set: bool,
    from_address: str | None,
    tls_skip_verify: bool | None,
    actor_user_id: str,
    actor_token_id: str | None,
) -> EmailAccountRecord:
    record = get_email_account(account_id)
    if name is not None:
        record.name = _clean_name(name)
    if host is not None:
        record.host = _clean_host(host)
    if port is not None:
        record.port = port
    if encryption is not None:
        record.encryption = _clean_encryption(encryption)
    if username_set:
        record.username = _clean_username(username)
    if password_set:
        record.password_ciphertext = _cipher(_clean_password(password))
    if from_address is not None:
        record.from_address = _clean_mailbox(from_address, "From")
    if tls_skip_verify is not None:
        record.tls_skip_verify = bool(tls_skip_verify)
    record.updated_at = utc_now()
    saved = get_email_account_store().save(record)
    _audit(actor_user_id, actor_token_id, saved.id, "email_account.update", {"name": saved.name})
    return saved


def delete_email_account(
    *,
    account_id: str,
    actor_user_id: str,
    actor_token_id: str | None,
) -> None:
    if get_email_account_store().get(account_id) is None:
        raise EmailAccountNotFound()
    if email_account_referenced(account_id):
        raise EmailAccountInUse()
    if not get_email_account_store().delete(account_id):
        raise EmailAccountNotFound()
    _audit(actor_user_id, actor_token_id, account_id, "email_account.delete", {})


def test_email_account(
    *,
    account_id: str,
    to: str,
    actor_user_id: str,
    actor_token_id: str | None,
) -> tuple[EmailAccountRecord, Delivery]:
    record = get_email_account(account_id)
    mailbox = _clean_mailbox(to, "To")
    result = deliver(record, [mailbox], TEST_SUBJECT, TEST_BODY)
    saved = get_email_account(account_id)
    _audit(actor_user_id, actor_token_id, account_id, "email_account.test", {"ok": result.ok})
    return saved, result


def email_account_referenced(account_id: str) -> bool:
    store = get_channel_store()
    offset = 0
    while True:
        rows, total = store.list_channels(q=None, active=None, limit=200, offset=offset)
        for row in rows:
            if _graph_uses(row.draft_graph, account_id):
                return True
            version_offset = 0
            while True:
                versions, version_total = store.list_versions(
                    row.id, limit=200, offset=version_offset
                )
                for version in versions:
                    if _graph_uses(version.graph, account_id):
                        return True
                version_offset += len(versions)
                if not versions or version_offset >= version_total:
                    break
        offset += len(rows)
        if not rows or offset >= total:
            return False


def _graph_uses(graph: dict[str, Any] | None, account_id: str) -> bool:
    if not isinstance(graph, dict):
        return False
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "action.email":
            continue
        config = node.get("config") or {}
        if isinstance(config, dict) and config.get("email_account_id") == account_id:
            return True
    return False


def _transmit(
    record: EmailAccountRecord,
    recipients: list[str],
    subject: str,
    body: str,
) -> None:
    context = None if record.encryption == "none" else _ssl_context(record.tls_skip_verify)
    client = _open(record, context)
    try:
        client.ehlo()
        if record.encryption == "starttls":
            client.starttls(context=context)
            client.ehlo()
        if record.username:
            client.login(record.username, _password(record) or "")
        code, reply = client.mail(record.from_address)
        if code >= 400:
            _rset(client)
            raise SmtpDeliveryError(_reply_text(code, reply))
        for recipient in recipients:
            code, reply = client.rcpt(recipient)
            if code >= 400:
                _rset(client)
                raise SmtpDeliveryError(_reply_text(code, reply))
        code, reply = client.data(_message_bytes(record.from_address, recipients, subject, body))
        if code >= 400:
            raise SmtpDeliveryError(_reply_text(code, reply))
    finally:
        try:
            client.quit()
        except Exception:  # noqa: BLE001
            pass


def _message_bytes(sender: str, recipients: list[str], subject: str, body: str) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body, subtype="plain", charset="utf-8")
    return message.as_bytes()


def _ssl_context(skip_verify: bool) -> ssl.SSLContext:
    if skip_verify:
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def _rset(client: Any) -> None:
    try:
        client.rset()
    except Exception:  # noqa: BLE001
        return


def _reply_text(code: int, reply: Any) -> str:
    if isinstance(reply, bytes):
        text = reply.decode(errors="replace")
    else:
        text = str(reply)
    return f"SMTP {code} {text}".strip()


def _cipher(secret: str | None) -> str | None:
    if secret is None:
        return None
    return encrypt_secret(secret)


def _password(record: EmailAccountRecord) -> str | None:
    if record.password_ciphertext is None:
        return None
    return decrypt_secret(record.password_ciphertext)


def _clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or len(cleaned) > 200:
        raise ChannelRequestInvalid("Name must be 1 to 200 characters")
    return cleaned


def _clean_host(host: str) -> str:
    cleaned = host.strip()
    if not cleaned or len(cleaned) > 255 or any(char.isspace() for char in cleaned):
        raise ChannelRequestInvalid("Host must be 1 to 255 characters without whitespace")
    return cleaned


def _clean_encryption(encryption: str) -> str:
    if encryption not in _ENCRYPTION:
        raise ChannelRequestInvalid("Encryption must be none, starttls, or implicit_tls")
    return encryption


def _clean_username(username: str | None) -> str | None:
    if username is None:
        return None
    cleaned = username.strip()
    if not cleaned:
        return None
    if len(cleaned) > 200:
        raise ChannelRequestInvalid("Username must be 1 to 200 characters")
    return cleaned


def _clean_password(password: str | None) -> str | None:
    if password is None:
        return None
    if not 1 <= len(password) <= 512:
        raise ChannelRequestInvalid("Password must be 1 to 512 characters")
    return password


def _clean_mailbox(value: str, label: str) -> str:
    cleaned = value.strip()
    if not is_mailbox(cleaned):
        raise ChannelRequestInvalid(f"{label} must be one mailbox")
    return cleaned


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
        resource_type="email_account",
        resource_id=resource_id,
        action=action,
        result="success",
        detail=detail,
    )


class MemoryEmailAccountStore:
    def __init__(self) -> None:
        self._rows: dict[str, EmailAccountRecord] = {}
        self._lock = threading.Lock()

    def create(self, record: EmailAccountRecord) -> EmailAccountRecord:
        with self._lock:
            self._rows[record.id] = copy.copy(record)
            return copy.copy(record)

    def get(self, account_id: str) -> EmailAccountRecord | None:
        with self._lock:
            record = self._rows.get(account_id)
            return None if record is None else copy.copy(record)

    def list_accounts(
        self, *, q: str | None, limit: int, offset: int
    ) -> tuple[list[EmailAccountRecord], int]:
        with self._lock:
            rows = list(self._rows.values())
        if q:
            folded = q.lower()
            rows = [row for row in rows if folded in row.name.lower()]
        rows.sort(key=lambda row: (row.created_at, row.id), reverse=True)
        total = len(rows)
        return [copy.copy(row) for row in rows[offset : offset + limit]], total

    def save(self, record: EmailAccountRecord) -> EmailAccountRecord:
        with self._lock:
            if record.id not in self._rows:
                raise EmailAccountNotFound()
            self._rows[record.id] = copy.copy(record)
            return copy.copy(record)

    def note_delivery(
        self, account_id: str, *, at: datetime, ok: bool, error: str | None
    ) -> None:
        with self._lock:
            record = self._rows.get(account_id)
            if record is None:
                return
            record.last_delivery_at = at
            record.last_delivery_ok = ok
            record.last_delivery_error = error

    def delete(self, account_id: str) -> bool:
        with self._lock:
            return self._rows.pop(account_id, None) is not None


def _from_row(row: EmailAccountRow) -> EmailAccountRecord:
    return EmailAccountRecord(
        id=row.id,
        name=row.name,
        host=row.host,
        port=row.port,
        encryption=row.encryption,
        username=row.username,
        password_ciphertext=row.password_ciphertext,
        from_address=row.from_address,
        tls_skip_verify=bool(row.tls_skip_verify),
        last_delivery_at=row.last_delivery_at,
        last_delivery_ok=None if row.last_delivery_ok is None else bool(row.last_delivery_ok),
        last_delivery_error=row.last_delivery_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlEmailAccountStore:
    def create(self, record: EmailAccountRecord) -> EmailAccountRecord:
        with session_scope() as session:
            session.add(
                EmailAccountRow(
                    id=record.id,
                    name=record.name,
                    host=record.host,
                    port=record.port,
                    encryption=record.encryption,
                    username=record.username,
                    password_ciphertext=record.password_ciphertext,
                    from_address=record.from_address,
                    tls_skip_verify=record.tls_skip_verify,
                    last_delivery_at=record.last_delivery_at,
                    last_delivery_ok=record.last_delivery_ok,
                    last_delivery_error=record.last_delivery_error,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )
            session.flush()
            return copy.copy(record)

    def get(self, account_id: str) -> EmailAccountRecord | None:
        with session_scope() as session:
            row = session.get(EmailAccountRow, account_id)
            return None if row is None else _from_row(row)

    def list_accounts(
        self, *, q: str | None, limit: int, offset: int
    ) -> tuple[list[EmailAccountRecord], int]:
        with session_scope() as session:
            stmt = select(EmailAccountRow)
            if q:
                stmt = stmt.where(EmailAccountRow.name.icontains(q, autoescape=True))
            total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
            rows = session.scalars(
                stmt.order_by(EmailAccountRow.created_at.desc(), EmailAccountRow.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            return [_from_row(row) for row in rows], total

    def save(self, record: EmailAccountRecord) -> EmailAccountRecord:
        with session_scope() as session:
            row = session.get(EmailAccountRow, record.id)
            if row is None:
                raise EmailAccountNotFound()
            row.name = record.name
            row.host = record.host
            row.port = record.port
            row.encryption = record.encryption
            row.username = record.username
            row.password_ciphertext = record.password_ciphertext
            row.from_address = record.from_address
            row.tls_skip_verify = record.tls_skip_verify
            row.updated_at = record.updated_at
            session.flush()
            return _from_row(row)

    def note_delivery(
        self, account_id: str, *, at: datetime, ok: bool, error: str | None
    ) -> None:
        with session_scope() as session:
            row = session.get(EmailAccountRow, account_id)
            if row is None:
                return
            row.last_delivery_at = at
            row.last_delivery_ok = ok
            row.last_delivery_error = error

    def delete(self, account_id: str) -> bool:
        with session_scope() as session:
            row = session.get(EmailAccountRow, account_id)
            if row is None:
                return False
            session.delete(row)
            return True


_memory_singleton: MemoryEmailAccountStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_email_account_store() -> MemoryEmailAccountStore | SqlEmailAccountStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryEmailAccountStore()
            return _memory_singleton
    return SqlEmailAccountStore()
