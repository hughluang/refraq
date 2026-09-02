"""Model Service domain errors."""

from __future__ import annotations

from backend.core.errors import AppError


class ModelServiceError(AppError):
    code = "MODEL_SERVICE_ERROR"
    http_status = 400


class ModelServiceNotFound(ModelServiceError):
    code = "MODEL_SERVICE_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Model Service not found"


class ModelServiceInvalidConfig(ModelServiceError):
    code = "MODEL_SERVICE_INVALID_CONFIG"

    def _default_message(self) -> str:
        return "Model Service configuration is invalid"


class ModelServicePurposeUnsupported(ModelServiceError):
    code = "MODEL_SERVICE_PURPOSE_UNSUPPORTED"

    def _default_message(self) -> str:
        return "Model Service purpose is not implemented"


class ModelServiceProtocolUnsupported(ModelServiceError):
    code = "MODEL_SERVICE_PROTOCOL_UNSUPPORTED"

    def _default_message(self) -> str:
        return "Model Service protocol is not implemented"


class ModelServiceWireImmutable(ModelServiceError):
    code = "MODEL_SERVICE_WIRE_IMMUTABLE"
    http_status = 409

    def _default_message(self) -> str:
        return "Model and protocol cannot change while the service is in use"


class ModelServiceNotInUse(ModelServiceError):
    code = "MODEL_SERVICE_NOT_IN_USE"
    http_status = 409

    def _default_message(self) -> str:
        return "This purpose has no in-use Model Service"


class ModelServiceCleanupForbidden(ModelServiceError):
    code = "MODEL_SERVICE_CLEANUP_FORBIDDEN"
    http_status = 409

    def _default_message(self) -> str:
        return "Cleanup is allowed only when closed or when no service is in use"


class ModelServiceSecretRequired(ModelServiceError):
    code = "MODEL_SERVICE_SECRET_REQUIRED"
    http_status = 409

    def _default_message(self) -> str:
        return "URL change requires a new API key or an explicit no-key declaration"


class ModelServiceUnavailable(ModelServiceError):
    code = "MODEL_SERVICE_UNAVAILABLE"
    http_status = 503

    def _default_message(self) -> str:
        return "Embeddings endpoint cannot be reached"


class ModelServiceTestFailed(ModelServiceError):
    code = "MODEL_SERVICE_TEST_FAILED"

    def _default_message(self) -> str:
        return "Embeddings endpoint returned an unusable response"
