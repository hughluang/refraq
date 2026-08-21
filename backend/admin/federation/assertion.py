"""Normalized external identity assertion."""

from __future__ import annotations

from dataclasses import dataclass

from backend.admin.federation.errors import SsoAssertionRejected
from backend.admin.federation.spec import SUBJECT_MAX_LEN


@dataclass(frozen=True)
class ExternalAssertion:
    issuer: str
    subject: str
    email: str | None
    display_name: str | None
    preferred_username: str | None
    groups: tuple[str, ...]
    groups_present: bool
    groups_overflow: bool
    claims: dict[str, object]


def require_subject(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SsoAssertionRejected("ID token subject is missing")
    if len(value) > SUBJECT_MAX_LEN or not value.isascii():
        raise SsoAssertionRejected("ID token subject is invalid")
    return value


def text_claim(claims: dict[str, object], name: str) -> str | None:
    value = claims.get(name)
    if isinstance(value, str) and value:
        return value
    return None
