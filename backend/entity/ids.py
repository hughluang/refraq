"""Opaque identifiers for Business Entity resources."""

from __future__ import annotations

import uuid

__all__ = ["new_entity_id", "new_version_id"]


def new_entity_id() -> str:
    return f"ent_{uuid.uuid4().hex[:12]}"


def new_version_id() -> str:
    return f"encv_{uuid.uuid4().hex[:12]}"
