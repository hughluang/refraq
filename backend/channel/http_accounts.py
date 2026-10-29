"""Site-wide HTTP Account catalog."""

from __future__ import annotations

import json
import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import func, select

from backend.admin.audit import persist_audit_event
from backend.channel.errors import (
    ChannelRequestInvalid,
    HttpAccountInUse,
    HttpAccountNotFound,
)
from backend.channel.models import HttpAccountRow
from backend.channel.store import get_channel_store
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.secrets import decrypt_secret, encrypt_secret
from backend.core.time import utc_now

__all__ = [
    "HttpAccountRecord",
    "create_http_account",
    "delete_http_account",
    "get_http_account",
    "get_http_account_store",
    "list_http_accounts",
    "present",
    "reset_http_account_store",
    "update_http_account",
]

_MAX_LIST = 32
_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_FORBIDDEN_HEADERS = frozenset(
    {
        "authorization",
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "upgrade",
        "te",
        "trailer",
        "proxy-authorization",
        "proxy-connection",
    }
)
_ORIGIN_MESSAGE = (
    "Allowed origin must be an absolute http or https URL "
    "with no userinfo, query, fragment, or path"
)


@dataclass
class HttpAccountRecord:
    id: str
    name: str
    auth_type: str
    username: str | None
    secret: str | None
    headers: list[tuple[str, str]]
    query: list[tuple[str, str]]
    allowed_origins: list[str]
    created_at: datetime
    updated_at: datetime


@dataclass
class _SealedHttpAccount:
    id: str
    name: str
    auth_type: str
    username: str | None
    secret_ciphertext: str | None
    headers_ciphertext: str
    query_ciphertext: str
    allowed_origins: list[str]
    created_at: datetime
    updated_at: datetime


def new_http_account_id() -> str:
    return f"hac_{uuid.uuid4().hex[:12]}"


