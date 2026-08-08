"""Account Center router implementing docs/api-contracts-account.md."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.admin.deps import get_current_user
from backend.admin.errors import (
    AccountInvalidDisplayName,
    AccountInvalidLocale,
    AccountPasswordInvalid,
    AccountPasswordNotLocal,
    AccountPasswordSessionRequired,
    AccountProfileEmpty,
)
from backend.admin.locales import is_supported_locale
from backend.admin.security import hash_password, verify_password
from backend.admin.user_payload import build_current_user
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.session_store import SessionStore, get_session_store
from backend.admin.user_store import UserRecord, UserStore, get_user_store
from backend.admin.schemas.account import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    UpdateProfileRequest,
    UpdateProfileResponse,
)

router = APIRouter(prefix="/account", tags=["account"])


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


@router.patch("/profile", response_model=UpdateProfileResponse)
def update_profile(
    payload: UpdateProfileRequest,
    user: UserRecord = Depends(get_current_user),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
) -> UpdateProfileResponse:
    fields_set = payload.model_fields_set
    if not fields_set:
        raise AccountProfileEmpty()

    display_name: str | None = None
    if "display_name" in fields_set:
        if payload.display_name is None or not payload.display_name.strip():
            raise AccountInvalidDisplayName()
        display_name = payload.display_name.strip()

    set_email = "email" in fields_set
    email = _normalize_email(payload.email) if set_email else None

    locale: str | None = None
    if "locale" in fields_set:
        if payload.locale is None or not is_supported_locale(payload.locale):
            raise AccountInvalidLocale()
        locale = payload.locale

    updated = users.update_profile(
        user.id,
        display_name=display_name,
        email=email,
        set_email=set_email,
        locale=locale,
    )
    assert updated is not None
    return UpdateProfileResponse(user=build_current_user(updated, roles))


@router.post("/password", response_model=ChangePasswordResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: UserRecord = Depends(get_current_user),
    users: UserStore = Depends(get_user_store),
    sessions: SessionStore = Depends(get_session_store),
) -> ChangePasswordResponse:
    if user.identity_source != "local":
        raise AccountPasswordNotLocal()

    session_id = getattr(request.state, "session_id", None)
    if not session_id:
        raise AccountPasswordSessionRequired()

    if not verify_password(payload.current_password, user.password_hash):
        raise AccountPasswordInvalid()
    if not payload.new_password.strip():
        raise AccountPasswordInvalid()

    users.update_password_hash(user.id, hash_password(payload.new_password))
    sessions.delete_other_sessions(user.id, session_id)
    return ChangePasswordResponse(success=True)
