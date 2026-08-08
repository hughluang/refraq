"""Platform settings router implementing docs/api-contracts-settings.md."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.admin.deps import require_permission
from backend.admin.settings_override import (
    clear_settings_override,
    get_admin_session_ttl_hours_default,
    get_admin_session_ttl_hours_source,
    get_effective_admin_session_ttl_hours,
    set_admin_session_ttl_hours,
)
from backend.core.config import Settings, get_settings
from backend.admin.user_store import UserRecord
from backend.admin.schemas.settings import (
    PlatformSettingsPatchRequest,
    PlatformSettingsResponse,
)

router = APIRouter(prefix="/settings", tags=["settings"])


def _build_response(settings: Settings) -> PlatformSettingsResponse:
    return PlatformSettingsResponse(
        refraq_env=settings.refraq_env,
        admin_session_ttl_hours=get_effective_admin_session_ttl_hours(settings),
        admin_session_ttl_hours_source=get_admin_session_ttl_hours_source(),
        admin_session_ttl_hours_default=get_admin_session_ttl_hours_default(settings),
    )


@router.get("", response_model=PlatformSettingsResponse)
def get_settings_view(
    _: UserRecord = Depends(require_permission("settings:read")),
    settings: Settings = Depends(get_settings),
) -> PlatformSettingsResponse:
    return _build_response(settings)


@router.patch("", response_model=PlatformSettingsResponse)
def patch_settings(
    payload: PlatformSettingsPatchRequest,
    _: UserRecord = Depends(require_permission("settings:write")),
    settings: Settings = Depends(get_settings),
) -> PlatformSettingsResponse:
    set_admin_session_ttl_hours(payload.admin_session_ttl_hours)
    return _build_response(settings)


@router.delete("/override", response_model=PlatformSettingsResponse)
def delete_settings_override(
    _: UserRecord = Depends(require_permission("settings:write")),
    settings: Settings = Depends(get_settings),
) -> PlatformSettingsResponse:
    clear_settings_override()
    return _build_response(settings)
