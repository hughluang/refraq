"""Authenticated Foundation HTTP adapter assembled with approved egress."""

from collections.abc import Callable
from contextlib import AbstractContextManager

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.notifications.configuration import (
    EgressPolicy, read_channel, replace_channel, request_route_test,
)
from backend.admin.user_store import UserRecord
from backend.core.db import session_scope

__all__ = ["create_router"]


class CredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    header_name: str = Field(max_length=128)
    secret: SecretStr


class RouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    https_url: SecretStr
    credential: CredentialInput


class ChannelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary: RouteInput
    fallback: RouteInput
    responder: str = Field(max_length=128)


def create_router(*, policy: EgressPolicy,
                  transaction: Callable[[], AbstractContextManager[Session]] = session_scope) -> APIRouter:
    router = APIRouter(prefix="/settings/notification-channel", tags=["settings"])

    @router.get("")
    def get_channel(user: UserRecord = Depends(require_permission("settings:read"))) -> dict:
        with transaction() as session:
            return read_channel(session)

    @router.put("")
    def put_channel(payload: ChannelInput,
                    user: UserRecord = Depends(require_permission("settings:write")),
                    actor_token_id: str | None = Depends(get_actor_token_id)) -> dict:
        values = {"responder": payload.responder}
        for name in ("primary", "fallback"):
            route = getattr(payload, name)
            values[name] = {"https_url": route.https_url.get_secret_value(), "credential": {
                "header_name": route.credential.header_name,
                "secret": route.credential.secret.get_secret_value(),
            }}
        with transaction() as session:
            return replace_channel(session, values, policy=policy,
                actor_user_id=user.id, actor_token_id=actor_token_id)

    @router.post("/test", status_code=202)
    def test_channel(user: UserRecord = Depends(require_permission("settings:write")),
                     actor_token_id: str | None = Depends(get_actor_token_id)) -> dict:
        with transaction() as session:
            return request_route_test(session, actor_user_id=user.id, actor_token_id=actor_token_id)

    return router
