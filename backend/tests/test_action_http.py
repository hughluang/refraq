"""action.http sends one request and returns the response record."""

from __future__ import annotations

import gzip
import json
import socket
import ssl
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from jsonschema import Draft202012Validator

from backend.admin.system_parameters import set_parameter
from backend.channel.engine import execute
from backend.channel.graph import validate
from backend.channel.http_accounts import HttpAccountRecord
from backend.channel.node_support import InputCapture, bind_execution_input, reset_execution_input
from backend.channel.nodes import list_node_types
from backend.channel.nodes.action.http import NODE_TYPE
from backend.tests.channel_hooks_fake import FakeHooks
from backend.worker.parameters import assemble_system_parameters

_FORBIDDEN = (
    "authorization",
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "upgrade",
    "te",
    "trailer",
    "proxy-authorization",
    "proxy-connection",
)


@dataclass
class Received:
    method: str
    target: str
    headers: list[tuple[str, str]]
    body: bytes


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length) if length else b""
        server = self.server
        assert isinstance(server, _Server)
        server.seen.append(Received(self.command, self.path, list(self.headers.items()), body))
        script = server.script
        if script is None:
            reply(self, 500, body=b"no script")
            return
        script(self, len(server.seen) - 1)

    def log_message(self, fmt: str, *args: Any) -> None:
        del fmt, args

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle()


class _Server(ThreadingHTTPServer):
    seen: list[Received]
    script: Callable[[_Handler, int], None] | None


def reply(
    handler: _Handler,
    status: int,
    headers: tuple[tuple[str, str], ...] | list[tuple[str, str]] = (),
    body: bytes = b"",
    *,
    delay: float = 0,
) -> None:
    if delay:
        time.sleep(delay)
    handler.send_response(status)
    for name, value in headers:
        handler.send_header(name, value)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Connection", "close")
    handler.end_headers()
    if handler.command != "HEAD" and body:
        handler.wfile.write(body)


@contextmanager
def serve(tls: tuple[Path, Path] | None = None):
    httpd = _Server(("127.0.0.1", 0), _Handler)
    httpd.seen = []
    httpd.script = None
    if tls is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(tls[0], tls[1])
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()


def origin_of(httpd: _Server, scheme: str = "http") -> str:
    port = httpd.server_address[1]
    return f"{scheme}://127.0.0.1:{port}"


def header_values(received: Received, name: str) -> list[str]:
    return [value for key, value in received.headers if key.lower() == name.lower()]


class _Resolver:
    def entity_head(self, entity_id: str) -> None:
        del entity_id
        return None

    def channel_exists(self, channel_id: str) -> bool:
        del channel_id
        return False

    def published_trigger_type(self, channel_id: str) -> str | None:
        del channel_id
        return None

    def source_exists(self, source_id: str) -> bool:
        del source_id
        return False


def run(config: dict[str, Any], values: dict[str, Any] | None = None):
    def evaluate(expression: str) -> Any:
        assert values is not None
        return values[expression]

    hooks = FakeHooks(evaluate=evaluate if values is not None else None)
    capture = InputCapture()
    token = bind_execution_input(capture)
    try:
        result = NODE_TYPE.execute({"id": "call", "config": config}, hooks)
    finally:
        reset_execution_input(token)
    return result, capture


def account(**overrides: Any) -> HttpAccountRecord:
    now = datetime.now(timezone.utc)
    fields: dict[str, Any] = {
        "id": "hac_1",
        "name": "OA",
        "auth_type": "none",
        "username": None,
        "secret": None,
        "headers": [],
        "query": [],
        "allowed_origins": [],
        "created_at": now,
        "updated_at": now,
    }
    fields.update(overrides)
    return HttpAccountRecord(**fields)


def use_account(monkeypatch: pytest.MonkeyPatch, record: HttpAccountRecord) -> None:
    monkeypatch.setattr(
        "backend.channel.nodes.action.http.get_http_account_store",
        lambda: SimpleNamespace(get=lambda account_id: record if account_id == record.id else None),
    )


def hidden(result: Any, capture: InputCapture) -> str:
    return json.dumps(
        {
            "input": capture.fields,
            "output": result.output,
            "error": result.error_message,
            "detail": result.error_detail,
        },
        default=str,
    )


@pytest.fixture(autouse=True)
def _parameters() -> None:
    assemble_system_parameters()


def test_get_returns_status_headers_and_body() -> None:
    def script(handler: _Handler, index: int) -> None:
        del index
        reply(
            handler,
            200,
            [
                ("Content-Type", "text/plain"),
                ("Link", '<a>; rel="next"'),
                ("Link", '<b>; rel="prev"'),
                ("Set-Cookie", "a=1"),
                ("Set-Cookie", "b=2"),
            ],
            b"hi",
        )

    with serve() as httpd:
        httpd.script = script
        result, _capture = run({"method": "GET", "url": origin_of(httpd) + "/item"})
    assert result.status == "succeeded"
    assert set(result.output) == {"status_code", "headers", "body"}
    assert result.output["status_code"] == 200
    assert result.output["body"] == "hi"
    headers = result.output["headers"]
    assert all(name == name.lower() for name in headers)
    assert headers["link"] == '<a>; rel="next", <b>; rel="prev"'
    assert headers["set-cookie"] == "b=2"
    assert headers["content-type"] == "text/plain"
    assert httpd.seen[0].method == "GET"
    assert httpd.seen[0].target == "/item"
    assert header_values(httpd.seen[0], "idempotency-key") == []
    assert header_values(httpd.seen[0], "cookie") == []


