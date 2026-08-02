from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    refraq_env: str = os.getenv("REFRAQ_ENV", "dev")
    admin_session_secret: str = os.getenv("ADMIN_SESSION_SECRET", "change-me")
    admin_session_ttl_hours: int = int(os.getenv("ADMIN_SESSION_TTL_HOURS", "8"))
    initial_admin_account: str = os.getenv("INITIAL_ADMIN_ACCOUNT", "root")
    initial_admin_password: str = os.getenv("INITIAL_ADMIN_PASSWORD", "change-me")


def get_settings() -> Settings:
    return Settings()
