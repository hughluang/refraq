"""Resolve dictionary attributes against Dictionaries for save and publish."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from backend.entity.dictionaries.store import get_dictionary_store
from backend.entity.errors import DictionaryDeprecated, EntityAttributeInvalid
from backend.entity.lifecycle import latest_published_of
from backend.entity.records import AttributeRecord, EntityVersionRecord

__all__ = [
    "bind_publish",
    "freeze_publish_bindings",
    "frozen_bindings_cover",
    "relevant_snapshot",
    "require_attribute_dictionaries",
]


def require_attribute_dictionaries(
    attributes: list[AttributeRecord],
    *,
    previous: list[AttributeRecord],
) -> None:
    previous_by_name = {attr.name: attr for attr in previous}
    store = get_dictionary_store()
    for attr in attributes:
        if attr.type != "dictionary":
            continue
        dictionary_id = attr.dictionary_id or ""
        found = store.get(dictionary_id)
        if found is None:
            raise EntityAttributeInvalid(
                f"Attribute '{attr.name}' dictionary_id '{dictionary_id}'"
                " does not name a dictionary"
            )
        prior = previous_by_name.get(attr.name)
        kept = (
            prior is not None
            and prior.type == "dictionary"
            and prior.dictionary_id == attr.dictionary_id
        )
        if found.deprecated_at is not None and not kept:
            raise DictionaryDeprecated(
                f"Dictionary '{found.name}' is deprecated"
            )


def freeze_publish_bindings(attributes: list[AttributeRecord]) -> dict[str, Any]:
    """Active codes and deprecation captured once at publish acceptance."""
    store = get_dictionary_store()
    bindings: dict[str, Any] = {}
    for attr in attributes:
        if attr.type != "dictionary":
            continue
        dictionary_id = attr.dictionary_id or ""
        found = store.get(dictionary_id)
        if found is None:
            raise EntityAttributeInvalid(
                f"Attribute '{attr.name}' dictionary_id '{dictionary_id}'"
                " does not name a dictionary"
            )
        codes = [entry.code for entry in found.entries if entry.active]
        if not codes:
            raise EntityAttributeInvalid(
                f"Attribute '{attr.name}' dictionary has no active codes"
            )
        bindings[attr.name] = {
            "dictionary_id": dictionary_id,
            "codes": codes,
            "deprecated": found.deprecated_at is not None,
        }
    return bindings


def frozen_bindings_cover(
    attributes: list[AttributeRecord],
    raw: object,
) -> dict[str, Any] | None:
    """Return the frozen document when it names every dictionary attribute."""
    if not isinstance(raw, dict):
        return None
    for attr in attributes:
        if attr.type != "dictionary":
            continue
        if not _binding_entry(raw.get(attr.name), attr.dictionary_id):
            return None
    return raw


def bind_publish(
    attributes: list[AttributeRecord],
    bindings: dict[str, Any],
) -> tuple[list[AttributeRecord], dict[str, Any]]:
    """Attribute copies and snapshots whose codes come from the frozen document."""
    bound: list[AttributeRecord] = []
    snapshots: dict[str, Any] = {}
    mismatches: list[str] = []
    for attr in attributes:
        if attr.type != "dictionary":
            bound.append(attr)
            continue
        frozen = bindings[attr.name]
        live_codes, live_deprecated, revision = _live_dictionary(
            attr.dictionary_id or "",
            attribute_name=attr.name,
        )
        if not _matches(frozen, live_codes, live_deprecated):
            mismatches.append(
                _mismatch_text(attr.name, frozen, live_codes, live_deprecated)
            )
            continue
        codes = tuple(str(code) for code in frozen["codes"])
        bound.append(replace(attr, codes=codes))
        snapshots[attr.name] = {
            "dictionary_id": frozen["dictionary_id"],
            "revision": revision,
            "codes": list(codes),
        }
    if mismatches:
        raise EntityAttributeInvalid(
            "Dictionary changed after publish was accepted: " + "; ".join(mismatches)
        )
    return bound, snapshots


def relevant_snapshot(
    versions: list[EntityVersionRecord],
    version: EntityVersionRecord,
    attribute_name: str,
    dictionary_id: str,
) -> dict[str, Any] | None:
    """Snapshot that decides whether this attribute read is behind."""
    own = version.dictionary_snapshots.get(attribute_name)
    if isinstance(own, dict) and own.get("dictionary_id") == dictionary_id:
        return own
    published = latest_published_of(versions)
    if published is None:
        return None
    snapshot = published.dictionary_snapshots.get(attribute_name)
    if isinstance(snapshot, dict) and snapshot.get("dictionary_id") == dictionary_id:
        return snapshot
    return None


def _binding_entry(entry: object, dictionary_id: str | None) -> bool:
    if not isinstance(entry, dict):
        return False
    codes = entry.get("codes")
    return (
        entry.get("dictionary_id") == dictionary_id
        and isinstance(codes, list)
        and bool(codes)
        and all(isinstance(code, str) and code for code in codes)
        and isinstance(entry.get("deprecated"), bool)
    )


def _live_dictionary(
    dictionary_id: str, *, attribute_name: str
) -> tuple[tuple[str, ...], bool, int]:
    found = get_dictionary_store().get(dictionary_id)
    if found is None:
        raise EntityAttributeInvalid(
            f"Attribute '{attribute_name}' dictionary_id '{dictionary_id}'"
            " does not name a dictionary"
        )
    codes = tuple(entry.code for entry in found.entries if entry.active)
    return codes, found.deprecated_at is not None, found.revision


def _matches(
    frozen: dict[str, Any],
    live_codes: tuple[str, ...],
    live_deprecated: bool,
) -> bool:
    return set(live_codes) == set(frozen["codes"]) and not (
        live_deprecated and not frozen["deprecated"]
    )


def _mismatch_text(
    name: str,
    frozen: dict[str, Any],
    live_codes: tuple[str, ...],
    live_deprecated: bool,
) -> str:
    accepted = ", ".join(str(code) for code in frozen["codes"])
    current = ", ".join(live_codes)
    text = f"{name} accepted=[{accepted}] now=[{current}]"
    if live_deprecated and not frozen["deprecated"]:
        text += " deprecated"
    return text