def test_empty_json_body_is_null() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(
            handler, 200, [("Content-Type", "application/json")]
        )
        result, _capture = run({"method": "GET", "url": origin_of(httpd) + "/"})
    assert result.status == "succeeded"
    assert result.output["body"] is None


def test_json_media_types_are_parsed_and_other_text_stays_text() -> None:
    payloads = [
        ("application/json", b'{"n":1}', {"n": 1}),
        ("application/json; charset=utf-8", b"[1]", [1]),
        ("application/vnd.api+json", b'{"data":1}', {"data": 1}),
        ("application/merge-patch+json", b"true", True),
        ("text/plain", b'{"n":1}', '{"n":1}'),
    ]

    def script(handler: _Handler, index: int) -> None:
        content_type, body, _expected = payloads[index]
        reply(handler, 200, [("Content-Type", content_type)], body)

    with serve() as httpd:
        httpd.script = script
        base = origin_of(httpd)
        for index, (_content_type, _body, expected) in enumerate(payloads):
            result, _capture = run({"method": "GET", "url": f"{base}/{index}"})
            assert result.status == "succeeded"
            assert result.output["body"] == expected


def test_json_parse_failure_and_invalid_utf8_fail() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(
            handler, 200, [("Content-Type", "application/json")], b"not-json"
        )
        parsed, _capture = run({"method": "GET", "url": origin_of(httpd) + "/json"})
    assert parsed.status == "failed"
    assert parsed.error_message == "Response body is not JSON"
    assert parsed.error_detail == {"status_code": 200}
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(
            handler, 200, [("Content-Type", "text/plain")], b"\xff"
        )
        binary, _capture = run({"method": "GET", "url": origin_of(httpd) + "/bin"})
    assert binary.status == "failed"
    assert binary.error_message == "Response body is not valid UTF-8"
    assert binary.error_detail == {"status_code": 200}


def test_json_body_sends_the_rendered_value() -> None:
    cases = [
        ("{{ payload }}", {"payload": {"a": 1}}, b'{"a":1}'),
        ("{{ payload }}", {"payload": "hello"}, b'"hello"'),
        ("{{ payload }}", {"payload": None}, b"null"),
        ("{{ payload }}", {"payload": [1, 2]}, b"[1,2]"),
        ('{"a": 1}', None, b'{"a":1}'),
        ('{"n": {{ n }}}', {"n": 2}, b'{"n":2}'),
    ]
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 204)
        url = origin_of(httpd) + "/write"
        for body, values, expected in cases:
            result, _capture = run(
                {
                    "method": "POST",
                    "url": url,
                    "body_mode": "json",
                    "body": body,
                },
                values,
            )
            assert result.status == "succeeded", result.error_message
            assert httpd.seen[-1].body == expected
            assert header_values(httpd.seen[-1], "content-type") == ["application/json"]


def test_raw_body_uses_the_required_content_type() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 200, body=b"ok")
        result, _capture = run(
            {
                "method": "POST",
                "url": origin_of(httpd) + "/raw",
                "body_mode": "raw",
                "body": "hello",
                "content_type": "text/plain",
            }
        )
    assert result.status == "succeeded"
    assert httpd.seen[0].body == b"hello"
    assert header_values(httpd.seen[0], "content-type") == ["text/plain"]


def test_blank_body_sends_no_body_and_no_body_content_type() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 200, body=b"ok")
        result, capture = run(
            {
                "method": "POST",
                "url": origin_of(httpd) + "/empty",
                "body": "   ",
                "content_type": "text/plain",
            }
        )
    assert result.status == "succeeded"
    assert httpd.seen[0].body == b""
    assert header_values(httpd.seen[0], "content-type") == []
    assert "content_type" not in capture.fields
    assert "body" not in capture.fields


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_write_methods_may_carry_a_body(method: str) -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 200, body=b"ok")
        result, _capture = run(
            {
                "method": method,
                "url": origin_of(httpd) + "/item",
                "body_mode": "raw",
                "body": "payload",
                "content_type": "text/plain",
            }
        )
    assert result.status == "succeeded"
    assert httpd.seen[0].method == method
    assert httpd.seen[0].body == b"payload"


def test_content_type_is_applied_after_account_and_node_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    use_account(
        monkeypatch,
        account(
            headers=[("Content-Type", "text/plain"), ("X-Account", "from-account")],
        ),
    )
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 204)
        result, _capture = run(
            {
                "method": "POST",
                "url": origin_of(httpd) + "/merge",
                "http_account_id": "hac_1",
                "headers": [{"name": "Content-Type", "value": "text/html"}],
                "body_mode": "json",
                "body": '{"a": 1}',
                "content_type": "application/merge-patch+json",
            }
        )
    assert result.status == "succeeded", result.error_message
    assert header_values(httpd.seen[0], "content-type") == ["application/merge-patch+json"]
    assert header_values(httpd.seen[0], "x-account") == ["from-account"]
    assert httpd.seen[0].body == b'{"a":1}'


