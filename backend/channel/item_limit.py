"""How many list elements one channel node holds in memory."""

from __future__ import annotations

__all__ = [
    "ITEM_LIMIT",
    "LIST_ITEM_LIMIT_MESSAGE",
    "SQL_ITEM_LIMIT_MESSAGE",
]

ITEM_LIMIT = 100_000
SQL_ITEM_LIMIT_MESSAGE = "Use Dataset Query, then Batch Read."
LIST_ITEM_LIMIT_MESSAGE = "Use Materialize or Dataset Query, then Batch Read."
