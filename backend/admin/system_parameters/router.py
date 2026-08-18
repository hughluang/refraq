"""Platform Settings HTTP for the System Parameter catalog."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.admin.audit import persist_audit_event
from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.system_parameters.errors import ParameterValueInvalid, UnregisteredParameter
from backend.admin.system_parameters.registry import get_parameter_spec, list_registered_specs
from backend.admin.system_parameters.resolver import (
    read_stored_parameter,
    reset_parameter,
    set_parameter,
    validate_parameter_write,
)
from backend.admin.system_parameters.schemas import (
    PlatformSettingsPatchRequest,
    PlatformSettingsResetRequest,
    PlatformSettingsResponse,
    SystemParameterOut,
)
from backend.admin.user_store import UserRecord, UserStore, get_user_store

router = APIRouter(prefix="/settings", tags=["settings"])


def _catalog(users: UserStore) -> PlatformSettingsResponse:
    items: list[SystemParameterOut] = []
    for spec in list_registered_specs():
        stored = read_stored_parameter(spec.key)
        account = None
        if stored.updated_by_user_id:
            actor = users.get_by_id(stored.updated_by_user_id)
            account = actor.account if actor is not None else None
        items.append(
            SystemParameterOut(
                key=spec.key,
                value=stored.value,
                seed=spec.seed,
                source=stored.source,
                constraint=spec.constraint.to_json_schema(),
                group=spec.group,
                operator_action_required=spec.operator_action_required,
                label_key=spec.label_key,
                help_key=spec.help_key,
                apply_note_key=spec.apply_note_key,
                updated_at=stored.updated_at,
                updated_by_user_id=stored.updated_by_user_id,
                updated_by_account=account,
            )
        )
    return PlatformSettingsResponse(parameters=items)


def _audit(
    *,
    request: Request,
    user: UserRecord,
    key: str,
    action: str,
    value: object,
    previous_value: object,
) -> None:
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="system_parameter",
        resource_id=key,
        action=action,
        result="success",
        detail={"value": value, "previous_value": previous_value},
    )


@router.get("", response_model=PlatformSettingsResponse)
def get_settings_view(
    _: UserRecord = Depends(require_permission("settings:read")),
    users: UserStore = Depends(get_user_store),
) -> PlatformSettingsResponse:
    return _catalog(users)


@router.patch("", response_model=PlatformSettingsResponse)
def patch_settings(
    payload: PlatformSettingsPatchRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("settings:write")),
    users: UserStore = Depends(get_user_store),
) -> PlatformSettingsResponse:
    pending: list[tuple[str, object, object]] = []
    for key, value in payload.values.items():
        try:
            validate_parameter_write(key, value)
        except UnregisteredParameter as exc:
            raise ParameterValueInvalid(f"unknown system parameter: {key}") from exc
        previous = read_stored_parameter(key).value
        pending.append((key, value, previous))
    for key, value, previous in pending:
        set_parameter(key, value, actor_user_id=user.id)
        _audit(
            request=request,
            user=user,
            key=key,
            action="parameter.set",
            value=value,
            previous_value=previous,
        )
    return _catalog(users)


@router.post("/reset", response_model=PlatformSettingsResponse)
def reset_settings(
    payload: PlatformSettingsResetRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("settings:write")),
    users: UserStore = Depends(get_user_store),
) -> PlatformSettingsResponse:
    keys = payload.keys or [spec.key for spec in list_registered_specs()]
    pending: list[tuple[str, object]] = []
    for key in keys:
        try:
            get_parameter_spec(key)
        except UnregisteredParameter as exc:
            raise ParameterValueInvalid(f"unknown system parameter: {key}") from exc
        previous = read_stored_parameter(key).value
        pending.append((key, previous))
    for key, previous in pending:
        resolved = reset_parameter(key, actor_user_id=user.id)
        _audit(
            request=request,
            user=user,
            key=key,
            action="parameter.reset",
            value=resolved.value,
            previous_value=previous,
        )
    return _catalog(users)