def test_rendered_blank_json_content_type_defaults_to_application_json() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 204)
        result, capture = run(
            {
                "method": "POST",
                "url": origin_of(httpd) + "/json",
                "body": "{{ payload }}",
                "content_type": "{{ ctype }}",
            },
            {"payload": {"ok": True}, "ctype": "  "},
        )
    assert result.status == "succeeded", result.error_message
    assert header_values(httpd.seen[0], "content-type") == ["application/json"]
    assert capture.fields["content_type"]["value"] == "  "


def test_url_keeps_expression_text_and_encodes_only_the_query_list() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(
            handler, 200, [("Content-Type", "text/plain")], b"ok"
        )
        port = httpd.server_address[1]
        result, capture = run(
            {
                "method": "GET",
                "url": f"http://127.0.0.1:{port}/{{{{ path }}}}?already=a%2Fb#frag",
                "query": [
                    {"name": "q", "value": "{{ space }}"},
                    {"name": "tag", "value": "1"},
                    {"name": "tag", "value": "2"},
                ],
            },
            {"path": "a/b", "space": "x y"},
        )
    expected = f"http://127.0.0.1:{port}/a/b?already=a%2Fb&q=x%20y&tag=1&tag=2#frag"
    assert result.status == "succeeded", result.error_message
    assert capture.fields["url"]["value"] == expected
    assert httpd.seen[0].target == f"/a/b?already=a%2Fb&q=x%20y&tag=1&tag=2"


def test_account_auth_headers_and_query_stay_off_the_record(monkeypatch: pytest.MonkeyPatch) -> None:
    use_account(
        monkeypatch,
        account(
            auth_type="bearer",
            secret="sekret-token-9f3a",
            headers=[("X-Trace", "sekret-header-9f3a")],
            query=[("api_key", "sekret-query-9f3a")],
        ),
    )
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(
            handler, 200, [("Content-Type", "application/json")], b'{"ok":true}'
        )
        result, capture = run(
            {
                "method": "GET",
                "url": origin_of(httpd) + "/call",
                "http_account_id": "hac_1",
                "query": [{"name": "q", "value": "1"}],
                "headers": [{"name": "x-trace", "value": "visible"}],
            }
        )
    assert result.status == "succeeded", result.error_message
    assert result.output["body"] == {"ok": True}
    target = httpd.seen[0].target
    assert target == "/call?q=1&api_key=sekret-query-9f3a"
    assert header_values(httpd.seen[0], "authorization") == ["Bearer sekret-token-9f3a"]
    assert header_values(httpd.seen[0], "x-trace") == ["visible"]
    stored = hidden(result, capture)
    assert "sekret-token-9f3a" not in stored
    assert "sekret-header-9f3a" not in stored
    assert "sekret-query-9f3a" not in stored
    assert capture.fields["url"]["value"] == origin_of(httpd) + "/call?q=1"


def test_basic_auth_is_the_utf8_user_password(monkeypatch: pytest.MonkeyPatch) -> None:
    use_account(
        monkeypatch,
        account(auth_type="basic", username="ada", secret="sekret-basic-9f3a"),
    )
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 204)
        result, capture = run(
            {
                "method": "GET",
                "url": origin_of(httpd) + "/",
                "http_account_id": "hac_1",
            }
        )
    assert result.status == "succeeded", result.error_message
    assert header_values(httpd.seen[0], "authorization") == ["Basic YWRhOnNla3JldC1iYXNpYy05ZjNh"]
    assert "sekret-basic-9f3a" not in hidden(result, capture)


def test_no_account_sends_no_authorization() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 204)
        result, _capture = run({"method": "GET", "url": origin_of(httpd) + "/"})
    assert result.status == "succeeded"
    assert header_values(httpd.seen[0], "authorization") == []


def test_origin_outside_the_allow_list_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 204)
        use_account(
            monkeypatch,
            account(
                auth_type="bearer",
                secret="sekret-token-9f3a",
                allowed_origins=["http://127.0.0.1:9"],
            ),
        )
        result, capture = run(
            {
                "method": "GET",
                "url": origin_of(httpd) + "/blocked",
                "http_account_id": "hac_1",
            }
        )
    assert httpd.seen == []
    assert result.status == "failed"
    assert result.error_message == "Origin is not allowed"
    assert result.error_detail is None
    assert "sekret-token-9f3a" not in hidden(result, capture)


def test_empty_allow_list_permits_the_server_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    with serve() as httpd:
        use_account(
            monkeypatch,
            account(
                auth_type="bearer",
                secret="sekret-token-9f3a",
                allowed_origins=[],
            ),
        )
        httpd.script = lambda handler, index: reply(handler, 204)
        result, _capture = run(
            {
                "method": "GET",
                "url": origin_of(httpd) + "/",
                "http_account_id": "hac_1",
            }
        )
    assert result.status == "succeeded", result.error_message
    assert header_values(httpd.seen[0], "authorization") == ["Bearer sekret-token-9f3a"]


def test_implicit_port_does_not_match_an_explicit_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 204)
        use_account(
            monkeypatch,
            account(allowed_origins=[origin_of(httpd)]),
        )
        result, _capture = run(
            {
                "method": "GET",
                "url": "http://127.0.0.1/nope",
                "http_account_id": "hac_1",
            }
        )
    assert httpd.seen == []
    assert result.error_message == "Origin is not allowed"


