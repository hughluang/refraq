"""Effective grants (R2) and the HMAC signed access context.

The token is ``base64(payload) || '.' || hex(hmac_sha256(secret, payload_bytes))``.
``acl.ctx_payload`` checks that form and accepts either of the two installed keys.
This module does not point Entity Data API reads at profile views.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from sqlalchemy import text

from backend.entity.access.combos import grant_reaches
from backend.entity.access.compiler import CompiledPolicy, Policy, context_attribute_keys
from backend.entity.access.facts import GrantSpec, Narrow, Person

__all__ = [
    "CONTEXT_TTL_SEC",
    "KeyRing",
    "SigningKey",
    "context_attrs",
    "effective_grants",
    "load_shared_ring",
    "issue_context",
    "sign_payload",
]

CONTEXT_TTL_SEC = 60
_PAYLOAD_KEYS = ("sub", "grants", "attrs", "rev", "exp", "req", "kid")


@dataclass(frozen=True, slots=True)
class SigningKey:
    kid: str
    secret: bytes


@dataclass(frozen=True, slots=True)
class KeyRing:
    """At most two keys. The last key signs; both verify (rotation)."""

    keys: tuple[SigningKey, ...]

    def current(self) -> SigningKey:
        if not self.keys:
            raise ValueError("signing key ring is empty")
        return self.keys[-1]

    def by_kid(self) -> dict[str, bytes]:
        return {item.kid: item.secret for item in self.keys}


def load_shared_ring(conn: object) -> KeyRing:
    """Read the newest acl signing key. The entity database is the source of truth."""
    row = conn.execute(text("SELECT kid, secret FROM acl.ensure_signing_key()")).one()  # type: ignore[union-attr]
    secret = row[1]
    if not isinstance(secret, bytes):
        secret = bytes(secret)
    return KeyRing((SigningKey(str(row[0]), secret),))


def effective_grants(
    policy: Policy,
    compiled: CompiledPolicy,
    person: Person,
    *,
    action: str,
    narrow: Narrow | None,
) -> tuple[GrantSpec, ...]:
    """R2: direct user, role, and group grants, minus broken, expired, and narrowed-out."""
    broken = frozenset(compiled.broken_grants)
    return tuple(
        grant
        for grant in policy.grants
        if grant_reaches(
            grant,
            person,
            action=action,
            narrow=narrow,
            now=policy.now,
            broken_grant_ids=broken,
        )
    )


def context_attrs(policy: Policy, person: Person) -> dict[str, Any]:
    """Subject values the compiled rules read, plus identity keys the restrictions need."""
    values = policy.subject_values.get(person.user_id, {})
    attrs: dict[str, Any] = {}
    for key in sorted(context_attribute_keys(policy)):
        if key == "__access_subject":
            attrs[key] = person.user_id
        elif key == "__access_role":
            attrs[key] = person.role_id
        elif key == "__access_groups":
            attrs[key] = list(person.group_ids)
        elif key in values:
            attrs[key] = _jsonable(values[key])
    return attrs


def issue_context(
    policy: Policy,
    compiled: CompiledPolicy,
    person: Person,
    ring: KeyRing,
    *,
    action: str,
    narrow: Narrow | None = None,
    request_id: str = "",
    now: datetime | None = None,
    ttl_sec: int = CONTEXT_TTL_SEC,
) -> str:
    """Sign ``{sub, grants, attrs, rev, exp, req, kid}`` with the ring's current key."""
    moment = now or datetime.now(timezone.utc)
    key = ring.current()
    grants = [grant.id for grant in effective_grants(
        policy, compiled, person, action=action, narrow=narrow
    )]
    payload = {
        "sub": person.user_id,
        "grants": grants,
        "attrs": context_attrs(policy, person),
        "rev": {policy.entity_id: int(policy.revision)},
        "exp": int(moment.timestamp()) + int(ttl_sec),
        "req": request_id,
        "kid": key.kid,
    }
    return sign_payload(payload, key.secret)


def sign_payload(payload: Mapping[str, Any], secret: bytes) -> str:
    body = _canonical(payload)
    digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return base64.b64encode(body).decode("ascii") + "." + digest


def _canonical(payload: Mapping[str, Any]) -> bytes:
    ordered = {key: payload[key] for key in _PAYLOAD_KEYS}
    return json.dumps(ordered, separators=(",", ":")).encode("utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else str(value)
    return value
