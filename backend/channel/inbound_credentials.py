"""Site-wide Inbound Credential catalog."""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import func, select

from backend.admin.audit import persist_audit_event
from backend.channel.errors import (
    ChannelRequestInvalid,
    InboundCredentialInUse,
    InboundCredentialNotFound,
)
from backend.channel.models import InboundCredentialRow
from backend.channel.store import get_channel_store
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.secrets import decrypt_secret, encrypt_secret
from backend.core.time import utc_now

__all__ = [
    "InboundCredentialRecord",
    "create_inbound_credential",
    "delete_inbound_credential",
    "get_inbound_credential",
    "get_inbound_credential_store",
    "list_inbound_credentials",
    "present",
    "reset_inbound_credential_store",
    "update_inbound_credential",
]


@dataclass
class InboundCredentialRecord:
    id: str
    name: str
    credential_type: str
    config: dict[str, Any]
    secret: str
    created_at: datetime
    updated_at: datetime


def new_inbound_credential_id() -> str:
    return f"icr_{uuid.uuid4().hex[:12]}"


def present(record: InboundCredentialRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "type": record.credential_type,
        "config": dict(record.config),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def list_inbound_credentials(
    *, q: str | None, limit: int, offset: int
) -> tuple[list[InboundCredentialRecord], int]:
    return get_inbound_credential_store().list_credentials(
        q=(q or "").strip() or None, limit=limit, offset=offset
    )


def get_inbound_credential(credential_id: str) -> InboundCredentialRecord:
    record = get_inbound_credential_store().get(credential_id)
    if record is None:
        raise InboundCredentialNotFound()
    return record


def create_inbound_credential(
    *,
    name: str,
    credential_type: str,
    secret: str,
    config: dict[str, Any],
    actor_user_id: str | None = None,
    actor_token_id: str | None = None,
) -> InboundCredentialRecord:
    parsed_type = _parse_type(credential_type)
    parsed_config = _parse_config(parsed_type, config)
    now = utc_now()
    record = InboundCredentialRecord(
        id=new_inbound_credential_id(),
        name=_clean_name(name),
        credential_type=parsed_type,
        config=parsed_config,
        secret=_parse_secret(secret),
        created_at=now,
        updated_at=now,
    )
    saved = get_inbound_credential_store().create(record)
    _audit(actor_user_id, actor_token_id, saved, "inbound_credential.create")
    return saved


def update_inbound_credential(
    *,
    credential_id: str,
    name: str | None,
    credential_type: str | None,
    type_set: bool,
    secret: str | None,
    secret_set: bool,
    config: dict[str, Any] | None,
    config_set: bool,
    actor_user_id: str | None = None,
    actor_token_id: str | None = None,
) -> InboundCredentialRecord:
    record = get_inbound_credential(credential_id)
    next_name = record.name if name is None else _clean_name(name)
    next_type = record.credential_type
    if type_set:
        next_type = _parse_type(credential_type)
    if config_set:
        next_config = _parse_config(next_type, config)
    elif next_type != record.credential_type:
        raise ChannelRequestInvalid("Changing type requires a config for that type")
    else:
        next_config = dict(record.config)
    next_secret = _parse_secret(secret) if secret_set else record.secret
    record.name = next_name
    record.credential_type = next_type
    record.config = next_config
    record.secret = next_secret
    record.updated_at = utc_now()
    saved = get_inbound_credential_store().save(record)
    _audit(actor_user_id, actor_token_id, saved, "inbound_credential.update")
    return saved


def delete_inbound_credential(
    *,
    credential_id: str,
    actor_user_id: str | None = None,
    actor_token_id: str | None = None,
) -> None:
    record = get_inbound_credential_store().get(credential_id)
    if record is None:
        raise InboundCredentialNotFound()
    if inbound_credential_referenced(credential_id):
        raise InboundCredentialInUse()
    if not get_inbound_credential_store().delete(credential_id):
        raise InboundCredentialNotFound()
    _audit(actor_user_id, actor_token_id, record, "inbound_credential.delete")


def inbound_credential_referenced(credential_id: str) -> bool:
    store = get_channel_store()
    offset = 0
    while True:
        rows, total = store.list_channels(q=None, active=None, limit=200, offset=offset)
        for row in rows:
            if _graph_uses(row.draft_graph, credential_id):
                return True
            version_offset = 0
            while True:
                versions, version_total = store.list_versions(
                    row.id, limit=200, offset=version_offset
                )
                for version in versions:
                    if _graph_uses(version.graph, credential_id):
                        return True
                version_offset += len(versions)
                if not versions or version_offset >= version_total:
                    break
        offset += len(rows)
        if not rows or offset >= total:
            return False


def _graph_uses(graph: dict[str, Any] | None, credential_id: str) -> bool:
    if not isinstance(graph, dict):
        return False
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return False
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "trigger.inbound":
            continue
        config = node.get("config")
        if isinstance(config, dict) and config.get("credential_id") == credential_id:
            return True
    return False


def _audit(
    actor_user_id: str | None,
    actor_token_id: str | None,
    record: InboundCredentialRecord,
    action: str,
) -> None:
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="inbound_credential",
        resource_id=record.id,
        action=action,
        result="success",
        detail={
            "name": record.name,
            "type": record.credential_type,
            "config": dict(record.config),
        },
    )


