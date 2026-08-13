"""HTTP Problem Details + Request ID contract (docs/conventions-errors.md)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.admin.errors import AuthInvalidCredentials
from backend.core.errors import (
    CODE_HTTP_METHOD_NOT_ALLOWED,
    CODE_HTTP_NOT_FOUND,
    CODE_INTERNAL_ERROR,
    CODE_REQUEST_INVALID,
    DETAIL_INTERNAL_ERROR,
    DETAIL_REQUEST_INVALID,
    FIELD_VALUE_MISSING,
)
from backend.core.request_id import (
    CELERY_HEADER,
    correlation_id,
    load_request_id_from_celery,
    transfer_request_id_to_celery,
)
from backend.main import app
from backend.metadata.mcp_server import _err
from backend.tests.problem import assert_problem

INBOUND_HEX = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_login_validation_is_request_invalid_without_pydantic_input(
    client: TestClient,
) -> None:
    response = client.post("/auth/login", json={"password": "secret-must-not-echo"})
    body = assert_problem(
        response,
        status=422,
        code=CODE_REQUEST_INVALID,
        detail=DETAIL_REQUEST_INVALID,
    )
    dumped = response.text
    assert "secret-must-not-echo" not in dumped
    assert '"loc"' not in dumped
    assert '"input"' not in dumped
    details = body["details"]
    assert details
    fields = {item["field"]: item for item in details}
    assert "account" in fields
    assert fields["account"]["code"] == FIELD_VALUE_MISSING
    assert "body.account" not in fields
    for item in details:
        assert set(item) == {"field", "code", "message"}


def test_unmatched_route_is_http_not_found(client: TestClient) -> None:
    assert_problem(
        client.get("/__no_such_route__"),
        status=404,
        code=CODE_HTTP_NOT_FOUND,
    )


def test_wrong_method_is_method_not_allowed(client: TestClient) -> None:
    assert_problem(
        client.get("/auth/login"),
        status=405,
        code=CODE_HTTP_METHOD_NOT_ALLOWED,
    )


def test_unhandled_error_hides_exception_text() -> None:
    @app.get("/__test/internal-error")
    def _boom() -> None:
        raise RuntimeError("do-not-leak-this")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/__test/internal-error",
            headers={"X-Request-ID": INBOUND_HEX},
        )
    body = assert_problem(
        response,
        status=500,
        code=CODE_INTERNAL_ERROR,
        detail=DETAIL_INTERNAL_ERROR,
    )
    assert "do-not-leak-this" not in response.text
    assert "RuntimeError" not in response.text
    assert body["request_id"] == INBOUND_HEX


def test_success_echoes_request_id_header_not_body(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    rid = response.headers.get("x-request-id")
    assert rid
    assert "request_id" not in response.json()


def test_inbound_hex_request_id_is_reused(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": INBOUND_HEX})
    assert response.headers["x-request-id"] == INBOUND_HEX


def test_inbound_invalid_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "not a uuid"})
    rid = response.headers["x-request-id"]
    assert rid != "not a uuid"
    assert len(rid) == 32


def test_error_body_request_id_matches_header(client: TestClient) -> None:
    response = client.get("/__no_such_route__", headers={"X-Request-ID": INBOUND_HEX})
    body = assert_problem(response, status=404, code=CODE_HTTP_NOT_FOUND)
    assert body["request_id"] == INBOUND_HEX


def test_mcp_error_keeps_message_not_detail() -> None:
    payload = _err(AuthInvalidCredentials())
    assert '"message"' in payload
    assert '"detail"' not in payload
    parsed = __import__("json").loads(payload)
    assert parsed["error"]["code"] == "AUTH_INVALID_CREDENTIALS"
    assert "type" not in parsed["error"]
    assert "request_id" not in parsed["error"]


def test_celery_header_round_trip() -> None:
    correlation_id.set("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    headers: dict[str, str] = {}
    transfer_request_id_to_celery(headers)
    assert headers[CELERY_HEADER] == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    correlation_id.set(None)
    task = SimpleNamespace(request=SimpleNamespace(get=headers.get))
    load_request_id_from_celery(task)
    assert correlation_id.get() == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    correlation_id.set(None)
