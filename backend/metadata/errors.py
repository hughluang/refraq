"""Domain errors for metadata foundation Source / Connection / Job / Catalog."""

from __future__ import annotations

from backend.admin.errors import AuthError


class SourceNotFound(AuthError):
    code = "SOURCE_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Source not found"


class SourceKeyDuplicate(AuthError):
    code = "SOURCE_KEY_DUPLICATE"
    http_status = 409

    def _default_message(self) -> str:
        return "Source key already exists"


class SourceKindUnsupported(AuthError):
    code = "SOURCE_KIND_UNSUPPORTED"
    http_status = 400

    def _default_message(self) -> str:
        return "Source kind is not supported in this slice"


class SourceConnectionExists(AuthError):
    code = "SOURCE_CONNECTION_EXISTS"
    http_status = 409

    def _default_message(self) -> str:
        return "This source already has a connection"


class SourceConnectionKindInvalid(AuthError):
    code = "SOURCE_CONNECTION_KIND_INVALID"
    http_status = 400

    def _default_message(self) -> str:
        return "Connections require a database Source"


class ConnectionNotFound(AuthError):
    code = "CONNECTION_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Connection not found"


class ConnectionEngineUnsupported(AuthError):
    code = "CONNECTION_ENGINE_UNSUPPORTED"
    http_status = 400

    def _default_message(self) -> str:
        return "Engine is not supported"


class CatalogObjectNotFound(AuthError):
    code = "CATALOG_OBJECT_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Catalog object not found"


class JobSourceDisabled(AuthError):
    code = "JOB_SOURCE_DISABLED"
    http_status = 400

    def _default_message(self) -> str:
        return "Source is not usable for jobs"


class JobConnectionDisabled(AuthError):
    code = "JOB_CONNECTION_DISABLED"
    http_status = 400

    def _default_message(self) -> str:
        return "Connection is not usable for this job"


class JobSecretMissing(AuthError):
    code = "JOB_SECRET_MISSING"
    http_status = 400

    def _default_message(self) -> str:
        return "Connection secret is missing"


class JobInputInvalid(AuthError):
    code = "JOB_INPUT_INVALID"
    http_status = 400

    def _default_message(self) -> str:
        return "Job kind or input is invalid"


class JobNotCancellable(AuthError):
    code = "JOB_NOT_CANCELLABLE"
    http_status = 400

    def _default_message(self) -> str:
        return "Job is already terminal"


class JobAlreadyActive(AuthError):
    code = "JOB_ALREADY_ACTIVE"
    http_status = 409

    def _default_message(self) -> str:
        return "A non-terminal structure job already exists for this source"


class JobNotFound(AuthError):
    code = "JOB_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Job not found"


class JobConnectionMismatch(AuthError):
    code = "JOB_CONNECTION_MISMATCH"
    http_status = 400

    def _default_message(self) -> str:
        return "connection_id does not match the source connection"


class SourceValidationError(AuthError):
    code = "SOURCE_VALIDATION_ERROR"
    http_status = 400

    def _default_message(self) -> str:
        return "Source validation failed"
