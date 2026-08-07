"""Domain errors for metadata foundation Source / Job / Catalog."""

from __future__ import annotations

from backend.admin.errors import AuthError


class SourceNotFound(AuthError):
    code = "SOURCE_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Source not found"


class SourceNotDisabled(AuthError):
    code = "SOURCE_NOT_DISABLED"
    http_status = 409

    def _default_message(self) -> str:
        return "Source must be disabled before delete"


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


class SourceAccessRequired(AuthError):
    code = "SOURCE_ACCESS_REQUIRED"
    http_status = 400

    def _default_message(self) -> str:
        return "A database source requires engine and access"


class SourceAccessInvalid(AuthError):
    code = "SOURCE_ACCESS_INVALID"
    http_status = 400

    def _default_message(self) -> str:
        return "Source access is invalid for this engine"


class SourceEngineUnsupported(AuthError):
    code = "SOURCE_ENGINE_UNSUPPORTED"
    http_status = 400

    def _default_message(self) -> str:
        return "Engine is not supported"


class SourceSecretRequired(AuthError):
    code = "SOURCE_SECRET_REQUIRED"
    http_status = 400

    def _default_message(self) -> str:
        return "Source access credentials are required for this probe"


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


class JobSecretMissing(AuthError):
    code = "JOB_SECRET_MISSING"
    http_status = 400

    def _default_message(self) -> str:
        return "Source access is missing"


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


class SourceValidationError(AuthError):
    code = "SOURCE_VALIDATION_ERROR"
    http_status = 400

    def _default_message(self) -> str:
        return "Source validation failed"