def test_header_line_breaks_fail_before_connect() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 204)
        for value in ("a\nb", "a\rb", "a\x00b"):
            result, _capture = run(
                {
                    "method": "GET",
                    "url": origin_of(httpd) + "/",
                    "headers": [{"name": "X-Test", "value": value}],
                }
            )
            assert result.status == "failed"
            assert result.error_message == "Header value contains a line break or NUL"
    assert httpd.seen == []


def test_rendered_forbidden_header_fails_before_connect() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 204)
        result, _capture = run(
            {
                "method": "GET",
                "url": origin_of(httpd) + "/",
                "headers": [{"name": "{{ name }}", "value": "x"}],
            },
            {"name": "Authorization"},
        )
    assert httpd.seen == []
    assert result.error_message == "Header name is not allowed"


def test_scheme_rejection_does_not_include_the_url() -> None:
    result, _capture = run({"method": "GET", "url": "ftp://127.0.0.1/secret-file"})
    assert result.status == "failed"
    assert result.error_message == "URL is not an absolute http or https URL"
    assert result.error_detail is None
    assert "secret-file" not in (result.error_message or "")


def test_port_outside_the_tcp_range_fails_before_connect() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 204)
        result, _capture = run(
            {"method": "GET", "url": "{{ target }}"},
            {"target": "http://127.0.0.1:99999/x"},
        )
    assert httpd.seen == []
    assert result.status == "failed"
    assert result.error_message == "URL is not an absolute http or https URL"
    assert result.error_detail is None


def test_rendered_url_over_8192_characters_is_not_sent() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 204)
        port = httpd.server_address[1]
        result, _capture = run(
            {"method": "GET", "url": "{{ big }}"},
            {"big": f"http://127.0.0.1:{port}/" + ("a" * 8200)},
        )
    assert httpd.seen == []
    assert result.error_message == "URL exceeds 8192 characters"


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirect_keeps_method_and_body(status: int) -> None:
    with serve() as first, serve() as second:
        second.script = lambda handler, index: reply(
            handler, 200, [("Content-Type", "text/plain")], b"landed"
        )

        def redirect(handler: _Handler, index: int) -> None:
            del index
            reply(handler, status, [("Location", origin_of(second) + "/landed")], b"")

        first.script = redirect
        result, _capture = run(
            {
                "method": "POST",
                "url": origin_of(first) + "/start",
                "body_mode": "raw",
                "body": "hello",
                "content_type": "text/plain",
                "headers": [{"name": "X-Node", "value": "kept"}],
            }
        )
    assert result.status == "succeeded", result.error_message
    assert result.output["body"] == "landed"
    assert first.seen[0].method == "POST"
    assert first.seen[0].body == b"hello"
    assert second.seen[0].method == "POST"
    assert second.seen[0].body == b"hello"
    assert second.seen[0].target == "/landed"
    assert header_values(second.seen[0], "content-type") == ["text/plain"]
    assert header_values(second.seen[0], "x-node") == ["kept"]


def test_303_retries_as_get_without_the_body() -> None:
    with serve() as first, serve() as second:
        second.script = lambda handler, index: reply(
            handler, 200, [("Content-Type", "text/plain")], b"other"
        )
        first.script = lambda handler, index: reply(
            handler, 303, [("Location", origin_of(second) + "/other")]
        )
        result, _capture = run(
            {
                "method": "POST",
                "url": origin_of(first) + "/start",
                "body_mode": "raw",
                "body": "hello",
                "content_type": "text/plain",
                "headers": [{"name": "X-Node", "value": "kept"}],
            }
        )
    assert result.status == "succeeded", result.error_message
    assert second.seen[0].method == "GET"
    assert second.seen[0].body == b""
    assert second.seen[0].target == "/other"
    assert header_values(second.seen[0], "content-type") == []
    assert header_values(second.seen[0], "x-node") == ["kept"]


def test_cross_origin_redirect_drops_account_material_for_the_rest_of_the_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_account(
        monkeypatch,
        account(
            auth_type="bearer",
            secret="sekret-token-9f3a",
            headers=[("X-Account", "sekret-header-9f3a")],
            query=[("api_key", "sekret-query-9f3a")],
        ),
    )
    with serve() as origin, serve() as other:
        other.script = lambda handler, index: reply(
            handler, 302, [("Location", origin_of(origin) + "/back")]
        )

        def start(handler: _Handler, index: int) -> None:
            if index == 0:
                reply(handler, 302, [("Location", origin_of(other) + "/away")])
                return
            reply(handler, 200, [("Content-Type", "text/plain")], b"home")

        origin.script = start
        result, capture = run(
            {
                "method": "GET",
                "url": origin_of(origin) + "/start",
                "http_account_id": "hac_1",
                "query": [{"name": "q", "value": "1"}],
                "headers": [{"name": "X-Node", "value": "visible"}],
            }
        )
    assert result.status == "succeeded", result.error_message
    assert result.output["body"] == "home"
    assert origin.seen[0].target == "/start?q=1&api_key=sekret-query-9f3a"
    assert header_values(origin.seen[0], "authorization") == ["Bearer sekret-token-9f3a"]
    assert header_values(origin.seen[0], "x-account") == ["sekret-header-9f3a"]
    assert other.seen[0].target == "/away"
    assert header_values(other.seen[0], "authorization") == []
    assert header_values(other.seen[0], "x-account") == []
    assert header_values(other.seen[0], "x-node") == ["visible"]
    assert header_values(other.seen[0], "cookie") == []
    assert origin.seen[1].target == "/back"
    assert header_values(origin.seen[1], "authorization") == []
    assert header_values(origin.seen[1], "x-account") == []
    assert header_values(origin.seen[1], "x-node") == ["visible"]
    assert "sekret-query-9f3a" not in origin.seen[1].target
    assert "sekret-token-9f3a" not in hidden(result, capture)


