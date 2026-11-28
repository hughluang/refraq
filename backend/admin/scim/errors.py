"""SCIM 2.0 RFC 7644 errors and admin token errors."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from backend.core.errors import AppError

SCIM_CONTENT_TYPE = "application/scim+json"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"


class ScimTokenNotFound(AppError):
    code = "SCIM_TOKEN_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "SCIM provisioning token not found"


class ScimError(Exception):
    """RFC 7644 SCIM error serialized with application/scim+json."""

    def __init__(
        self,
        status: int,
        detail: str,
        *,
        scim_type: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.scim_type = scim_type

    def to_response(self) -> JSONResponse:
        body: dict[str, object] = {
            "schemas": [SCIM_ERROR_SCHEMA],
            "status": str(self.status),
            "detail": self.detail,
        }
        if self.scim_type:
            body["scimType"] = self.scim_type
        return JSONResponse(
            status_code=self.status,
            content=body,
            media_type=SCIM_CONTENT_TYPE,
        )
