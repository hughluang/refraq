"""Helpers for HTTP Problem Details assertions."""

from __future__ import annotations

from typing import Any

from httpx import Response

from backend.core.errors import problem_type


def assert_problem(
    response: Response,
    *,
    status: int,
    code: str,
    detail: str | None = None,
) -> dict[str, Any]:
    assert response.status_code == status
    content_type = response.headers.get("content-type", "")
    assert content_type.startswith("application/problem+json")
    body = response.json()
    assert body["type"] == problem_type(code)
    assert body["status"] == status
    assert body["code"] == code
    assert "message" not in body
    assert "request_id" in body and body["request_id"]
    assert response.headers.get("x-request-id") == body["request_id"]
    if detail is not None:
        assert body["detail"] == detail
    else:
        assert isinstance(body["detail"], str) and body["detail"]
    return body
