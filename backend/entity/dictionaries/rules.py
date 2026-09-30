"""Lexical rules and entry replacement for Dictionarys."""

from __future__ import annotations

from backend.entity.dictionaries.records import DictionaryEntryRecord
from backend.entity.errors import DictionaryInvalid
from backend.entity.validate import IDENT_RE

NAME_MAX_LEN = 63
DISPLAY_NAME_MAX_LEN = 256
CODE_MAX_LEN = 64
LABEL_MAX_LEN = 200

__all__ = [
    "CODE_MAX_LEN",
    "DISPLAY_NAME_MAX_LEN",
    "LABEL_MAX_LEN",
    "NAME_MAX_LEN",
    "active_codes",
    "clean_description",
    "normalize_entries",
    "require_dictionary_name",
    "require_display_name",
]


def require_dictionary_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > NAME_MAX_LEN or not IDENT_RE.match(cleaned):
        raise DictionaryInvalid(
            "Dictionary name must start with a letter and use only a-z, 0-9,"
            f" and underscore, at most {NAME_MAX_LEN} characters"
        )
    return cleaned


def require_display_name(display_name: str) -> str:
    cleaned = (display_name or "").strip()
    if not cleaned or len(cleaned) > DISPLAY_NAME_MAX_LEN:
        raise DictionaryInvalid(
            f"Dictionary display_name is required and at most {DISPLAY_NAME_MAX_LEN} characters"
        )
    return cleaned


def clean_description(description: str | None) -> str | None:
    if description is None:
        return None
    if not isinstance(description, str):
        raise DictionaryInvalid("Dictionary description must be a string")
    cleaned = description.strip()
    return cleaned or None


def active_codes(entries: tuple[DictionaryEntryRecord, ...]) -> frozenset[str]:
    return frozenset(entry.code for entry in entries if entry.active)


def normalize_entries(
    raw: list[dict[str, object]],
    *,
    snapshotted: frozenset[str],
    previous: tuple[DictionaryEntryRecord, ...] = (),
) -> tuple[DictionaryEntryRecord, ...]:
    if len(raw) == 0:
        raise DictionaryInvalid("Dictionary entries must be a non-empty list")
    previous_codes = {entry.code for entry in previous}
    seen: set[str] = set()
    cleaned: list[DictionaryEntryRecord] = []
    for index, item in enumerate(raw):
        code = _require_code(item.get("code"))
        if code in seen:
            raise DictionaryInvalid(f"Dictionary code '{code}' is duplicated")
        seen.add(code)
        label = _require_label(item.get("label"))
        active = _require_active(item.get("active", True))
        cleaned.append(
            DictionaryEntryRecord(code=code, label=label, active=active, position=index)
        )
    removed = previous_codes - seen
    blocked = sorted(removed & snapshotted)
    if blocked:
        raise DictionaryInvalid(
            f"Code '{blocked[0]}' is in a publish snapshot and cannot be removed"
        )
    return tuple(cleaned)


def _require_code(value: object) -> str:
    if not isinstance(value, str):
        raise DictionaryInvalid("Dictionary code must be a string")
    code = value.strip()
    if not code or len(code) > CODE_MAX_LEN:
        raise DictionaryInvalid(
            "Dictionary code must be non-empty and"
            f" at most {CODE_MAX_LEN} characters"
        )
    return code


def _require_label(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DictionaryInvalid("Dictionary label must be a string")
    label = value.strip()
    if not label:
        return None
    if len(label) > LABEL_MAX_LEN:
        raise DictionaryInvalid(
            f"Dictionary label must be at most {LABEL_MAX_LEN} characters"
        )
    return label


def _require_active(value: object) -> bool:
    if not isinstance(value, bool):
        raise DictionaryInvalid("Dictionary active must be a boolean")
    return value
