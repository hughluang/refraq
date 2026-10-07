"""Opaque identifiers for Business Entity resources."""

from __future__ import annotations

import uuid

__all__ = [
    "new_access_grant_id",
    "new_access_log_id",
    "new_access_profile_id",
    "new_access_restriction_id",
    "new_attribute_id",
    "new_dictionary_id",
    "new_entity_id",
    "new_version_id",
]


def new_attribute_id() -> str:
    return f"att_{uuid.uuid4().hex[:12]}"


def new_entity_id() -> str:
    return f"ent_{uuid.uuid4().hex[:12]}"


def new_version_id() -> str:
    return uuid.uuid4().hex[:16]


def new_dictionary_id() -> str:
    return f"dct_{uuid.uuid4().hex[:12]}"


def new_access_profile_id() -> str:
    return f"eap_{uuid.uuid4().hex[:12]}"


def new_access_grant_id() -> str:
    return f"eag_{uuid.uuid4().hex[:12]}"


def new_access_restriction_id() -> str:
    return f"ear_{uuid.uuid4().hex[:12]}"


def new_access_log_id() -> str:
    return f"eal_{uuid.uuid4().hex[:12]}"