def test_same_origin_redirect_keeps_account_material(monkeypatch: pytest.MonkeyPatch) -> None:
    use_account(
        monkeypatch,
        account(
            auth_type="bearer",
            secret="sekret-token-9f3a",
            headers=[("X-Account", "sekret-header-9f3a")],
            query=[("api_key", "sekret-query-9f3a")],
        ),
    )
    with serve() as httpd:
        def script(handler: _Handler, index: int) -> None:
            if index == 0:
                reply(handler, 302, [("Location", "/next"), ("Set-Cookie", "session=sekret-cookie")])
                return
            reply(handler, 200, [("Content-Type", "text/plain")], b"next")

        httpd.script = script
        result, _capture = run(
            {
                "method": "GET",
                "url": origin_of(httpd) + "/start",
                "http_account_id": "hac_1",
            }
        )
    assert result.status == "succeeded", result.error_message
    assert httpd.seen[1].target == "/next"
    assert header_values(httpd.seen[1], "authorization") == ["Bearer sekret-token-9f3a"]
    assert header_values(httpd.seen[1], "x-account") == ["sekret-header-9f3a"]
    assert header_values(httpd.seen[1], "cookie") == []
    assert "sekret-query-9f3a" not in httpd.seen[1].target


def test_relative_location_is_resolved_against_the_response_url() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: (
            reply(handler, 302, [("Location", "next")])
            if index == 0
            else reply(handler, 200, [("Content-Type", "text/plain")], b"next")
        )
        result, _capture = run(
            {"method": "GET", "url": origin_of(httpd) + "/dir/start"}
        )
    assert result.status == "succeeded", result.error_message
    assert httpd.seen[1].target == "/dir/next"


def test_missing_or_non_http_location_fails() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(
            handler, 302, [("Content-Type", "text/plain")], b"stop"
        )
        missing, _capture = run({"method": "GET", "url": origin_of(httpd) + "/a"})
    assert missing.status == "failed"
    assert missing.error_message == "Redirect is missing a Location"
    assert missing.error_detail == {"status_code": 302, "body": "stop"}
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(
            handler, 302, [("Location", "ftp://127.0.0.1/file")]
        )
        bad, _capture = run({"method": "GET", "url": origin_of(httpd) + "/a"})
    assert len(httpd.seen) == 1
    assert bad.error_message == "Redirect URL is not absolute http or https"
    assert bad.error_detail["status_code"] == 302


def test_redirect_location_with_an_illegal_port_fails() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(
            handler, 302, [("Location", "http://127.0.0.1:99999/next")]
        )
        result, _capture = run({"method": "GET", "url": origin_of(httpd) + "/start"})
    assert len(httpd.seen) == 1
    assert result.status == "failed"
    assert result.error_message == "Redirect URL is not absolute http or https"
    assert result.error_detail["status_code"] == 302


def test_redirect_limit_zero_returns_the_3xx() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(
            handler, 302, [("Location", "/next"), ("Content-Type", "text/plain")], b"go"
        )
        result, _capture = run(
            {
                "method": "GET",
                "url": origin_of(httpd) + "/start",
                "max_redirects": 0,
            }
        )
    assert len(httpd.seen) == 1
    assert result.status == "failed"
    assert result.error_detail == {"status_code": 302, "body": "go"}


def test_exhausted_redirect_limit_fails_with_the_status_still_in_hand() -> None:
    with serve() as httpd:
        def script(handler: _Handler, index: int) -> None:
            if index >= 4:
                reply(handler, 500, body=b"too many")
                return
            reply(handler, 302, [("Location", "/again"), ("Content-Type", "text/plain")], b"go")

        httpd.script = script
        result, _capture = run(
            {"method": "GET", "url": origin_of(httpd) + "/start", "max_redirects": 1}
        )
    assert len(httpd.seen) == 2
    assert result.status == "failed"
    assert result.error_detail == {"status_code": 302, "body": "go"}


def test_absent_redirect_limit_follows_five() -> None:
    with serve() as httpd:
        def script(handler: _Handler, index: int) -> None:
            if index >= 8:
                reply(handler, 500, body=b"too many")
                return
            reply(handler, 302, [("Location", "/again")])

        httpd.script = script
        result, _capture = run({"method": "GET", "url": origin_of(httpd) + "/start"})
    assert len(httpd.seen) == 6
    assert result.error_detail["status_code"] == 302


def test_null_redirect_limit_still_follows() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: (
            reply(handler, 302, [("Location", "/next")])
            if index == 0
            else reply(handler, 200, [("Content-Type", "text/plain")], b"ok")
        )
        result, _capture = run(
            {
                "method": "GET",
                "url": origin_of(httpd) + "/start",
                "max_redirects": None,
            }
        )
    assert result.status == "succeeded", result.error_message
    assert len(httpd.seen) == 2


