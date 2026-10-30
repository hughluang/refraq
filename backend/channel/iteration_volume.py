"""Shared iteration list and the 16 MiB cap for Container rounds.

Callers pass their own failure message. The measurement lives here so a test
can patch one constant.
"""

from __future__ import annotations

from typing import Any

from backend.channel.nodes.spec import NodeResult
from backend.channel.variables import value_size

__all__ = ["ITERATION_VOLUME_MAX_BYTES", "append_round"]

ITERATION_VOLUME_MAX_BYTES = 16 * 1024 * 1024
_VOLUME_CODE = "CHANNEL_ITERATION_VOLUME_EXCEEDED"


def append_round(
    iterations: list[Any], record: Any, *, message: str
) -> NodeResult | None:
    """Append one round. Fail with no output when the list exceeds 16 MiB."""
    iterations.append(record)
    if value_size(iterations) > ITERATION_VOLUME_MAX_BYTES:
        return NodeResult(
            status="failed",
            error_code=_VOLUME_CODE,
            error_message=message,
        )
    return None
