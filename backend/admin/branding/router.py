"""HTTP adapters for site branding."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import UploadFile

from backend.admin.branding.errors import (
    BrandingAssetNotFound,
    BrandingAssetTooLarge,
    BrandingRequestInvalid,
)
from backend.admin.branding.schemas import (
    BrandingAssetOut,
    BrandingOut,
    BrandingPatchRequest,
    EmptyBody,
)
from backend.admin.branding.service import (
    ASSET_CACHE_CONTROL,
    MAX_ASSET_BYTES,
    PUBLIC_CACHE_CONTROL,
    delete_asset,
    present_asset,
    read_asset,
    read_public_branding,
    replace_asset,
    reset_branding,
    update_branding,
)
from backend.admin.branding.store import (
    BrandingAssetKind,
    BrandingStore,
    get_branding_store,
)
from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord

router = APIRouter(prefix="/branding", tags=["branding"])


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    return any(
        token.strip() in {"*", etag} for token in if_none_match.split(",")
    )


def _public_json(store: BrandingStore) -> JSONResponse:
    cached = read_public_branding(store)
    return JSONResponse(
        content=cached.body,
        headers={"Cache-Control": PUBLIC_CACHE_CONTROL, "ETag": cached.etag},
    )


@router.get("")
def get_branding(
    if_none_match: Annotated[str | None, Header()] = None,
    store: BrandingStore = Depends(get_branding_store),
) -> Response:
    cached = read_public_branding(store)
    headers = {"Cache-Control": PUBLIC_CACHE_CONTROL, "ETag": cached.etag}
    if _etag_matches(if_none_match, cached.etag):
        return Response(status_code=304, headers=headers)
    return JSONResponse(content=cached.body, headers=headers)


@router.put("", response_model=BrandingOut)
def put_branding(
    payload: BrandingPatchRequest,
    user: UserRecord = Depends(require_permission("branding:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
    store: BrandingStore = Depends(get_branding_store),
) -> JSONResponse:
    update_branding(
        store,
        payload.present_values(),
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return _public_json(store)


@router.get("/assets/{kind}")
def get_branding_asset(
    kind: BrandingAssetKind,
    if_none_match: Annotated[str | None, Header()] = None,
    store: BrandingStore = Depends(get_branding_store),
) -> Response:
    asset = read_asset(store, kind)
    if asset is None:
        raise BrandingAssetNotFound(f"branding asset {kind} is not configured")
    etag = f'"{asset.checksum}"'
    headers = {
        "Cache-Control": ASSET_CACHE_CONTROL,
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    if asset.content_type == "image/svg+xml":
        headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'none'; object-src 'none'; "
            "base-uri 'none'"
        )
    if _etag_matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return Response(content=asset.bytes, media_type=asset.content_type, headers=headers)


def _single_upload_file(form_names: list[str], files: list[object]) -> UploadFile:
    extra = [name for name in form_names if name != "file"]
    if extra or len(files) != 1 or not isinstance(files[0], UploadFile):
        raise BrandingRequestInvalid(
            "branding asset upload must contain exactly one file part named file"
        )
    return files[0]


@router.post("/assets/{kind}", response_model=BrandingAssetOut, status_code=201)
async def post_branding_asset(
    kind: BrandingAssetKind,
    request: Request,
    user: UserRecord = Depends(require_permission("branding:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
    store: BrandingStore = Depends(get_branding_store),
) -> BrandingAssetOut:
    form = await request.form()
    file = _single_upload_file(list(form.keys()), form.getlist("file"))
    try:
        content = await file.read(MAX_ASSET_BYTES + 1)
    finally:
        await file.close()
    if not content:
        raise BrandingRequestInvalid("branding assets must not be empty")
    if len(content) > MAX_ASSET_BYTES:
        raise BrandingAssetTooLarge(
            f"branding assets must not exceed {MAX_ASSET_BYTES} bytes"
        )
    asset = replace_asset(
        store,
        kind=kind,
        content=content,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return present_asset(kind, asset)


@router.delete("/assets/{kind}", status_code=204)
def remove_branding_asset(
    kind: BrandingAssetKind,
    user: UserRecord = Depends(require_permission("branding:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
    store: BrandingStore = Depends(get_branding_store),
) -> Response:
    delete_asset(
        store,
        kind=kind,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return Response(status_code=204)


@router.post("/reset", status_code=204)
def reset_site_branding(
    user: UserRecord = Depends(require_permission("branding:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
    store: BrandingStore = Depends(get_branding_store),
    payload: EmptyBody | None = None,
) -> Response:
    del payload
    reset_branding(
        store,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return Response(status_code=204)
