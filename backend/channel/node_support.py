"""Helpers shared by several node types."""

from __future__ import annotations

import json
from contextvars import ContextVar, Token
from typing import Any, Mapping

from backend.channel.nodes.spec import EngineHooks, NodeResult
from backend.channel.template import TemplateTypeError, render

__all__ = [
    "InputCapture",
    "bind_execution_input",
    "canonical_json",
    "render_field",
    "reset_execution_input",
]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class InputCapture:
    """Template fields rendered while one node execution is in progress.

    The caller names the config path. A repeated path keeps the last render.
    """

    def __init__(self) -> None:
        self.fields: dict[str, Any] = {}

    def record_value(self, path: str, value: Any) -> None:
        self.fields[path] = {"value": value}

    def record_error(self, path: str, code: str, message: str) -> None:
        self.fields[path] = {"error": {"code": code, "message": message}}


_active: ContextVar[InputCapture | None] = ContextVar(
    "channel_execution_input", default=None
)


def bind_execution_input(capture: InputCapture) -> Token[InputCapture | None]:
    return _active.set(capture)


def reset_execution_input(token: Token[InputCapture | None]) -> None:
    _active.reset(token)


def render_field(
    hooks: EngineHooks,
    raw: Any,
    schema: Mapping[str, Any],
    *,
    path: str,
) -> tuple[Any, NodeResult | None]:
    try:
        if not isinstance(raw, str):
            raise TemplateTypeError("Template value must be text")
        value = render(raw, hooks.evaluate, schema)
    except TemplateTypeError as exc:
        _record_error(path, "CHANNEL_VALUE_TYPE_MISMATCH", str(exc))
        return None, NodeResult(
            status="failed",
            error_code="CHANNEL_VALUE_TYPE_MISMATCH",
            error_message=str(exc),
            error_detail={"expression": raw},
        )
    except Exception as exc:  # noqa: BLE001
        _record_error(path, "CHANNEL_NODE_FAILED", str(exc))
        return None, NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=str(exc),
            error_detail={"expression": raw},
        )
    _record_value(path, value)
    return value, None


def _record_value(path: str, value: Any) -> None:
    capture = _active.get()
    if capture is not None:
        capture.record_value(path, value)


def _record_error(path: str, code: str, message: str) -> None:
    capture = _active.get()
    if capture is not None:
        capture.record_error(path, code, message)
