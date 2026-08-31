"""Request-scoped MCP actor (User + PAT id). Not taken from tool arguments."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

from backend.admin.deps import resolve_pat_bearer
from backend.admin.errors import AuthPatInvalid, AuthUnauthenticated
from backend.admin.user_store import UserRecord

_actor: ContextVar[tuple[UserRecord, str] | None] = ContextVar(
    "refraq_mcp_actor", default=None
)


def set_mcp_actor(user: UserRecord, token_id: str) -> Token[tuple[UserRecord, str] | None]:
    return _actor.set((user, token_id))


def reset_mcp_actor(token: Token[tuple[UserRecord, str] | None]) -> None:
    _actor.reset(token)


def current_actor() -> tuple[UserRecord, str]:
    actor = _actor.get()
    if actor is None:
        raise AuthUnauthenticated()
    return actor


def actor_from_authorization_header(
    authorization: str | None,
) -> tuple[UserRecord, str]:
    """Resolve PAT from `Authorization: Bearer`. Missing/invalid → unauthenticated."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthUnauthenticated()
    secret = authorization.split(" ", 1)[1].strip()
    if not secret:
        raise AuthUnauthenticated()
    try:
        return resolve_pat_bearer(secret)
    except AuthPatInvalid as exc:
        raise AuthUnauthenticated() from exc


@contextmanager
def mcp_authorization(authorization: str) -> Iterator[tuple[UserRecord, str]]:
    """Bind the PAT actor for stdio and in-process tool calls."""
    user, token_id = actor_from_authorization_header(authorization)
    token = set_mcp_actor(user, token_id)
    try:
        yield user, token_id
    finally:
        reset_mcp_actor(token)
