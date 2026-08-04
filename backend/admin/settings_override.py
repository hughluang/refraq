"""In-process Settings Override for a narrow writable set (not Store Backend)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Literal

from backend.core.config import Settings, get_settings

TTL_HOURS_MIN = 1
TTL_HOURS_MAX = 168

SettingsSource = Literal["env", "override"]


@dataclass(slots=True)
class _OverrideState:
    admin_session_ttl_hours: int | None = None


_lock = threading.Lock()
_state = _OverrideState()


def reset_settings_override() -> None:
    with _lock:
        _state.admin_session_ttl_hours = None


def get_admin_session_ttl_hours_default(settings: Settings | None = None) -> int:
    cfg = settings or get_settings()
    return cfg.admin_session_ttl_hours


def get_effective_admin_session_ttl_hours(settings: Settings | None = None) -> int:
    cfg = settings or get_settings()
    with _lock:
        if _state.admin_session_ttl_hours is not None:
            return _state.admin_session_ttl_hours
    return cfg.admin_session_ttl_hours


def get_admin_session_ttl_hours_source() -> SettingsSource:
    with _lock:
        return "override" if _state.admin_session_ttl_hours is not None else "env"


def set_admin_session_ttl_hours(value: int) -> None:
    if value < TTL_HOURS_MIN or value > TTL_HOURS_MAX:
        raise ValueError(
            f"admin_session_ttl_hours must be between {TTL_HOURS_MIN} and {TTL_HOURS_MAX}"
        )
    with _lock:
        _state.admin_session_ttl_hours = value


def clear_settings_override() -> None:
    reset_settings_override()