_HEADER = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_TOKEN_KEYS = frozenset({"location", "name"})
_HMAC_KEYS = frozenset({"signature_header", "encoding", "prefix", "timestamp_header"})


def _parse_type(value: object) -> str:
    if value not in {"token", "hmac_sha256"}:
        raise ChannelRequestInvalid("Type must be token or hmac_sha256")
    return str(value)


def _parse_secret(secret: object) -> str:
    if not isinstance(secret, str) or not 1 <= len(secret) <= 4096 or secret.strip() == "":
        raise ChannelRequestInvalid("Secret must be 1 to 4096 characters")
    return secret


def _parse_config(credential_type: str, config: object) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ChannelRequestInvalid("Config must be an object")
    if credential_type == "token":
        return _parse_token_config(config)
    return _parse_hmac_config(config)


def _parse_token_config(config: dict[str, Any]) -> dict[str, Any]:
    if set(config) != _TOKEN_KEYS:
        raise ChannelRequestInvalid("Token config requires location and name")
    location = config.get("location")
    if location not in {"header", "query"}:
        raise ChannelRequestInvalid("Token location must be header or query")
    if location == "header":
        name = _header_name(config.get("name"), "Header name must be a token of 1 to 128 characters")
    else:
        name = _query_name(config.get("name"))
    return {"location": location, "name": name}


def _parse_hmac_config(config: dict[str, Any]) -> dict[str, Any]:
    if not {"signature_header", "encoding"} <= set(config) <= _HMAC_KEYS:
        raise ChannelRequestInvalid("HMAC config requires signature_header and encoding")
    encoding = config.get("encoding")
    if encoding not in {"hex", "base64"}:
        raise ChannelRequestInvalid("HMAC encoding must be hex or base64")
    parsed: dict[str, Any] = {
        "signature_header": _header_name(
            config.get("signature_header"),
            "Signature header must be a token of 1 to 128 characters",
        ),
        "encoding": encoding,
    }
    if "prefix" in config and config.get("prefix") is not None:
        parsed["prefix"] = _plain_text(
            config.get("prefix"),
            "Prefix must be 1 to 128 characters without CR, LF, or NUL",
            128,
        )
    if "timestamp_header" in config and config.get("timestamp_header") is not None:
        parsed["timestamp_header"] = _header_name(
            config.get("timestamp_header"),
            "Timestamp header must be a token of 1 to 128 characters",
        )
    return parsed


def _header_name(value: object, message: str) -> str:
    if not isinstance(value, str) or _HEADER.fullmatch(value) is None or not 1 <= len(value) <= 128:
        raise ChannelRequestInvalid(message)
    return value


def _query_name(value: object) -> str:
    return _plain_text(
        value,
        "Query name must be 1 to 2048 characters without CR, LF, or NUL",
        2048,
    )


def _plain_text(value: object, message: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= limit
        or value.strip() == ""
        or any(char in value for char in ("\r", "\n", "\x00"))
    ):
        raise ChannelRequestInvalid(message)
    return value


def _clean_name(name: object) -> str:
    if not isinstance(name, str):
        raise ChannelRequestInvalid("Name must be 1 to 200 characters")
    cleaned = name.strip()
    if not cleaned or len(cleaned) > 200:
        raise ChannelRequestInvalid("Name must be 1 to 200 characters")
    return cleaned


@dataclass
class _SealedInboundCredential:
    id: str
    name: str
    credential_type: str
    config: dict[str, Any]
    secret_ciphertext: str
    created_at: datetime
    updated_at: datetime


