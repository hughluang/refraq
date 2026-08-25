"""Persistence ports and adapters for site branding."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import lru_cache
from typing import Literal, Protocol

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.admin.branding.models import SiteBrandingAssetRow, SiteBrandingRow
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now

BrandingAssetKind = Literal["logo", "favicon"]
BrandingAssetOrigin = Literal["seed", "user"]
SITE_BRANDING_ID = "site"


@dataclass(frozen=True, slots=True)
class BrandingAssetRecord:
    id: str
    kind: BrandingAssetKind
    content_type: str
    byte_size: int
    bytes: bytes
    checksum: str
    origin: BrandingAssetOrigin
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BrandingRecord:
    brand_names: dict[str, str] | None = None
    taglines: dict[str, str] | None = None
    primary_color: str | None = None
    primary_shades: list[str] | None = None
    show_logo: bool = True
    show_brand_name_with_logo: bool = True
    updated_at: datetime = field(default_factory=utc_now)
    updated_by_user_id: str | None = None


class BrandingStore(Protocol):
    def get(self) -> BrandingRecord | None: ...

    def patch(
        self, values: dict[str, object], *, actor_user_id: str
    ) -> BrandingRecord: ...

    def get_asset(self, kind: BrandingAssetKind) -> BrandingAssetRecord | None: ...

    def replace_asset(
        self,
        *,
        kind: BrandingAssetKind,
        content_type: str,
        content: bytes,
        checksum: str,
    ) -> BrandingAssetRecord: ...

    def delete_asset(self, kind: BrandingAssetKind) -> BrandingAssetRecord | None: ...

    def reset(self) -> None: ...


def _patched(
    current: BrandingRecord | None,
    values: dict[str, object],
    *,
    actor_user_id: str,
) -> BrandingRecord:
    base = current or BrandingRecord()
    allowed = {
        "brand_names",
        "taglines",
        "primary_color",
        "primary_shades",
        "show_logo",
        "show_brand_name_with_logo",
    }
    changes = {key: value for key, value in values.items() if key in allowed}
    return replace(
        base,
        **changes,
        updated_at=utc_now(),
        updated_by_user_id=actor_user_id,
    )


class MemoryBrandingStore:
    def __init__(self) -> None:
        self._branding: BrandingRecord | None = None
        self._assets: dict[BrandingAssetKind, BrandingAssetRecord] = {}
        self._lock = threading.RLock()

    def get(self) -> BrandingRecord | None:
        with self._lock:
            return self._branding

    def patch(
        self, values: dict[str, object], *, actor_user_id: str
    ) -> BrandingRecord:
        with self._lock:
            self._branding = _patched(
                self._branding, values, actor_user_id=actor_user_id
            )
            return self._branding

    def get_asset(self, kind: BrandingAssetKind) -> BrandingAssetRecord | None:
        with self._lock:
            return self._assets.get(kind)

    def replace_asset(
        self,
        *,
        kind: BrandingAssetKind,
        content_type: str,
        content: bytes,
        checksum: str,
    ) -> BrandingAssetRecord:
        with self._lock:
            previous = self._assets.get(kind)
            asset = BrandingAssetRecord(
                id=(
                    previous.id
                    if previous is not None
                    else f"brand_asset_{uuid.uuid4().hex[:12]}"
                ),
                kind=kind,
                content_type=content_type,
                byte_size=len(content),
                bytes=content,
                checksum=checksum,
                origin="user",
                created_at=utc_now(),
            )
            self._assets[kind] = asset
            return asset

    def delete_asset(self, kind: BrandingAssetKind) -> BrandingAssetRecord | None:
        with self._lock:
            return self._assets.pop(kind, None)

    def reset(self) -> None:
        with self._lock:
            self._branding = None
            self._assets.clear()


class SqlBrandingStore:
    def get(self) -> BrandingRecord | None:
        with session_scope() as session:
            row = session.get(SiteBrandingRow, SITE_BRANDING_ID)
            return _row_to_branding(row) if row is not None else None

    def patch(
        self, values: dict[str, object], *, actor_user_id: str
    ) -> BrandingRecord:
        with session_scope() as session:
            row = self._ensure_branding(session)
            for key, value in values.items():
                if key in {
                    "brand_names",
                    "taglines",
                    "primary_color",
                    "primary_shades",
                    "show_logo",
                    "show_brand_name_with_logo",
                }:
                    setattr(row, key, value)
            row.updated_at = utc_now()
            row.updated_by_user_id = actor_user_id
            session.flush()
            return _row_to_branding(row)

    def get_asset(self, kind: BrandingAssetKind) -> BrandingAssetRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(SiteBrandingAssetRow).where(
                    SiteBrandingAssetRow.kind == kind
                )
            )
            return _row_to_asset(row) if row is not None else None

    def replace_asset(
        self,
        *,
        kind: BrandingAssetKind,
        content_type: str,
        content: bytes,
        checksum: str,
    ) -> BrandingAssetRecord:
        with session_scope() as session:
            row = session.scalar(
                select(SiteBrandingAssetRow)
                .where(SiteBrandingAssetRow.kind == kind)
                .with_for_update()
            )
            if row is None:
                row = SiteBrandingAssetRow(
                    id=f"brand_asset_{uuid.uuid4().hex[:12]}",
                    kind=kind,
                    content_type=content_type,
                    byte_size=len(content),
                    bytes=content,
                    checksum=checksum,
                    created_at=utc_now(),
                )
                session.add(row)
            else:
                row.content_type = content_type
                row.byte_size = len(content)
                row.bytes = content
                row.checksum = checksum
                row.created_at = utc_now()
            session.flush()
            return _row_to_asset(row)

    def delete_asset(self, kind: BrandingAssetKind) -> BrandingAssetRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(SiteBrandingAssetRow)
                .where(SiteBrandingAssetRow.kind == kind)
                .with_for_update()
            )
            if row is None:
                return None
            asset = _row_to_asset(row)
            session.delete(row)
            session.flush()
            return asset

    def reset(self) -> None:
        with session_scope() as session:
            row = session.get(SiteBrandingRow, SITE_BRANDING_ID)
            if row is not None:
                session.delete(row)
                session.flush()
            session.execute(delete(SiteBrandingAssetRow))

    @staticmethod
    def _ensure_branding(session: Session) -> SiteBrandingRow:
        row = session.get(SiteBrandingRow, SITE_BRANDING_ID)
        if row is None:
            row = SiteBrandingRow(
                id=SITE_BRANDING_ID,
                brand_names=None,
                taglines=None,
                primary_color=None,
                primary_shades=None,
                show_logo=True,
                show_brand_name_with_logo=True,
                updated_at=utc_now(),
                updated_by_user_id=None,
            )
            session.add(row)
            session.flush()
        return row


def _row_to_branding(row: SiteBrandingRow) -> BrandingRecord:
    return BrandingRecord(
        brand_names=dict(row.brand_names) if row.brand_names is not None else None,
        taglines=dict(row.taglines) if row.taglines is not None else None,
        primary_color=row.primary_color,
        primary_shades=list(row.primary_shades) if row.primary_shades is not None else None,
        show_logo=row.show_logo,
        show_brand_name_with_logo=row.show_brand_name_with_logo,
        updated_at=row.updated_at,
        updated_by_user_id=row.updated_by_user_id,
    )


def _row_to_asset(row: SiteBrandingAssetRow) -> BrandingAssetRecord:
    return BrandingAssetRecord(
        id=row.id,
        kind=row.kind,  # type: ignore[arg-type]
        content_type=row.content_type,
        byte_size=row.byte_size,
        bytes=row.bytes,
        checksum=row.checksum,
        origin="user",
        created_at=row.created_at,
    )


_memory_singleton: MemoryBrandingStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_branding_store() -> BrandingStore:
    if get_settings().store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryBrandingStore()
            return _memory_singleton
    return SqlBrandingStore()


def reset_branding_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_branding_store.cache_clear()
