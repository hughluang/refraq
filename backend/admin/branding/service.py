"""Site branding use cases, validation, and short-lived public cache."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring as _safe_xml_fromstring

from backend.admin.audit import persist_audit_event
from backend.admin.branding.errors import (
    BrandingAssetInvalid,
    BrandingAssetTooLarge,
    BrandingAssetTypeUnsupported,
    BrandingAssetUnsafe,
    BrandingInvalid,
    BrandingReadFailed,
    BrandingRequestInvalid,
    BrandingWriteFailed,
)
from backend.admin.branding.schemas import (
    BRAND_NAME_MAX_LENGTH,
    TAGLINE_MAX_LENGTH,
    BrandingAssetOut,
    BrandingOut,
)
from backend.admin.branding.store import (
    BrandingAssetKind,
    BrandingAssetOrigin,
    BrandingAssetRecord,
    BrandingRecord,
    BrandingStore,
)
from backend.admin.locales import is_supported_locale
from backend.core.errors import AppError
from backend.core.time import utc_now

MAX_ASSET_BYTES = 512 * 1024
PUBLIC_CACHE_TTL_SECONDS = 30.0
PUBLIC_CACHE_CONTROL = "public, max-age=30, stale-while-revalidate=60"
ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_SEED_DIR = Path(__file__).resolve().parent / "seeds"
_PACKAGED_FILENAMES: dict[BrandingAssetKind, str] = {
    "logo": "logo.svg",
    "favicon": "favicon.png",
}

_SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_FORBIDDEN_SVG_ELEMENTS = frozenset(
    {
        "script",
        "foreignobject",
        "iframe",
        "object",
        "embed",
        "animate",
        "animatetransform",
        "animatemotion",
        "set",
    }
)
_RASTER_DATA_IMAGE_RE = re.compile(
    r"^data:image/(?:png|jpe?g|gif|webp)[;,]",
    re.IGNORECASE,
)
_XML_STYLESHEET_RE = re.compile(br"<\?xml-stylesheet\b", re.IGNORECASE)
_CSS_FORBIDDEN_RE = re.compile(r"(?:@import|javascript\s*:)", re.IGNORECASE)
_CSS_URL_RE = re.compile(r"url\s*\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CachedBranding:
    body: dict[str, Any]
    etag: str


_T = TypeVar("_T")

_cache_lock = threading.Lock()
_cache_store: BrandingStore | None = None
_cache_value: CachedBranding | None = None
_cache_expires_at = 0.0


def _store_read(operation: Callable[[], _T]) -> _T:
    try:
        return operation()
    except AppError:
        raise
    except Exception as exc:
        raise BrandingReadFailed("site branding store read failed") from exc


def _store_write(operation: Callable[[], _T]) -> _T:
    try:
        return operation()
    except AppError:
        raise
    except Exception as exc:
        raise BrandingWriteFailed("site branding store write failed") from exc


def reset_branding_cache() -> None:
    global _cache_store, _cache_value, _cache_expires_at
    with _cache_lock:
        _cache_store = None
        _cache_value = None
        _cache_expires_at = 0.0


def asset_url(kind: BrandingAssetKind, asset: BrandingAssetRecord | None) -> str | None:
    if asset is None:
        return None
    return f"/api/branding/assets/{kind}?v={asset.checksum}"


def present_branding(
    record: BrandingRecord | None,
    *,
    logo: BrandingAssetRecord | None,
    favicon: BrandingAssetRecord | None,
) -> BrandingOut:
    item = record or BrandingRecord()
    return BrandingOut(
        brand_names=dict(item.brand_names or {}),
        taglines=dict(item.taglines or {}),
        primary_color=item.primary_color,
        primary_shades=item.primary_shades,
        show_logo=item.show_logo,
        show_brand_name_with_logo=item.show_brand_name_with_logo,
        logo_url=asset_url("logo", logo),
        favicon_url=asset_url("favicon", favicon),
        logo_source=_asset_source(logo),
        favicon_source=_asset_source(favicon),
    )


def _asset_source(
    asset: BrandingAssetRecord | None,
) -> BrandingAssetOrigin | None:
    if asset is None:
        return None
    return asset.origin


def present_asset(kind: BrandingAssetKind, asset: BrandingAssetRecord) -> BrandingAssetOut:
    url = asset_url(kind, asset)
    assert url is not None
    return BrandingAssetOut(
        kind=kind,
        content_type=asset.content_type,
        byte_size=asset.byte_size,
        checksum=asset.checksum,
        url=url,
    )


def _skip_product_seed() -> bool:
    return os.getenv("REFRAQ_SKIP_SEED") == "1"


def packaged_asset_bytes(kind: BrandingAssetKind) -> bytes:
    return (_SEED_DIR / _PACKAGED_FILENAMES[kind]).read_bytes()


def _packaged_asset_record(kind: BrandingAssetKind) -> BrandingAssetRecord:
    content = packaged_asset_bytes(kind)
    content_type = validate_asset(kind, content)
    checksum = hashlib.sha256(content).hexdigest()
    return BrandingAssetRecord(
        id=f"packaged-{kind}",
        kind=kind,
        content_type=content_type,
        byte_size=len(content),
        bytes=content,
        checksum=checksum,
        origin="seed",
        created_at=utc_now(),
    )


def read_asset(
    store: BrandingStore, kind: BrandingAssetKind
) -> BrandingAssetRecord | None:
    def _resolve() -> BrandingAssetRecord | None:
        overlay = store.get_asset(kind)
        if overlay is not None:
            return overlay
        if _skip_product_seed():
            return None
        return _packaged_asset_record(kind)

    return _store_read(_resolve)


def _read_uncached(store: BrandingStore) -> CachedBranding:
    output = present_branding(
        _store_read(store.get),
        logo=read_asset(store, "logo"),
        favicon=read_asset(store, "favicon"),
    )
    body = output.model_dump(mode="json")
    encoded = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    etag = f'"{hashlib.sha256(encoded).hexdigest()}"'
    return CachedBranding(body=body, etag=etag)


def read_public_branding(store: BrandingStore) -> CachedBranding:
    global _cache_store, _cache_value, _cache_expires_at
    now = time.monotonic()
    with _cache_lock:
        if (
            _cache_store is store
            and _cache_value is not None
            and now < _cache_expires_at
        ):
            return _cache_value
        value = _read_uncached(store)
        _cache_store = store
        _cache_value = value
        _cache_expires_at = now + PUBLIC_CACHE_TTL_SECONDS
        return value


def _normalize_localized(
    value: dict[str, str] | None, *, max_length: int
) -> dict[str, str] | None:
    if value is None:
        return None
    normalized: dict[str, str] = {}
    for raw_locale, raw_text in value.items():
        locale = raw_locale.strip()
        if not is_supported_locale(locale):
            raise BrandingInvalid(f"unsupported branding locale '{raw_locale}'")
        if not isinstance(raw_text, str):
            raise BrandingInvalid("localized branding text must be a string")
        text = raw_text.strip()
        if not text:
            raise BrandingInvalid("localized branding text must not be empty")
        if len(text) > max_length:
            raise BrandingInvalid(
                f"localized text must not exceed {max_length} characters"
            )
        if locale in normalized:
            raise BrandingInvalid("locale keys must be unique after trimming")
        normalized[locale] = text
    return normalized


def _normalize_hex(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not HEX_COLOR_RE.fullmatch(normalized):
        raise BrandingInvalid(f"{field} must be a six-digit hex color")
    return normalized.lower()


def validate_patch(values: dict[str, object]) -> dict[str, object]:
    patched = dict(values)
    if "brand_names" in patched:
        patched["brand_names"] = _normalize_localized(
            patched["brand_names"],  # type: ignore[arg-type]
            max_length=BRAND_NAME_MAX_LENGTH,
        )
    if "taglines" in patched:
        patched["taglines"] = _normalize_localized(
            patched["taglines"],  # type: ignore[arg-type]
            max_length=TAGLINE_MAX_LENGTH,
        )
    color_present = "primary_color" in patched
    shades_present = "primary_shades" in patched
    if color_present != shades_present:
        raise BrandingInvalid(
            "primary_color and primary_shades must be sent together"
        )
    if color_present:
        color = patched["primary_color"]
        shades = patched["primary_shades"]
        if (color is None) != (shades is None):
            raise BrandingInvalid(
                "primary_color and primary_shades must both be set or both be null"
            )
        if color is not None:
            if not isinstance(color, str):
                raise BrandingInvalid("primary_color must be a six-digit hex color")
            patched["primary_color"] = _normalize_hex(color, field="primary_color")
            if not isinstance(shades, list) or len(shades) != 10:
                raise BrandingInvalid("primary_shades must contain exactly 10 colors")
            patched["primary_shades"] = [
                _normalize_hex(str(item), field="primary_shades") for item in shades
            ]
    if "show_logo" in patched and patched["show_logo"] is None:
        patched["show_logo"] = True
    if "show_brand_name_with_logo" in patched and patched["show_brand_name_with_logo"] is None:
        patched["show_brand_name_with_logo"] = True
    return patched


def update_branding(
    store: BrandingStore,
    values: dict[str, object],
    *,
    actor_user_id: str,
    actor_token_id: str | None,
) -> BrandingOut:
    patched = validate_patch(values)
    record = _store_write(lambda: store.patch(patched, actor_user_id=actor_user_id))
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="site_branding",
        resource_id="site",
        action="branding.update",
        result="success",
        detail={"fields": sorted(patched)},
    )
    reset_branding_cache()
    return present_branding(
        record,
        logo=read_asset(store, "logo"),
        favicon=read_asset(store, "favicon"),
    )


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1].lower()


def _is_allowed_data_image(value: str) -> bool:
    return bool(_RASTER_DATA_IMAGE_RE.match(value.strip()))


def _validate_svg_css(value: str) -> None:
    if _CSS_FORBIDDEN_RE.search(value):
        raise BrandingAssetUnsafe("SVG external CSS references are forbidden")
    for match in _CSS_URL_RE.finditer(value):
        target = match.group(2).strip()
        if not (target.startswith("#") or _is_allowed_data_image(target)):
            raise BrandingAssetUnsafe("SVG external CSS references are forbidden")


def _looks_like_xml(content: bytes) -> bool:
    stripped = content.lstrip(b"\xef\xbb\xbf \t\r\n")
    return stripped.startswith(b"<")


def _validate_svg(content: bytes) -> None:
    if _XML_STYLESHEET_RE.search(content):
        raise BrandingAssetUnsafe("SVG external stylesheets are forbidden")
    try:
        # Default ElementTree expands internal entities. This parser refuses
        # DTD and entity declarations, which is the SVG acceptance boundary.
        root = _safe_xml_fromstring(content)
    except DefusedXmlException as exc:
        raise BrandingAssetUnsafe(
            "SVG DTD and entity declarations are forbidden"
        ) from exc
    except (ET.ParseError, ValueError) as exc:
        raise BrandingAssetInvalid("SVG must be well-formed XML") from exc
    if root.tag != f"{{{_SVG_NAMESPACE}}}svg":
        raise BrandingAssetInvalid("SVG root must use the SVG namespace")
    for element in root.iter():
        element_name = _local_name(element.tag)
        if element_name in _FORBIDDEN_SVG_ELEMENTS:
            raise BrandingAssetUnsafe(f"SVG element <{element_name}> is forbidden")
        if element_name == "style":
            _validate_svg_css(element.text or "")
        for raw_name, raw_value in element.attrib.items():
            name = _local_name(raw_name)
            value = raw_value.strip()
            lowered = value.lower()
            if name.startswith("on"):
                raise BrandingAssetUnsafe("SVG event handler attributes are forbidden")
            if name in {"href", "src"} and not (
                value.startswith("#") or _is_allowed_data_image(value)
            ):
                raise BrandingAssetUnsafe("SVG external references are forbidden")
            if name == "style":
                _validate_svg_css(value)
            if "javascript:" in lowered:
                raise BrandingAssetUnsafe("SVG javascript references are forbidden")


def detect_asset_type(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x00\x00\x01\x00"):
        return "image/vnd.microsoft.icon"
    if _looks_like_xml(content):
        _validate_svg(content)
        return "image/svg+xml"
    raise BrandingAssetTypeUnsupported("unrecognized branding asset type")


def validate_asset(kind: BrandingAssetKind, content: bytes) -> str:
    if len(content) > MAX_ASSET_BYTES:
        raise BrandingAssetTooLarge(
            f"branding assets must not exceed {MAX_ASSET_BYTES} bytes"
        )
    if not content:
        raise BrandingRequestInvalid("branding assets must not be empty")
    content_type = detect_asset_type(content)
    accepted = {
        "logo": {"image/png", "image/jpeg", "image/svg+xml"},
        "favicon": {"image/png", "image/vnd.microsoft.icon"},
    }
    if content_type not in accepted[kind]:
        raise BrandingAssetTypeUnsupported(
            f"{content_type} is not accepted for branding asset kind {kind}"
        )
    return content_type


def replace_asset(
    store: BrandingStore,
    *,
    kind: BrandingAssetKind,
    content: bytes,
    actor_user_id: str,
    actor_token_id: str | None,
) -> BrandingAssetRecord:
    content_type = validate_asset(kind, content)
    checksum = hashlib.sha256(content).hexdigest()
    asset = _store_write(
        lambda: store.replace_asset(
            kind=kind,
            content_type=content_type,
            content=content,
            checksum=checksum,
        )
    )
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="site_branding",
        resource_id="site",
        action="branding.asset.replace",
        result="success",
        detail={
            "kind": kind,
            "byte_size": asset.byte_size,
            "checksum": asset.checksum,
            "content_type": asset.content_type,
            "origin": asset.origin,
        },
    )
    reset_branding_cache()
    return asset


def delete_asset(
    store: BrandingStore,
    *,
    kind: BrandingAssetKind,
    actor_user_id: str,
    actor_token_id: str | None,
) -> BrandingAssetRecord | None:
    asset = _store_write(lambda: store.delete_asset(kind))
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="site_branding",
        resource_id="site",
        action="branding.asset.delete",
        result="success",
        detail={
            "kind": kind,
            "byte_size": asset.byte_size if asset else None,
            "checksum": asset.checksum if asset else None,
            "content_type": asset.content_type if asset else None,
            "origin": asset.origin if asset else None,
        },
    )
    reset_branding_cache()
    return asset


def reset_branding(
    store: BrandingStore,
    *,
    actor_user_id: str,
    actor_token_id: str | None,
) -> None:
    _store_write(store.reset)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="site_branding",
        resource_id="site",
        action="branding.reset",
        result="success",
    )
    reset_branding_cache()