def test_http_error_keeps_status_and_body_on_the_error_output() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(
            handler, 400, [("Content-Type", "application/json")], b'{"error":"nope"}'
        )
        node = _engine_node(
            {"method": "GET", "url": origin_of(httpd) + "/fail"},
            on_error="error_output",
        )
        outcome, hooks = _engine(node)
    assert outcome.status == "succeeded"
    assert hooks.outputs["call"] == {
        "code": "CHANNEL_NODE_FAILED",
        "message": "HTTP 400",
        "detail": {"status_code": 400, "body": {"error": "nope"}},
    }


def test_continue_stores_a_null_output() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 404, body=b"missing")
        node = _engine_node(
            {"method": "GET", "url": origin_of(httpd) + "/missing"},
            on_error="continue",
        )
        outcome, hooks = _engine(node)
    assert outcome.status == "succeeded"
    assert hooks.outputs["call"] is None


def test_retry_sends_the_post_again() -> None:
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 500, body=b"no")
        node = _engine_node(
            {
                "method": "POST",
                "url": origin_of(httpd) + "/retry",
                "body_mode": "raw",
                "body": "again",
                "content_type": "text/plain",
            },
            retry={"max_tries": 2, "wait_sec": 0},
        )
        outcome, hooks = _engine(node)
    assert outcome.status == "failed"
    assert [item.method for item in httpd.seen] == ["POST", "POST"]
    assert [item.body for item in httpd.seen] == [b"again", b"again"]
    assert hooks.order == ["call", "call"]


def test_retry_after_on_429_and_503_sets_the_minimum_wait() -> None:
    future = formatdate(time.time() + 120, usegmt=True)
    cases = [
        (429, "12", 12),
        (503, "0", 0),
        (429, "3601", 3600),
        (503, "Sun, 06 Nov 1994 08:49:37 GMT", 0),
        (429, future, None),
    ]
    with serve() as httpd:
        plan: list[tuple[int, str]] = [(status, header) for status, header, _expected in cases]

        def script(handler: _Handler, index: int) -> None:
            status, header = plan[index]
            reply(
                handler,
                status,
                [("Retry-After", header), ("Content-Type", "application/json")],
                b'{"wait":true}',
            )

        httpd.script = script
        url = origin_of(httpd) + "/limited"
        for status, _header, expected in cases:
            result, _capture = run({"method": "GET", "url": url})
            assert result.status == "failed"
            assert result.error_detail["status_code"] == status
            assert result.error_detail["body"] == {"wait": True}
            if expected is None:
                assert 90 <= result.error_detail["retry_after_sec"] <= 120
                assert result.minimum_wait_sec == result.error_detail["retry_after_sec"]
            else:
                assert result.error_detail["retry_after_sec"] == expected
                assert result.minimum_wait_sec == expected


def test_invalid_retry_after_and_other_statuses_set_neither() -> None:
    with serve() as httpd:
        def script(handler: _Handler, index: int) -> None:
            status = 429 if index == 0 else 500
            reply(
                handler,
                status,
                [("Retry-After", "soon" if index == 0 else "15"), ("Content-Type", "text/plain")],
                b"no",
            )

        httpd.script = script
        url = origin_of(httpd) + "/limited"
        invalid, _capture = run({"method": "GET", "url": url})
        other, _capture = run({"method": "GET", "url": url})
    assert "retry_after_sec" not in invalid.error_detail
    assert invalid.minimum_wait_sec is None
    assert other.error_detail == {"status_code": 500, "body": "no"}
    assert other.minimum_wait_sec is None


def test_request_over_the_cap_is_not_sent() -> None:
    set_parameter("channel_http_response_max_bytes", 65536, actor_user_id=None)
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 204)
        result, _capture = run(
            {
                "method": "POST",
                "url": origin_of(httpd) + "/big",
                "body_mode": "raw",
                "body": "x" * 65537,
                "content_type": "text/plain",
            }
        )
    assert httpd.seen == []
    assert result.status == "failed"
    assert result.error_message == "Request body exceeds the size cap"
    assert result.error_detail is None


def test_request_at_the_cap_is_sent() -> None:
    set_parameter("channel_http_response_max_bytes", 65536, actor_user_id=None)
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 204)
        result, _capture = run(
            {
                "method": "POST",
                "url": origin_of(httpd) + "/fit",
                "body_mode": "raw",
                "body": "x" * 65536,
                "content_type": "text/plain",
            }
        )
    assert result.status == "succeeded", result.error_message
    assert len(httpd.seen[0].body) == 65536


@pytest.mark.parametrize("status", [200, 400])
def test_response_over_the_cap_omits_the_body(status: int) -> None:
    set_parameter("channel_http_response_max_bytes", 65536, actor_user_id=None)
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(
            handler, status, [("Content-Type", "text/plain")], b"y" * 65537
        )
        result, _capture = run({"method": "GET", "url": origin_of(httpd) + "/big"})
    assert result.status == "failed"
    assert result.error_message == "Response body exceeds the size cap"
    assert result.error_detail["status_code"] == status
    assert result.error_detail["body_bytes"] > 65536
    assert "body" not in result.error_detail


def test_response_at_the_cap_is_kept() -> None:
    set_parameter("channel_http_response_max_bytes", 65536, actor_user_id=None)
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(
            handler, 200, [("Content-Type", "text/plain")], b"z" * 65536
        )
        result, _capture = run({"method": "GET", "url": origin_of(httpd) + "/fit"})
    assert result.status == "succeeded", result.error_message
    assert len(result.output["body"]) == 65536