def _seal(record: InboundCredentialRecord) -> _SealedInboundCredential:
    return _SealedInboundCredential(
        id=record.id,
        name=record.name,
        credential_type=record.credential_type,
        config=dict(record.config),
        secret_ciphertext=encrypt_secret(record.secret),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _open(sealed: _SealedInboundCredential) -> InboundCredentialRecord:
    return InboundCredentialRecord(
        id=sealed.id,
        name=sealed.name,
        credential_type=sealed.credential_type,
        config=dict(sealed.config),
        secret=decrypt_secret(sealed.secret_ciphertext),
        created_at=sealed.created_at,
        updated_at=sealed.updated_at,
    )


def _copy_sealed(sealed: _SealedInboundCredential) -> _SealedInboundCredential:
    return _SealedInboundCredential(
        id=sealed.id,
        name=sealed.name,
        credential_type=sealed.credential_type,
        config=dict(sealed.config),
        secret_ciphertext=sealed.secret_ciphertext,
        created_at=sealed.created_at,
        updated_at=sealed.updated_at,
    )


class MemoryInboundCredentialStore:
    def __init__(self) -> None:
        self._rows: dict[str, _SealedInboundCredential] = {}
        self._lock = threading.Lock()

    def create(self, record: InboundCredentialRecord) -> InboundCredentialRecord:
        sealed = _seal(record)
        with self._lock:
            self._rows[record.id] = _copy_sealed(sealed)
            return _open(_copy_sealed(sealed))

    def get(self, credential_id: str) -> InboundCredentialRecord | None:
        with self._lock:
            sealed = self._rows.get(credential_id)
            return None if sealed is None else _open(_copy_sealed(sealed))

    def list_credentials(
        self, *, q: str | None, limit: int, offset: int
    ) -> tuple[list[InboundCredentialRecord], int]:
        with self._lock:
            rows = list(self._rows.values())
        if q:
            folded = q.lower()
            rows = [row for row in rows if folded in row.name.lower()]
        rows.sort(key=lambda row: (row.created_at, row.id), reverse=True)
        total = len(rows)
        page = rows[offset : offset + limit]
        return [_open(_copy_sealed(row)) for row in page], total

    def save(self, record: InboundCredentialRecord) -> InboundCredentialRecord:
        sealed = _seal(record)
        with self._lock:
            if record.id not in self._rows:
                raise InboundCredentialNotFound()
            self._rows[record.id] = _copy_sealed(sealed)
            return _open(_copy_sealed(sealed))

    def delete(self, credential_id: str) -> bool:
        with self._lock:
            return self._rows.pop(credential_id, None) is not None


def _sealed_from_row(row: InboundCredentialRow) -> _SealedInboundCredential:
    return _SealedInboundCredential(
        id=row.id,
        name=row.name,
        credential_type=row.credential_type,
        config=dict(row.config),
        secret_ciphertext=row.secret_ciphertext,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlInboundCredentialStore:
    def create(self, record: InboundCredentialRecord) -> InboundCredentialRecord:
        sealed = _seal(record)
        with session_scope() as session:
            session.add(
                InboundCredentialRow(
                    id=sealed.id,
                    name=sealed.name,
                    credential_type=sealed.credential_type,
                    config=dict(sealed.config),
                    secret_ciphertext=sealed.secret_ciphertext,
                    created_at=sealed.created_at,
                    updated_at=sealed.updated_at,
                )
            )
            session.flush()
            return _open(sealed)

    def get(self, credential_id: str) -> InboundCredentialRecord | None:
        with session_scope() as session:
            row = session.get(InboundCredentialRow, credential_id)
            return None if row is None else _open(_sealed_from_row(row))

    def list_credentials(
        self, *, q: str | None, limit: int, offset: int
    ) -> tuple[list[InboundCredentialRecord], int]:
        with session_scope() as session:
            stmt = select(InboundCredentialRow)
            if q:
                stmt = stmt.where(InboundCredentialRow.name.icontains(q, autoescape=True))
            total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
            rows = session.scalars(
                stmt.order_by(
                    InboundCredentialRow.created_at.desc(),
                    InboundCredentialRow.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            ).all()
            return [_open(_sealed_from_row(row)) for row in rows], total

    def save(self, record: InboundCredentialRecord) -> InboundCredentialRecord:
        sealed = _seal(record)
        with session_scope() as session:
            row = session.get(InboundCredentialRow, record.id)
            if row is None:
                raise InboundCredentialNotFound()
            row.name = sealed.name
            row.credential_type = sealed.credential_type
            row.config = dict(sealed.config)
            row.secret_ciphertext = sealed.secret_ciphertext
            row.updated_at = sealed.updated_at
            session.flush()
            return _open(_sealed_from_row(row))

    def delete(self, credential_id: str) -> bool:
        with session_scope() as session:
            row = session.get(InboundCredentialRow, credential_id)
            if row is None:
                return False
            session.delete(row)
            return True


_memory_singleton: MemoryInboundCredentialStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_inbound_credential_store() -> MemoryInboundCredentialStore | SqlInboundCredentialStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryInboundCredentialStore()
            return _memory_singleton
    return SqlInboundCredentialStore()


def reset_inbound_credential_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_inbound_credential_store.cache_clear()
