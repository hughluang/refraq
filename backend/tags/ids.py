"""Opaque identifiers for Tag records."""

from __future__ import annotations

import uuid

__all__ = ["new_saved_filter_id", "new_tag_id"]


def new_tag_id() -> str:
    return f"tag_{uuid.uuid4().hex[:12]}"


def new_saved_filter_id() -> str:
    return f"sf_{uuid.uuid4().hex[:12]}"
