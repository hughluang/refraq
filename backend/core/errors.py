"""Cross-package error primitive and HTTP Problem Details serialization."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.core.request_id import HEADER_NAME, get_request_id

PROBLEM_TYPE_PREFIX = "urn:refraq:problem:"

CODE_REQUEST_INVALID = "REQUEST_INVALID"
CODE_INTERNAL_ERROR = "INTERNAL_ERROR"
CODE_HTTP_NOT_FOUND = "HTTP_NOT_FOUND"
CODE_HTTP_METHOD_NOT_ALLOWED = "HTTP_METHOD_NOT_ALLOWED"
CODE_HTTP_ERROR = "HTTP_ERROR"

DETAIL_REQUEST_INVALID = "Request validation failed"
DETAIL_INTERNAL_ERROR = "Internal server error"

FIELD_VALUE_MISSING = "VALUE_MISSING"
FIELD_VALUE_INVALID = "VALUE_INVALID"

_LOC_PREFIXES = frozenset({"body", "query", "path", "header", "cookie"})


RETRY_AFTER_DEFAULT_SEC = 1


class AppError(Exception):
    """Base class for errors that map to an API error response."""

    code: str = "APP_ERROR"
    http_status: int = 400
    retry_after_sec: int | None = None

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self._default_message()

    def _default_message(self) -> str:
        return self.code

    def extra_headers(self) -> dict[str, str]:
        if self.retry_after_sec is None:
            return {}
        return {"Retry-After": str(int(self.retry_after_sec))}


class PlatformCapacityExceeded(AppError):
    code = "PLATFORM_CAPACITY_EXCEEDED"
    http_status = 503
    retry_after_sec = RETRY_AFTER_DEFAULT_SEC

    def _default_message(self) -> str:
        return "Platform is at capacity"


class PlatformTimeout(AppError):
    code = "PLATFORM_TIMEOUT"
    http_status = 504

    def _default_message(self) -> str:
        return "Platform request exceeded the statement timeout"


class AdmissionCapacityExceeded(AppError):
    code = "ADMISSION_CAPACITY_EXCEEDED"
    http_status = 503
    retry_after_sec = RETRY_AFTER_DEFAULT_SEC

    def _default_message(self) -> str:
        return "Platform admission is at capacity"


class AdmissionActorLimitExceeded(AppError):
    code = "ADMISSION_ACTOR_LIMIT_EXCEEDED"
    http_status = 429
    retry_after_sec = RETRY_AFTER_DEFAULT_SEC

    def _default_message(self) -> str:
        return "This user already holds the admission share"


class ProblemFieldError(BaseModel):
    field: str
    code: str
    message: str


class ProblemDetails(BaseModel):
    """RFC 9457 Problem Details plus frozen extensions `code` / `request_id` / `details`."""

    model_config = ConfigDict(extra="allow")

    type: str
    status: int
    detail: str
    code: str
    request_id: str
    details: list[ProblemFieldError] | None = Field(default=None)


class ProblemJSONResponse(JSONResponse):
    media_type = "application/problem+json"


def problem_type(code: str) -> str:
    return f"{PROBLEM_TYPE_PREFIX}{code}"


def problem_body(
    *,
    status: int,
    code: str,
    detail: str,
    details: list[ProblemFieldError] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    payload = ProblemDetails(
        type=problem_type(code),
        status=status,
        detail=detail,
        code=code,
        request_id=request_id or get_request_id() or "",
        details=details or None,
    )
    return payload.model_dump(exclude_none=True)


def problem_response(
    *,
    status: int,
    code: str,
    detail: str,
    details: list[ProblemFieldError] | None = None,
    request_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> ProblemJSONResponse:
    body = problem_body(
        status=status,
        code=code,
        detail=detail,
        details=details,
        request_id=request_id,
    )
    response_headers = {HEADER_NAME: str(body["request_id"])}
    if headers:
        response_headers.update(headers)
    return ProblemJSONResponse(
        status_code=status,
        content=body,
        headers=response_headers,
    )


def field_path_from_loc(loc: tuple[object, ...]) -> str:
    parts = [str(item) for item in loc]
    if parts and parts[0] in _LOC_PREFIXES:
        parts = parts[1:]
    return ".".join(parts)


def validation_field_errors(errors: list[dict[str, Any]]) -> list[ProblemFieldError]:
    fields: list[ProblemFieldError] = []
    for item in errors:
        loc = item.get("loc") or ()
        err_type = str(item.get("type") or "")
        code = FIELD_VALUE_MISSING if err_type == "missing" else FIELD_VALUE_INVALID
        fields.append(
            ProblemFieldError(
                field=field_path_from_loc(tuple(loc)),
                code=code,
                message=str(item["msg"]),
            )
        )
    return fields


def http_status_problem_code(status: int) -> str:
    if status == 404:
        return CODE_HTTP_NOT_FOUND
    if status == 405:
        return CODE_HTTP_METHOD_NOT_ALLOWED
    return CODE_HTTP_ERROR
