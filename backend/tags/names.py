"""Display-name and description rules for a Tag.

Uniqueness and the stored spelling come from the precis-i18n nickname profiles
as shipped. Callers do not pass a case mapping.
"""

from __future__ import annotations

import unicodedata

from precis_i18n import get_profile

from backend.tags.errors import TagDescriptionInvalid, TagNameInvalid

_PRESERVED = get_profile("NicknameCasePreserved")
_MAPPED = get_profile("NicknameCaseMapped")

_RAW_MAX = 256
_NAME_MAX = 64
_DESCRIPTION_MAX = 200


def enforce_tag_name(value: str) -> tuple[str, str]:
    """Return ``(display name, comparison form)`` or raise ``TagNameInvalid``."""

    if len(value) > _RAW_MAX:
        raise TagNameInvalid()
    try:
        display = _PRESERVED.enforce(value)
        comparison = _MAPPED.enforce(value)
    except UnicodeError as exc:
        raise TagNameInvalid() from exc
    # NicknameCasePreserved rejects an empty result itself (UnicodeEncodeError).
    # A display name it returns is therefore non-empty; only the length cap remains.
    if len(display) > _NAME_MAX:
        raise TagNameInvalid()
    return display, comparison


def enforce_tag_description(value: str | None) -> str | None:
    """Trim a description. Empty means absent. Raise ``TagDescriptionInvalid``."""

    if value is None:
        return None
    if len(value) > _RAW_MAX:
        raise TagDescriptionInvalid()
    trimmed = value.strip()
    if trimmed == "":
        return None
    if len(trimmed) > _DESCRIPTION_MAX or _has_control(trimmed):
        raise TagDescriptionInvalid()
    return trimmed


def _has_control(value: str) -> bool:
    return any(unicodedata.category(char) == "Cc" for char in value)
