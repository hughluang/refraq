"""Domain errors for metadata foundation Source / Job / Catalog."""

from __future__ import annotations

from backend.core.errors import AppError

__all__ = [
    "BusinessDomainCodeConflict",
    "BusinessDomainInUse",
    "BusinessDomainNotFound",
    "BusinessDomainUnknown",
    "CatalogColumnNotFound",
    "CatalogJoinNotFound",
    "CatalogObjectNotFound",
    "CatalogSearchQueryRequired",
    "JobAlreadyActive",
    "JobInputInvalid",
    "JobSecretMissing",
    "JobSourceDisabled",
    "JoinCrossSource",
    "JoinEvidenceRequired",
    "JoinInvalid",
    "JoinPathUnavailable",
    "LocatorInvalid",
    "QueryFailed",
    "QueryMultiStatement",
    "QueryNotReadonly",
    "QueryRowLimit",
    "QueryTimeout",
    "SampleColumnUnknown",
    "SampleFilterInvalid",
    "SemanticColumnUnknown",
    "SourceAccessInvalid",
    "SourceAccessRequired",
    "SourceEngineUnsupported",
    "SourceKeyDuplicate",
    "SourceKindUnsupported",
    "SourceNotDisabled",
    "SourceNotFound",
    "SourceSecretRequired",
    "SourceValidationError",
]


class SourceNotFound(AppError):
    code = "SOURCE_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Source not found"


class SourceNotDisabled(AppError):
    code = "SOURCE_NOT_DISABLED"
    http_status = 409

    def _default_message(self) -> str:
        return "Source must be disabled before delete"


class SourceKeyDuplicate(AppError):
    code = "SOURCE_KEY_DUPLICATE"
    http_status = 409

    def _default_message(self) -> str:
        return "Source key already exists"


class SourceKindUnsupported(AppError):
    code = "SOURCE_KIND_UNSUPPORTED"
    http_status = 400

    def _default_message(self) -> str:
        return "Source kind is not supported in this slice"


class SourceAccessRequired(AppError):
    code = "SOURCE_ACCESS_REQUIRED"
    http_status = 400

    def _default_message(self) -> str:
        return "A database source requires engine and access"


class SourceAccessInvalid(AppError):
    code = "SOURCE_ACCESS_INVALID"
    http_status = 400

    def _default_message(self) -> str:
        return "Source access is invalid for this engine"


class SourceEngineUnsupported(AppError):
    code = "SOURCE_ENGINE_UNSUPPORTED"
    http_status = 400

    def _default_message(self) -> str:
        return "Engine is not supported"


class SourceSecretRequired(AppError):
    code = "SOURCE_SECRET_REQUIRED"
    http_status = 400

    def _default_message(self) -> str:
        return "Source access credentials are required for this probe"


class LocatorInvalid(AppError):
    code = "LOCATOR_INVALID"
    http_status = 400

    def _default_message(self) -> str:
        return "Locator key is invalid"


class CatalogObjectNotFound(AppError):
    code = "CATALOG_OBJECT_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Catalog object not found"


class CatalogColumnNotFound(AppError):
    code = "CATALOG_COLUMN_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Catalog column not found"


class SemanticColumnUnknown(AppError):
    code = "SEMANTIC_COLUMN_UNKNOWN"
    http_status = 400

    def _default_message(self) -> str:
        return "business_primary_key names a column that does not exist on the object"


class BusinessDomainNotFound(AppError):
    code = "BUSINESS_DOMAIN_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Business domain not found"


class BusinessDomainUnknown(AppError):
    code = "BUSINESS_DOMAIN_UNKNOWN"
    http_status = 400

    def _default_message(self) -> str:
        return "business_domain_code does not match an existing Business Domain"


class BusinessDomainCodeConflict(AppError):
    code = "BUSINESS_DOMAIN_CODE_CONFLICT"
    http_status = 409

    def _default_message(self) -> str:
        return "Business domain code already exists"


class BusinessDomainInUse(AppError):
    code = "BUSINESS_DOMAIN_IN_USE"
    http_status = 409

    def _default_message(self) -> str:
        return "Business domain is still referenced by catalog objects"


class CatalogJoinNotFound(AppError):
    code = "CATALOG_JOIN_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Catalog join not found"


class CatalogSearchQueryRequired(AppError):
    code = "CATALOG_SEARCH_QUERY_REQUIRED"
    http_status = 400

    def _default_message(self) -> str:
        return "Search query is required"


class JoinPathUnavailable(AppError):
    code = "JOIN_PATH_UNAVAILABLE"
    http_status = 400

    def _default_message(self) -> str:
        return "Join path start cannot be expanded"


class JoinEvidenceRequired(AppError):
    code = "JOIN_EVIDENCE_REQUIRED"
    http_status = 400

    def _default_message(self) -> str:
        return "Join evidence is required"


class JoinInvalid(AppError):
    code = "JOIN_INVALID"
    http_status = 400

    def _default_message(self) -> str:
        return "Join edge is invalid"


class JoinCrossSource(AppError):
    code = "JOIN_CROSS_SOURCE"
    http_status = 400

    def _default_message(self) -> str:
        return "Join columns must belong to the same Source"


class JobSourceDisabled(AppError):
    code = "JOB_SOURCE_DISABLED"
    http_status = 400

    def _default_message(self) -> str:
        return "Source is not usable for jobs"


class JobSecretMissing(AppError):
    code = "JOB_SECRET_MISSING"
    http_status = 400

    def _default_message(self) -> str:
        return "Source access is missing"


class JobInputInvalid(AppError):
    code = "JOB_INPUT_INVALID"
    http_status = 400

    def _default_message(self) -> str:
        return "Job kind or input is invalid"


class JobAlreadyActive(AppError):
    code = "JOB_ALREADY_ACTIVE"
    http_status = 409

    def _default_message(self) -> str:
        return "A non-terminal structure job already exists for this source"


class SourceValidationError(AppError):
    code = "SOURCE_VALIDATION_ERROR"
    http_status = 400

    def _default_message(self) -> str:
        return "Source validation failed"


class QueryNotReadonly(AppError):
    code = "QUERY_NOT_READONLY"
    http_status = 400

    def _default_message(self) -> str:
        return "SQL is not a single read-only SELECT statement"


class QueryMultiStatement(AppError):
    code = "QUERY_MULTI_STATEMENT"
    http_status = 400

    def _default_message(self) -> str:
        return "Only a single SQL statement is allowed"


class QueryTimeout(AppError):
    code = "QUERY_TIMEOUT"
    http_status = 504

    def _default_message(self) -> str:
        return "Query exceeded the platform timeout"


class QueryRowLimit(AppError):
    code = "QUERY_ROW_LIMIT"
    http_status = 400

    def _default_message(self) -> str:
        return "max_rows exceeds the platform cap"


class QueryFailed(AppError):
    code = "QUERY_FAILED"
    http_status = 502

    def _default_message(self) -> str:
        return "Query execution failed"


class SampleColumnUnknown(AppError):
    code = "SAMPLE_COLUMN_UNKNOWN"
    http_status = 400

    def _default_message(self) -> str:
        return "Sample references an unknown column"


class SampleFilterInvalid(AppError):
    code = "SAMPLE_FILTER_INVALID"
    http_status = 400

    def _default_message(self) -> str:
        return "Sample filter is invalid"
