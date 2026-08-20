"""Join attester constants and automatic insert-vs-skip."""

from __future__ import annotations

from typing import Literal

STRUCTURE_JOIN_ORIGIN = "foreign_key"
SQL_LINEAGE_JOIN_ORIGIN = "sql_lineage"
HUMAN_JOIN_ORIGIN = "human"
MCP_JOIN_ORIGIN = "mcp"

JoinInsertDecision = Literal["insert", "skip_protected", "skip_rejected"]


def decide_automatic_insert(*, existing_rejected: bool | None) -> JoinInsertDecision:
    """Whether an automatic Job may insert a join for this directed pair.

    ``existing_rejected`` is None when the pair has no row. Automatic Jobs never
    update or delete an existing row.
    """
    if existing_rejected is None:
        return "insert"
    if existing_rejected:
        return "skip_rejected"
    return "skip_protected"
