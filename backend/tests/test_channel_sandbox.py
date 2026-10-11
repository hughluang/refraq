"""Expression sandbox subprocess."""

from __future__ import annotations

import pytest

from backend.channel.sandbox import ExpressionError, SandboxSession


def test_self_path_and_comprehension() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(
            channel={"id": "chn"},
            run={"id": "job"},
            platform={"now": "2026-10-10T00:00:00Z"},
        )
        sandbox.put_output(
            ref="read_suppliers",
            name="Read suppliers",
            output={"rows": [{"id": "a"}, {"id": "b"}], "count": 2},
        )
        assert sandbox.evaluate('self.read_suppliers.output.count') == 2
        assert sandbox.evaluate('self.nodes["Read suppliers"].output.rows[0]["id"]') == "a"
        assert sandbox.evaluate('[row["id"] for row in self.read_suppliers.output.rows]') == ["a", "b"]
        assert sandbox.evaluate("self.platform.now") == "2026-10-10T00:00:00Z"


def test_missing_node_fails() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        with pytest.raises(ExpressionError):
            sandbox.evaluate("self.missing.output.rows")


def test_import_os_is_denied() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        with pytest.raises(ExpressionError):
            sandbox.evaluate("__import__('os').getcwd()")
