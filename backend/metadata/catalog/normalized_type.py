"""Canonical native type strings and the closed Normalized Type vocabulary."""

from __future__ import annotations

import re

_PAREN_GROUP = re.compile(r"\([^()]*\)")
_SPACE = re.compile(r"\s+")

CLOSED_NORMALIZED_TYPES: frozenset[str] = frozenset(
    {
        "string",
        "integer",
        "number",
        "boolean",
        "date",
        "timestamp",
        "time",
        "interval",
        "binary",
        "json",
        "array",
        "unknown",
    }
)
PATCHABLE_NORMALIZED_TYPES: frozenset[str] = CLOSED_NORMALIZED_TYPES - {"unknown"}


def canonicalize_native_type(data_type: str) -> str:
    """Lowercase, fold whitespace, and drop every parenthetical group and its contents."""
    text = str(data_type).strip().lower()
    if not text:
        return ""
    previous = None
    while previous != text:
        previous = text
        text = _PAREN_GROUP.sub("", text)
    return _SPACE.sub(" ", text).strip()
