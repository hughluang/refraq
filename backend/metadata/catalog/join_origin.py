"""Join Origin policy: structure-derived vs human/mcp protection."""

from __future__ import annotations

from typing import Literal

PROTECTED_JOIN_ORIGINS = frozenset({"human", "mcp"})
STRUCTURE_JOIN_ORIGIN = "foreign_key"

JoinWriteDecision = Literal["keep_existing", "apply"]


def resolve_join_write(
    *,
    existing_origin: str | None,
    incoming_origin: str,
) -> JoinWriteDecision:
    """Decide whether an incoming join write may replace an existing edge.

    Structure-derived ``foreign_key`` must not overwrite human/mcp edges.
    """
    if (
        incoming_origin == STRUCTURE_JOIN_ORIGIN
        and existing_origin is not None
        and existing_origin in PROTECTED_JOIN_ORIGINS
    ):
        return "keep_existing"
    return "apply"
