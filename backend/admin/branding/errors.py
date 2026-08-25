"""Site branding errors."""

from backend.core.errors import CODE_REQUEST_INVALID, AppError


class BrandingInvalid(AppError):
    code = "BRANDING_INVALID"
    http_status = 422


class BrandingAssetInvalid(AppError):
    code = "BRANDING_ASSET_INVALID"
    http_status = 422


class BrandingAssetUnsafe(AppError):
    code = "BRANDING_ASSET_UNSAFE"
    http_status = 422


class BrandingAssetTypeUnsupported(AppError):
    code = "BRANDING_ASSET_TYPE_UNSUPPORTED"
    http_status = 415


class BrandingAssetTooLarge(AppError):
    code = "BRANDING_ASSET_TOO_LARGE"
    http_status = 413


class BrandingAssetNotFound(AppError):
    code = "BRANDING_ASSET_NOT_FOUND"
    http_status = 404


class BrandingReadFailed(AppError):
    code = "BRANDING_READ_FAILED"
    http_status = 503


class BrandingWriteFailed(AppError):
    code = "BRANDING_WRITE_FAILED"
    http_status = 503


class BrandingRequestInvalid(AppError):
    code = CODE_REQUEST_INVALID
    http_status = 422