def present(record: HttpAccountRecord) -> dict[str, Any]:
    auth: dict[str, Any] = {"type": record.auth_type}
    if record.auth_type == "basic":
        auth["username"] = record.username
    return {
        "id": record.id,
        "name": record.name,
        "auth": auth,
        "headers": [{"name": name} for name, _value in record.headers],
        "query": [{"name": name} for name, _value in record.query],
        "allowed_origins": list(record.allowed_origins),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def list_http_accounts(
    *, q: str | None, limit: int, offset: int
) -> tuple[list[HttpAccountRecord], int]:
    return get_http_account_store().list_accounts(
        q=(q or "").strip() or None, limit=limit, offset=offset
    )


def get_http_account(account_id: str) -> HttpAccountRecord:
    record = get_http_account_store().get(account_id)
    if record is None:
        raise HttpAccountNotFound()
    return record


def create_http_account(
    *,
    name: str,
    auth: dict[str, Any] | None,
    headers: list[dict[str, Any]] | None,
    query: list[dict[str, Any]] | None,
    allowed_origins: list[str] | None,
    actor_user_id: str,
    actor_token_id: str | None,
) -> HttpAccountRecord:
    auth_type, username, secret = ("none", None, None) if auth is None else _parse_auth(auth)
    now = utc_now()
    record = HttpAccountRecord(
        id=new_http_account_id(),
        name=_clean_name(name),
        auth_type=auth_type,
        username=username,
        secret=secret,
        headers=_parse_headers([] if headers is None else headers),
        query=_parse_query([] if query is None else query),
        allowed_origins=_parse_origins([] if allowed_origins is None else allowed_origins),
        created_at=now,
        updated_at=now,
    )
    saved = get_http_account_store().create(record)
    _audit(actor_user_id, actor_token_id, saved, "http_account.create")
    return saved


def update_http_account(
    *,
    account_id: str,
    name: str | None,
    auth: dict[str, Any] | None,
    auth_set: bool,
    headers: list[dict[str, Any]] | None,
    headers_set: bool,
    query: list[dict[str, Any]] | None,
    query_set: bool,
    allowed_origins: list[str] | None,
    origins_set: bool,
    actor_user_id: str,
    actor_token_id: str | None,
) -> HttpAccountRecord:
    record = get_http_account(account_id)
    if name is not None:
        record.name = _clean_name(name)
    if auth_set:
        if auth is None:
            raise ChannelRequestInvalid("Auth must be an object")
        record.auth_type, record.username, record.secret = _parse_auth(auth)
    if headers_set:
        if headers is None:
            raise ChannelRequestInvalid("Headers must be a list")
        record.headers = _parse_headers(headers)
    if query_set:
        if query is None:
            raise ChannelRequestInvalid("Query must be a list")
        record.query = _parse_query(query)
    if origins_set:
        if allowed_origins is None:
            raise ChannelRequestInvalid("Allowed origins must be a list")
        record.allowed_origins = _parse_origins(allowed_origins)
    record.updated_at = utc_now()
    saved = get_http_account_store().save(record)
    _audit(actor_user_id, actor_token_id, saved, "http_account.update")
    return saved


def delete_http_account(
    *,
    account_id: str,
    actor_user_id: str,
    actor_token_id: str | None,
) -> None:
    record = get_http_account_store().get(account_id)
    if record is None:
        raise HttpAccountNotFound()
    if http_account_referenced(account_id):
        raise HttpAccountInUse()
    if not get_http_account_store().delete(account_id):
        raise HttpAccountNotFound()
    _audit(actor_user_id, actor_token_id, record, "http_account.delete")


def http_account_referenced(account_id: str) -> bool:
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
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return False
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "action.http":
            continue
        config = node.get("config")
        if isinstance(config, dict) and config.get("http_account_id") == account_id:
            return True
    return False


def _parse_auth(auth: dict[str, Any]) -> tuple[str, str | None, str | None]:
    if not isinstance(auth, dict):
        raise ChannelRequestInvalid("Auth must be an object")
    auth_type = auth.get("type")
    if auth_type == "none":
        if any(key in auth for key in ("token", "username", "password")):
            raise ChannelRequestInvalid("Auth none must not include a secret or username")
        return "none", None, None
    if auth_type == "bearer":
        if any(key in auth for key in ("username", "password")):
            raise ChannelRequestInvalid("Bearer auth must not include a username or password")
        return "bearer", None, _clean_token(auth.get("token"))
    if auth_type == "basic":
        if "token" in auth:
            raise ChannelRequestInvalid("Basic auth must not include a token")
        return "basic", _clean_username(auth.get("username")), _clean_password(auth.get("password"))
    raise ChannelRequestInvalid("Auth type must be none, bearer, or basic")


def _clean_name(name: object) -> str:
    if not isinstance(name, str):
        raise ChannelRequestInvalid("Name must be 1 to 200 characters")
    cleaned = name.strip()
    if not cleaned or len(cleaned) > 200:
        raise ChannelRequestInvalid("Name must be 1 to 200 characters")
    return cleaned


def _clean_token(token: object) -> str:
    if not isinstance(token, str) or not 1 <= len(token) <= 4096:
        raise ChannelRequestInvalid("Bearer token must be 1 to 4096 characters")
    return token


def _clean_username(username: object) -> str:
    if (
        not isinstance(username, str)
        or not 1 <= len(username) <= 256
        or ":" in username
        or any(unicodedata.category(char) == "Cc" for char in username)
    ):
        raise ChannelRequestInvalid(
            "Basic username must be 1 to 256 characters with no colon or control character"
        )
    return username


def _clean_password(password: object) -> str:
    if not isinstance(password, str) or not 1 <= len(password) <= 1024:
        raise ChannelRequestInvalid("Basic password must be 1 to 1024 characters")
    return password


def _parse_headers(headers: list[dict[str, Any]]) -> list[tuple[str, str]]:
    if not isinstance(headers, list) or len(headers) > _MAX_LIST:
        raise ChannelRequestInvalid("At most 32 static headers are allowed")
    parsed: list[tuple[str, str]] = []
    for item in headers:
        if not isinstance(item, dict):
            raise ChannelRequestInvalid("Header name must be a token of 1 to 128 characters")
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or _TOKEN.fullmatch(name) is None or not 1 <= len(name) <= 128:
            raise ChannelRequestInvalid("Header name must be a token of 1 to 128 characters")
        if name.lower() in _FORBIDDEN_HEADERS:
            raise ChannelRequestInvalid("Static header name is not allowed")
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= 4096
            or any(char in value for char in ("\r", "\n", "\x00"))
        ):
            raise ChannelRequestInvalid(
                "Header value must be 1 to 4096 characters without CR, LF, or NUL"
            )
        parsed.append((name, value))
    return parsed