def test_compressed_body_that_expands_past_the_cap_fails() -> None:
    set_parameter("channel_http_response_max_bytes", 65536, actor_user_id=None)
    wire = gzip.compress(b"x" * 70000)
    assert len(wire) < 65536
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(
            handler,
            200,
            [("Content-Type", "text/plain"), ("Content-Encoding", "gzip")],
            wire,
        )
        result, _capture = run({"method": "GET", "url": origin_of(httpd) + "/gzip"})
    assert result.status == "failed"
    assert result.error_detail["status_code"] == 200
    assert result.error_detail["body_bytes"] > 65536
    assert "body" not in result.error_detail


def test_cap_is_the_value_read_at_the_start(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def accessor() -> int:
        calls["n"] += 1
        return 65536 if calls["n"] == 1 else 10

    monkeypatch.setattr(
        "backend.channel.nodes.action.http.channel_http_response_max_bytes",
        accessor,
    )
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(
            handler, 200, [("Content-Type", "text/plain")], b"x" * 100
        )
        result, _capture = run(
            {
                "method": "POST",
                "url": origin_of(httpd) + "/once",
                "body_mode": "raw",
                "body": "y" * 100,
                "content_type": "text/plain",
            }
        )
    assert result.status == "succeeded", result.error_message
    assert len(result.output["body"]) == 100


def test_slow_body_fails_at_the_deadline_without_a_status() -> None:
    def script(handler: _Handler, index: int) -> None:
        del index
        handler.send_response(200)
        handler.send_header("Content-Type", "text/plain")
        handler.send_header("Content-Length", "4")
        handler.send_header("Connection", "close")
        handler.end_headers()
        time.sleep(2)
        try:
            handler.wfile.write(b"late")
        except OSError:
            return

    with serve() as httpd:
        httpd.script = script
        result, _capture = run(
            {
                "method": "GET",
                "url": origin_of(httpd) + "/slow",
                "timeout_sec": 1,
            }
        )
    assert result.status == "failed"
    assert result.error_message == "Timed out calling 127.0.0.1"
    assert result.error_detail is None
    assert "/slow" not in (result.error_message or "")


def test_blank_timeout_waits_longer_than_one_second() -> None:
    def script(handler: _Handler, index: int) -> None:
        del index
        reply(handler, 200, [("Content-Type", "text/plain")], b"ok", delay=2)

    with serve() as httpd:
        httpd.script = script
        result, _capture = run(
            {"method": "GET", "url": origin_of(httpd) + "/wait", "timeout_sec": None}
        )
    assert result.status == "succeeded", result.error_message
    assert result.output["body"] == "ok"


def test_one_deadline_covers_redirects() -> None:
    with serve() as first, serve() as second:
        first.script = lambda handler, index: reply(
            handler, 302, [("Location", origin_of(second) + "/next")], delay=0.6
        )
        second.script = lambda handler, index: reply(
            handler, 200, [("Content-Type", "text/plain")], b"late", delay=0.6
        )
        result, _capture = run(
            {
                "method": "GET",
                "url": origin_of(first) + "/start",
                "timeout_sec": 1,
            }
        )
    assert len(first.seen) == 1
    assert len(second.seen) == 1
    assert result.status == "failed"
    assert result.error_message == "Timed out calling 127.0.0.1"
    assert result.error_detail is None


def test_connection_failure_names_the_host_only() -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    result, _capture = run(
        {"method": "GET", "url": f"http://127.0.0.1:{port}/secret-path?token=sekret"}
    )
    assert result.status == "failed"
    assert result.error_message == "Connection failed for 127.0.0.1"
    assert result.error_detail is None
    assert "secret-path" not in (result.error_message or "")
    assert "sekret" not in (result.error_message or "")


def test_tls_verification_failure_has_no_status(tmp_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_path = tmp_path / "key.pem"
    cert_path = tmp_path / "cert.pem"
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    with serve((cert_path, key_path)) as httpd:
        httpd.script = lambda handler, index: reply(handler, 200, body=b"ok")
        result, _capture = run(
            {"method": "GET", "url": f"https://127.0.0.1:{httpd.server_address[1]}/secret"}
        )
    assert result.status == "failed"
    assert result.error_message == "TLS verification failed for 127.0.0.1"
    assert result.error_detail is None
    assert "secret" not in (result.error_message or "")
    assert httpd.seen == []


def test_missing_account_fails_validation_and_execution() -> None:
    config = {
        "method": "GET",
        "url": "http://127.0.0.1/missing",
        "http_account_id": "hac_missing",
    }
    problems = NODE_TYPE.check(config, _Resolver())
    assert [(item.code, item.path) for item in problems] == [
        ("CHANNEL_REFERENCE_UNRESOLVED", ("http_account_id",))
    ]
    with serve() as httpd:
        httpd.script = lambda handler, index: reply(handler, 204)
        result, _capture = run(
            {
                "method": "GET",
                "url": origin_of(httpd) + "/missing",
                "http_account_id": "hac_missing",
            }
        )
    assert httpd.seen == []
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_NODE_FAILED"
    assert result.error_message == "HTTP Account was not found"


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_get_and_head_reject_a_non_blank_body(method: str) -> None:
    problems = NODE_TYPE.check(
        {"method": method, "url": "http://127.0.0.1/", "body": "{{ value }}"},
        _Resolver(),
    )
    assert any(item.path == ("body",) for item in problems)
    blank = NODE_TYPE.check(
        {"method": method, "url": "http://127.0.0.1/", "body": "   "},
        _Resolver(),
    )
    assert blank == []


@pytest.mark.parametrize("name", _FORBIDDEN)
def test_forbidden_header_names_fail_validation(name: str) -> None:
    problems = NODE_TYPE.check(
        {
            "method": "GET",
            "url": "http://127.0.0.1/",
            "headers": [{"name": name.upper(), "value": "x"}],
        },
        _Resolver(),
    )
    assert [(item.code, item.path) for item in problems] == [
        ("CHANNEL_NODE_CONFIG_INVALID", ("headers", 0, "name"))
    ]


def test_raw_body_requires_a_content_type_and_plain_text_validates() -> None:
    missing = NODE_TYPE.check(
        {
            "method": "POST",
            "url": "http://127.0.0.1/",
            "body_mode": "raw",
            "body": "hello",
        },
        _Resolver(),
    )
    assert any(item.path == ("content_type",) for item in missing)
    graph = {
        "nodes": [
            {
                "id": "start",
                "type": "trigger.manual",
                "name": "Start",
                "ref": "start",
                "position": {"x": 0, "y": 0},
                "config": {},
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "call",
                "type": "action.http",
                "name": "Call",
                "ref": "call",
                "position": {"x": 0, "y": 1},
                "config": {
                    "method": "POST",
                    "url": "http://127.0.0.1/hook",
                    "body_mode": "raw",
                    "body": "hello",
                    "content_type": "text/plain",
                },
                "on_error": "stop",
                "retry": None,
            },
        ],
        "edges": [
            {
                "id": "start-call",
                "source": {"node_id": "start", "port": "main"},
                "target": {"node_id": "call", "port": "main"},
            }
        ],
        "settings": {},
    }
    errors = [item for item in validate(graph, _Resolver()) if item.severity != "warning"]
    assert errors == []


def test_configuration_schema_matches_the_product_limits() -> None:
    schema = NODE_TYPE.config_schema
    properties = schema["properties"]
    assert schema["required"] == ["method", "url"]
    assert properties["method"]["enum"] == ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]
    assert properties["body_mode"]["enum"] == ["json", "raw"]
    assert properties["body_mode"]["default"] == "json"
    assert properties["url"]["maxLength"] == 8192
    assert properties["url"]["x-refraq-template"] == {"type": "string"}
    assert properties["query"]["maxItems"] == 32
    assert properties["headers"]["maxItems"] == 32
    assert properties["query"]["items"]["properties"]["name"]["maxLength"] == 2048
    assert properties["headers"]["items"]["properties"]["name"]["maxLength"] == 128
    assert properties["headers"]["items"]["properties"]["name"]["minLength"] == 1
    assert properties["headers"]["items"]["properties"]["value"]["maxLength"] == 4096
    assert properties["http_account_id"]["x-refraq-ref"] == "http_account"
    assert "x-refraq-template" not in properties["http_account_id"]
    assert properties["timeout_sec"]["minimum"] == 1
    assert properties["timeout_sec"]["maximum"] == 120
    assert properties["max_redirects"]["minimum"] == 0
    assert properties["max_redirects"]["maximum"] == 10
    assert NODE_TYPE.permission is None
    assert [port.port for port in NODE_TYPE.inputs] == ["main"]
    assert [port.port for port in NODE_TYPE.outputs] == ["main", "error"]
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors({"method": "GET", "url": "http://127.0.0.1/"})) == []
    assert (
        list(
            validator.iter_errors(
                {
                    "method": "GET",
                    "url": "http://127.0.0.1/",
                    "timeout_sec": None,
                    "max_redirects": None,
                    "http_account_id": None,
                }
            )
        )
        == []
    )
    assert list(validator.iter_errors({"method": "GET", "url": "x" * 8193}))
    assert list(
        validator.iter_errors(
            {
                "method": "GET",
                "url": "http://127.0.0.1/",
                "query": [{"name": "q", "value": "1"}] * 33,
            }
        )
    )
    assert list(validator.iter_errors({"method": "GET", "url": "http://127.0.0.1/", "timeout_sec": 0}))
    assert list(validator.iter_errors({"method": "GET", "url": "http://127.0.0.1/", "max_redirects": 11}))
    token = NODE_TYPE.check(
        {
            "method": "GET",
            "url": "http://127.0.0.1/",
            "headers": [{"name": "Bad Name", "value": "x"}],
        },
        _Resolver(),
    )
    assert any(item.path == ("headers", 0, "name") for item in token)


def _engine_node(
    config: dict[str, Any],
    *,
    on_error: str = "stop",
    retry: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "id": "call",
        "type": "action.http",
        "name": "Call",
        "ref": "call",
        "position": {"x": 0, "y": 0},
        "config": config,
        "on_error": on_error,
        "retry": retry,
    }


def _engine(node: dict[str, Any]):
    graph = {"nodes": [node], "edges": [], "settings": {}}
    hooks = FakeHooks()
    outcome = execute(graph, "call", list_node_types(), _Resolver(), hooks)
    return outcome, hooks
