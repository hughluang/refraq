"""Helpers shared by node executors."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.engine import EngineHooks, NodeResult
from backend.channel.template import TemplateTypeError, render

__all__ = ["render_field"]


def render_field(
    hooks: EngineHooks,
    raw: Any,
    schema: Mapping[str, Any],
) -> tuple[Any, NodeResult | None]:
    try:
        if not isinstance(raw, str):
            raise TemplateTypeError("Template value must be text")
        return render(raw, hooks.evaluate, schema), None
    except TemplateTypeError as exc:
        return None, NodeResult(
            status="failed",
            error_code="CHANNEL_VALUE_TYPE_MISMATCH",
            error_message=str(exc),
            error_detail={"expression": raw},
        )
    except Exception as exc:  # noqa: BLE001
        return None, NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=str(exc),
            error_detail={"expression": raw},
        )
