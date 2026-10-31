"""Expression sandbox subprocess."""

from __future__ import annotations

import pytest

from backend.channel.sandbox import CodeError, ExpressionError, SandboxSession
from backend.channel.template import render

_STRING = {"type": "string"}


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
        with pytest.raises(ExpressionError, match=r"^self\.missing does not resolve$"):
            sandbox.evaluate("self.missing.output.rows")


def test_missing_key_names_the_key() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        sandbox.put_output(ref="read", name="Read", output={"nope": 1})
        with pytest.raises(ExpressionError, match=r"^ok does not resolve$"):
            sandbox.evaluate("self.read.output.ok")


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


def test_run_code_reads_rows_and_reuses_one_process() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={"id": "chn"}, run={"id": "job"}, platform={})
        sandbox.put_output(
            ref="read",
            name="Read",
            output={"rows": [{"id": "a"}, {"id": "b"}], "count": 2},
        )
        pid = sandbox._proc.pid
        assert sandbox.run_code(
            'return [row["id"] for row in self.read.output.rows]',
            5,
        ) == ["a", "b"]
        assert sandbox.run_code("return self.read.output.count", 5) == 2
        assert sandbox._proc.pid == pid


def test_run_code_denies_network_and_import() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        with pytest.raises(CodeError) as network:
            sandbox.run_code("import socket\nsocket.socket()", 5)
        with pytest.raises(CodeError) as imported:
            sandbox.run_code("import os\nreturn os.getcwd()", 5)
    assert network.value.reason == "network"
    assert imported.value.reason == "import"
    assert str(network.value) == "Code tried to use the network"
    assert str(imported.value) == "Code imported a module that is not allowed"
    assert network.value.detail["reason"] == "network"
    assert imported.value.detail["reason"] == "import"


def test_run_code_timeout_restarts_and_stays_usable() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={"id": "chn"}, run={"id": "job"}, platform={})
        sandbox.put_output(ref="read", name="Read", output={"n": 7})
        pid = sandbox._proc.pid
        with pytest.raises(CodeError) as timed:
            sandbox.run_code("while True:\n    pass", 1)
        assert timed.value.reason == "timeout"
        assert str(timed.value) == "Code exceeded the time limit"
        assert sandbox._proc.pid != pid
        restarted = sandbox._proc.pid
        assert sandbox.run_code("return self.read.output.n", 5) == 7
        assert sandbox.run_code("return 1", 5) == 1
        assert sandbox._proc.pid == restarted


def test_run_code_memory_is_distinct_and_restarts() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        with pytest.raises(CodeError) as memory:
            sandbox.run_code(
                "blocks = []\n"
                "for _ in range(80):\n"
                "    blocks.append('x' * (8 * 1024 * 1024))\n"
                "return len(blocks)",
                30,
            )
        assert memory.value.reason == "memory"
        assert str(memory.value) == "Code exceeded the memory limit"
        assert sandbox.run_code("return 1", 5) == 1


def test_url_quote_in_a_string_template_encodes_reserved_characters() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        assert (
            render('{{ url_quote("a/b?c#d e") }}', sandbox.evaluate, _STRING)
            == "a%2Fb%3Fc%23d%20e"
        )


def test_url_quote_encodes_non_ascii_from_utf8_bytes() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        assert render('{{ url_quote("\\u00e9") }}', sandbox.evaluate, _STRING) == "%C3%A9"


def test_url_quote_renders_a_number_as_its_text() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        assert render("{{ url_quote(1) }}", sandbox.evaluate, _STRING) == "1"
        assert render("{{ url_quote(1e21) }}", sandbox.evaluate, _STRING) == "1e%2B21"


def test_url_quote_leaves_unreserved_characters() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        assert render('{{ url_quote("Ab9-._~") }}', sandbox.evaluate, _STRING) == "Ab9-._~"


def test_url_quote_globals_walk_fails() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        with pytest.raises(ExpressionError):
            sandbox.evaluate("'_REAL_IMPORT' in url_quote.__globals__")
        with pytest.raises(ExpressionError):
            sandbox.evaluate("url_quote.__globals__['_REAL_IMPORT']('os').listdir('.')")


def test_url_quote_call_attribute_walk_fails() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        with pytest.raises(ExpressionError):
            sandbox.evaluate("url_quote.__call__.__name__")
        with pytest.raises(ExpressionError):
            sandbox.evaluate("'_REAL_IMPORT' in url_quote.__call__.__self__.__globals__")


def test_url_quote_class_attribute_walk_fails() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        with pytest.raises(ExpressionError):
            sandbox.evaluate("url_quote.__class__.__name__")


def test_run_code_error_names_the_author_line() -> None:
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        with pytest.raises(CodeError) as failed:
            sandbox.run_code("x = 1\nreturn 1 / 0", 5)
    assert failed.value.reason == "error"
    assert failed.value.detail["type"] == "ZeroDivisionError"
    assert failed.value.detail["line"] == 2
    assert "line 2" in str(failed.value)
