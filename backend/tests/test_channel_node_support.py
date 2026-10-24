"""Template fields rendered for a node executor."""

from __future__ import annotations

from backend.channel.node_support import render_field
from backend.tests.channel_hooks_fake import FakeHooks


def test_type_mismatch_keeps_the_expression() -> None:
    value, error = render_field(FakeHooks(), "1", {"type": "boolean"}, path="condition")
    assert value is None
    assert error is not None
    assert error.status == "failed"
    assert error.error_code == "CHANNEL_VALUE_TYPE_MISMATCH"
    assert error.error_message == "Value does not match the declared type"
    assert error.error_detail == {"expression": "1"}


def test_evaluation_error_keeps_the_expression() -> None:
    def evaluate(expression: str) -> object:
        raise RuntimeError(f"unknown {expression}")

    value, error = render_field(
        FakeHooks(evaluate=evaluate),
        "{{ missing }}",
        {"type": "boolean"},
        path="condition",
    )
    assert value is None
    assert error is not None
    assert error.status == "failed"
    assert error.error_code == "CHANNEL_NODE_FAILED"
    assert error.error_message == "unknown missing"
    assert error.error_detail == {"expression": "{{ missing }}"}


def test_non_string_raw_is_a_type_mismatch() -> None:
    value, error = render_field(FakeHooks(), {"n": 1}, {"type": "string"}, path="sql")
    assert value is None
    assert error is not None
    assert error.status == "failed"
    assert error.error_code == "CHANNEL_VALUE_TYPE_MISMATCH"
    assert error.error_message == "Template value must be text"
    assert error.error_detail == {"expression": {"n": 1}}
