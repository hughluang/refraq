"""Helpers shared by several node types."""

from __future__ import annotations

import json
from typing import Any, Mapping

from backend.channel.nodes.spec import EngineHooks, NodeResult
from backend.channel.template import TemplateTypeError, render

__all__ = ["canonical_json", "render_field"]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


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