def _parse_query(query: list[dict[str, Any]]) -> list[tuple[str, str]]:
    if not isinstance(query, list) or len(query) > _MAX_LIST:
        raise ChannelRequestInvalid("At most 32 secret query parameters are allowed")
    parsed: list[tuple[str, str]] = []
    for item in query:
        if not isinstance(item, dict):
            raise ChannelRequestInvalid("Query name must be 1 to 2048 characters")
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or not 1 <= len(name) <= 2048:
            raise ChannelRequestInvalid("Query name must be 1 to 2048 characters")
        if not isinstance(value, str) or not 1 <= len(value) <= 2048:
            raise ChannelRequestInvalid("Query value must be 1 to 2048 characters")
        parsed.append((name, value))
    return parsed


def _parse_origins(origins: list[str]) -> list[str]:
    if not isinstance(origins, list) or len(origins) > _MAX_LIST:
        raise ChannelRequestInvalid("At most 32 allowed origins are allowed")
    return [_normalize_origin(item) for item in origins]


def _normalize_origin(value: object) -> str:
    from urllib.parse import urlsplit

    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ChannelRequestInvalid(_ORIGIN_MESSAGE)
    if any(char in value for char in ("?", "#", "@")):
        raise ChannelRequestInvalid(_ORIGIN_MESSAGE)
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise ChannelRequestInvalid(_ORIGIN_MESSAGE) from None
    if parts.scheme not in {"http", "https"} or not host:
        raise ChannelRequestInvalid(_ORIGIN_MESSAGE)
    if parts.path not in {"", "/"}:
        raise ChannelRequestInvalid(_ORIGIN_MESSAGE)
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    if not 1 <= port <= 65535:
        raise ChannelRequestInvalid(_ORIGIN_MESSAGE)
    shown = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{shown}:{port}"


def _audit(
    actor_user_id: str,
    actor_token_id: str | None,
    record: HttpAccountRecord,
    action: str,
) -> None:
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="http_account",
        resource_id=record.id,
        action=action,
        result="success",
        detail={
            "name": record.name,
            "auth_type": record.auth_type,
            "username": record.username,
            "header_names": [name for name, _value in record.headers],
            "query_names": [name for name, _value in record.query],
            "allowed_origins": list(record.allowed_origins),
        },
    )


