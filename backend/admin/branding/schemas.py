"""HTTP shapes for site branding."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

BRAND_NAME_MAX_LENGTH = 80
TAGLINE_MAX_LENGTH = 160


class BrandingOut(BaseModel):
    brand_names: dict[str, str]
    taglines: dict[str, str]
    primary_color: str | None
    primary_shades: list[str] | None
    show_logo: bool
    show_brand_name_with_logo: bool
    logo_url: str | None
    favicon_url: str | None
    logo_source: Literal["seed", "user"] | None
    favicon_source: Literal["seed", "user"] | None


class BrandingPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_names: dict[str, str] | None = None
    taglines: dict[str, str] | None = None
    primary_color: str | None = None
    primary_shades: list[str] | None = None
    show_logo: bool | None = None
    show_brand_name_with_logo: bool | None = None

    def present_values(self) -> dict[str, Any]:
        return self.model_dump(include=self.model_fields_set)


class BrandingAssetOut(BaseModel):
    kind: Literal["logo", "favicon"]
    content_type: str
    byte_size: int
    checksum: str
    url: str


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
