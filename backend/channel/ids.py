"""Opaque Data Channel identifiers."""

from __future__ import annotations

import uuid

__all__ = ["new_channel_id"]


def new_channel_id() -> str:
    return f"chn_{uuid.uuid4().hex[:12]}"
