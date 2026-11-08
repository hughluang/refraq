"""Opaque continuation for one interactive history page.

The token is a position bound to the caller, the Entity, and the query.
It is not an authorization cache. The HMAC key is the access-context
signing key. The payload is not an access-context token, and it does not
use ``sign_payload``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from backend.core.time import utc_now
from backend.entity.access.context import CONTEXT_TTL_SEC, load_shared_ring
from backend.entity.entity_db import get_entity_engine
from backend.entity.errors import EntityRequestInvalid
from backend.entity.history.bounds import _blank

_CURSOR_KEYS = ("sub", "ent", "q", "pos", "exp", "kid")
_DIGEST_LEN = 64


@dataclass(frozen=True, slots=True)
class HistoryQuery:
    """Filters that bind a continuation. Blank strings are absent."""

    operation: str | None = None
    source: str | None = None
    subject: str | None = None
    row_identity: str | None = None
    occurred_from: str | None = None
    occurred_to: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _blank(self.operation))
        object.__setattr__(self, "source", _blank(self.source))
        object.__setattr__(self, "subject", _blank(self.subject))
        object.__setattr__(self, "row_identity", _blank(self.row_identity))
        object.__setattr__(self, "occurred_from", _blank(self.occurred_from))
        object.__setattr__(self, "occurred_to", _blank(self.occurred_to))

    def canonical(self) -> str:
        body = {
            "occurred_from": self.occurred_from,
            "occurred_to": self.occurred_to,
            "operation": self.operation,
            "row_identity": self.row_identity,
            "source": self.source,
            "subject": self.subject,
        }
        return json.dumps(body, separators=(",", ":"), sort_keys=True)


def issue_history_cursor(
    *,
    subject_id: str,
    entity_id: str,
    query: HistoryQuery,
    position: int,
) -> str:
    """Sign the seam continuation. ``position`` is passed back unchanged."""
    if isinstance(position, bool) or not isinstance(position, int) or position < 1:
        raise ValueError("history cursor position must be a sequence")
    key = _current_key()
    payload = {
        "sub": subject_id,
        "ent": entity_id,
        "q": query.canonical(),
        "pos": position,
        "exp": int(utc_now().timestamp()) + CONTEXT_TTL_SEC,
        "kid": key.kid,
    }
    return _token(payload, key.secret)


def open_history_cursor(
    token: str,
    *,
    subject_id: str,
    entity_id: str,
    query: HistoryQuery,
) -> int:
    """Return the continuation sequence, or reject the token.

    A blank, tampered, expired, or rebound token is ``422 REQUEST_INVALID``.
    The error does not name the position or say whether events exist.
    """
    if not isinstance(token, str) or token.strip() == "":
        raise EntityRequestInvalid()
    try:
        payload = _verified_payload(token.strip())
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise EntityRequestInvalid() from None
    if (
        payload["sub"] != subject_id
        or payload["ent"] != entity_id
        or payload["q"] != query.canonical()
    ):
        raise EntityRequestInvalid()
    exp = payload["exp"]
    if isinstance(exp, bool) or not isinstance(exp, int):
        raise EntityRequestInvalid()
    if exp <= int(utc_now().timestamp()):
        raise EntityRequestInvalid()
    pos = payload["pos"]
    if isinstance(pos, bool) or not isinstance(pos, int) or pos < 1:
        raise EntityRequestInvalid()
    return pos


def _current_key() -> Any:
    with get_entity_engine().begin() as conn:
        return load_shared_ring(conn).current()


def _secret(kid: object) -> bytes:
    if not isinstance(kid, str) or kid == "":
        raise EntityRequestInvalid()
    with get_entity_engine().begin() as conn:
        secret = load_shared_ring(conn).by_kid().get(kid)
    if secret is None:
        raise EntityRequestInvalid()
    return secret


def _verified_payload(token: str) -> dict[str, Any]:
    if token.count(".") != 1:
        raise EntityRequestInvalid()
    encoded, digest = token.split(".", 1)
    if len(digest) != _DIGEST_LEN:
        raise EntityRequestInvalid()
    try:
        body = base64.urlsafe_b64decode(_pad(encoded))
    except ValueError:
        raise EntityRequestInvalid() from None
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise EntityRequestInvalid()
    expected = hmac.new(_secret(payload.get("kid")), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, expected):
        raise EntityRequestInvalid()
    return {key: payload[key] for key in _CURSOR_KEYS}


def _token(payload: dict[str, Any], secret: bytes) -> str:
    body = json.dumps(
        {key: payload[key] for key in _CURSOR_KEYS}, separators=(",", ":")
    ).encode("utf-8")
    digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
    encoded = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
    return encoded + "." + digest


def _pad(value: str) -> str:
    return value + "=" * (-len(value) % 4)