def _seal_pairs(pairs: list[tuple[str, str]]) -> str:
    payload = [{"name": name, "value": value} for name, value in pairs]
    return encrypt_secret(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _open_pairs(ciphertext: str) -> list[tuple[str, str]]:
    payload = json.loads(decrypt_secret(ciphertext))
    return [(item["name"], item["value"]) for item in payload]


def _seal(record: HttpAccountRecord) -> _SealedHttpAccount:
    return _SealedHttpAccount(
        id=record.id,
        name=record.name,
        auth_type=record.auth_type,
        username=record.username,
        secret_ciphertext=None if record.secret is None else encrypt_secret(record.secret),
        headers_ciphertext=_seal_pairs(record.headers),
        query_ciphertext=_seal_pairs(record.query),
        allowed_origins=list(record.allowed_origins),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _open(sealed: _SealedHttpAccount) -> HttpAccountRecord:
    return HttpAccountRecord(
        id=sealed.id,
        name=sealed.name,
        auth_type=sealed.auth_type,
        username=sealed.username,
        secret=None if sealed.secret_ciphertext is None else decrypt_secret(sealed.secret_ciphertext),
        headers=_open_pairs(sealed.headers_ciphertext),
        query=_open_pairs(sealed.query_ciphertext),
        allowed_origins=list(sealed.allowed_origins),
        created_at=sealed.created_at,
        updated_at=sealed.updated_at,
    )


def _copy_sealed(sealed: _SealedHttpAccount) -> _SealedHttpAccount:
    return _SealedHttpAccount(
        id=sealed.id,
        name=sealed.name,
        auth_type=sealed.auth_type,
        username=sealed.username,
        secret_ciphertext=sealed.secret_ciphertext,
        headers_ciphertext=sealed.headers_ciphertext,
        query_ciphertext=sealed.query_ciphertext,
        allowed_origins=list(sealed.allowed_origins),
        created_at=sealed.created_at,
        updated_at=sealed.updated_at,
    )


class MemoryHttpAccountStore:
    def __init__(self) -> None:
        self._rows: dict[str, _SealedHttpAccount] = {}
        self._lock = threading.Lock()

    def create(self, record: HttpAccountRecord) -> HttpAccountRecord:
        sealed = _seal(record)
        with self._lock:
            self._rows[record.id] = _copy_sealed(sealed)
            return _open(_copy_sealed(sealed))

    def get(self, account_id: str) -> HttpAccountRecord | None:
        with self._lock:
            sealed = self._rows.get(account_id)
            return None if sealed is None else _open(_copy_sealed(sealed))

    def list_accounts(
        self, *, q: str | None, limit: int, offset: int
    ) -> tuple[list[HttpAccountRecord], int]:
        with self._lock:
            rows = list(self._rows.values())
        if q:
            folded = q.lower()
            rows = [row for row in rows if folded in row.name.lower()]
        rows.sort(key=lambda row: (row.created_at, row.id), reverse=True)
        total = len(rows)
        page = rows[offset : offset + limit]
        return [_open(_copy_sealed(row)) for row in page], total

    def save(self, record: HttpAccountRecord) -> HttpAccountRecord:
        sealed = _seal(record)
        with self._lock:
            if record.id not in self._rows:
                raise HttpAccountNotFound()
            self._rows[record.id] = _copy_sealed(sealed)
            return _open(_copy_sealed(sealed))

    def delete(self, account_id: str) -> bool:
        with self._lock:
            return self._rows.pop(account_id, None) is not None


def _sealed_from_row(row: HttpAccountRow) -> _SealedHttpAccount:
    return _SealedHttpAccount(
        id=row.id,
        name=row.name,
        auth_type=row.auth_type,
        username=row.username,
        secret_ciphertext=row.secret_ciphertext,
        headers_ciphertext=row.headers_ciphertext,
        query_ciphertext=row.query_ciphertext,
        allowed_origins=list(row.allowed_origins),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlHttpAccountStore:
    def create(self, record: HttpAccountRecord) -> HttpAccountRecord:
        sealed = _seal(record)
        with session_scope() as session:
            session.add(
                HttpAccountRow(
                    id=sealed.id,
                    name=sealed.name,
                    auth_type=sealed.auth_type,
                    username=sealed.username,
                    secret_ciphertext=sealed.secret_ciphertext,
                    headers_ciphertext=sealed.headers_ciphertext,
                    query_ciphertext=sealed.query_ciphertext,
                    allowed_origins=list(sealed.allowed_origins),
                    created_at=sealed.created_at,
                    updated_at=sealed.updated_at,
                )
            )
            session.flush()
            return _open(sealed)

    def get(self, account_id: str) -> HttpAccountRecord | None:
        with session_scope() as session:
            row = session.get(HttpAccountRow, account_id)
            return None if row is None else _open(_sealed_from_row(row))

    def list_accounts(
        self, *, q: str | None, limit: int, offset: int
    ) -> tuple[list[HttpAccountRecord], int]:
        with session_scope() as session:
            stmt = select(HttpAccountRow)
            if q:
                stmt = stmt.where(HttpAccountRow.name.icontains(q, autoescape=True))
            total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
            rows = session.scalars(
                stmt.order_by(HttpAccountRow.created_at.desc(), HttpAccountRow.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            return [_open(_sealed_from_row(row)) for row in rows], total

    def save(self, record: HttpAccountRecord) -> HttpAccountRecord:
        sealed = _seal(record)
        with session_scope() as session:
            row = session.get(HttpAccountRow, record.id)
            if row is None:
                raise HttpAccountNotFound()
            row.name = sealed.name
            row.auth_type = sealed.auth_type
            row.username = sealed.username
            row.secret_ciphertext = sealed.secret_ciphertext
            row.headers_ciphertext = sealed.headers_ciphertext
            row.query_ciphertext = sealed.query_ciphertext
            row.allowed_origins = list(sealed.allowed_origins)
            row.updated_at = sealed.updated_at
            session.flush()
            return _open(_sealed_from_row(row))

    def delete(self, account_id: str) -> bool:
        with session_scope() as session:
            row = session.get(HttpAccountRow, account_id)
            if row is None:
                return False
            session.delete(row)
            return True


_memory_singleton: MemoryHttpAccountStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_http_account_store() -> MemoryHttpAccountStore | SqlHttpAccountStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryHttpAccountStore()
            return _memory_singleton
    return SqlHttpAccountStore()


def reset_http_account_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_http_account_store.cache_clear()

