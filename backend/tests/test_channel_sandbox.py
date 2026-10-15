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


def test_network_and_write_open_are_denied() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        with pytest.raises(ExpressionError):
            sandbox.evaluate("__import__('socket').socket()")
        with pytest.raises(ExpressionError):
            sandbox.evaluate("open('/tmp/refraq-sandbox-probe', 'w')")


def test_dict_rows_support_comprehensions_and_methods() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={"id": "chn"}, run={"id": "job"}, platform={})
        sandbox.put_output(
            ref="read",
            name="Read",
            output={"rows": [{"code": " ab "}, {"code": "c", "get": 1}]},
        )
        assert sandbox.evaluate(
            '[dict(r, code=r["code"].strip()) for r in self.read.output.rows]'
        ) == [{"code": "ab"}, {"code": "c", "get": 1}]
        assert sandbox.evaluate('{**self.read.output.rows[0], "n": 2}') == {"code": " ab ", "n": 2}
        assert sandbox.evaluate('self.read.output.rows[0].get("missing")') is None
        assert sandbox.evaluate("self.read.output.rows[1].get") == 1


def test_drop_outputs_survives_restart() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        sandbox.put_output(ref="read", name="Read", output={"n": 1})
        sandbox.put_output(ref="keep", name="Keep", output={"n": 2})
        sandbox.drop_outputs(["read"])
        with pytest.raises(ExpressionError):
            sandbox.evaluate("self.read.output.n")
        assert sandbox.evaluate("self.keep.output.n") == 2
        sandbox._restart()
        with pytest.raises(ExpressionError):
            sandbox.evaluate("self.read.output.n")
        assert sandbox.evaluate("self.keep.output.n") == 2
