from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    refraq_env: str = os.getenv("REFRAQ_ENV", "dev")
    api_host: str = os.getenv("REFRAQ_API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("REFRAQ_API_PORT", "8000"))
    admin_jwt_secret: str = os.getenv("ADMIN_JWT_SECRET", "change-me")
    admin_jwt_expire_hours: int = int(os.getenv("ADMIN_JWT_EXPIRE_HOURS", "8"))


def get_settings() -> Settings:
    return Settings()
