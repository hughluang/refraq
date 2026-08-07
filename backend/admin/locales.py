"""Supported Console UI locales (Account Center / User.locale)."""

from __future__ import annotations

SUPPORTED_LOCALES: frozenset[str] = frozenset({"zh-CN", "en-US"})
DEFAULT_LOCALE = "en-US"


def is_supported_locale(value: str) -> bool:
    return value in SUPPORTED_LOCALES
