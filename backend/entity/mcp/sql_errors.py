"""Replace Profile View and physical relation names in a database message.

``views`` maps a bare Profile View name to the Entity ``table_name``.
``physical`` maps a bare physical table name the same way. Quoted, bare, and
schema-qualified forms are replaced. A single leading underscore is the
PostgreSQL array-type prefix and is kept. The Entity ``table_name`` is what
remains.
"""

from __future__ import annotations

import re
from typing import Mapping

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


def rewrite_sql_message(
    message: str,
    views: Mapping[str, str],
    *,
    physical: Mapping[str, str] | None = None,
) -> str:
    """Replace known relation identifiers with Entity ``table_name`` values."""

    pairs = [(name, table) for name, table in views.items()]
    if physical:
        pairs.extend((name, table) for name, table in physical.items())
    pairs.sort(key=lambda item: (-len(item[0]), item[0]))
    rewritten = message
    for identifier, table_name in pairs:
        if not identifier or identifier == table_name:
            continue
        rewritten = _replace_identifier(rewritten, identifier, table_name)
    return rewritten


def _replace_identifier(message: str, identifier: str, table_name: str) -> str:
    escaped = re.escape(identifier)
    # Optional "_" is pg_type's array prefix (_viewname). It is not part of the
    # identifier, so a longer name such as name9 or x_name still does not match.
    array_prefix = r"(?P<array>_)?"
    patterns = (
        rf'"(?:[^"]*)"\s*\.\s*"{array_prefix}{escaped}"',
        rf'\b{_IDENT}\s*\.\s*"{array_prefix}{escaped}"',
        rf'"(?:[^"]*)"\s*\.\s*{array_prefix}{escaped}\b',
        rf"\b{_IDENT}\s*\.\s*{array_prefix}{escaped}\b",
        rf'"{array_prefix}{escaped}"',
        rf"\b{array_prefix}{escaped}\b",
    )

    def _replacement(match: re.Match[str]) -> str:
        return (match.group("array") or "") + table_name

    rewritten = message
    for pattern in patterns:
        rewritten = re.sub(pattern, _replacement, rewritten)
    return rewritten
