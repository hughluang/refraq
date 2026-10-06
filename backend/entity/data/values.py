"""Inbound and outbound value encoding for Entity Data API."""

from __future__ import annotations

from typing import Any

from dataclasses import replace

from backend.entity.attribute_type import resolve
from backend.entity.data.head import HeadTarget
from backend.entity.dictionaries.store import get_dictionary_store
from backend.entity.errors import EntityRowInvalid
from backend.entity.records import AttributeRecord

__all__ = [
    "decode_row",
    "encode_inbound",
    "encode_inbound_map",
    "reference_value_attr",
    "require_business_key_value",
    "writable_dictionary_codes",
]

def encode_inbound_map(
    values: dict[str, Any],
    target: HeadTarget,
    *,
    partial: bool,
) -> dict[str, Any]:
    if "row_id" in values:
        raise EntityRowInvalid("row_id is not an authorable attribute")
    by_name = {attr.name: attr for attr in target.attributes}
    unknown = [key for key in values if key not in by_name]
    if unknown:
        raise EntityRowInvalid(
            f"Unknown attribute(s): {', '.join(sorted(unknown))}"
        )
    if not values:
        raise EntityRowInvalid("values must not be empty")
    encoded: dict[str, Any] = {}
    for name, raw in values.items():
        require_business_key_value(by_name[name], raw)
        encoded[name] = encode_inbound(by_name[name], raw, target)
    if not partial:
        for attr in target.attributes:
            if attr.required and attr.name not in encoded:
                raise EntityRowInvalid(
                    f"Attribute '{attr.name}' is required"
                )
            if attr.required and encoded.get(attr.name) is None:
                raise EntityRowInvalid(
                    f"Attribute '{attr.name}' is required"
                )
    return encoded


def require_business_key_value(attr: AttributeRecord, raw: Any) -> None:
    """A string Business Key must not be empty or whitespace."""
    if (
        attr.business_key
        and attr.type == "string"
        and isinstance(raw, str)
        and not raw.strip()
    ):
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' business key must not be blank"
        )


def encode_inbound(
    attr: AttributeRecord, raw: Any, target: HeadTarget
) -> Any:
    if raw is None:
        return None
    if isinstance(raw, str) and "\x00" in raw:
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' must not contain NUL"
        )
    if attr.type == "reference":
        return _encode_reference(attr, raw, target)
    spec = resolve(attr.type)
    codes = (
        writable_dictionary_codes(attr, target)
        if "dictionary" in spec.reads
        else None
    )
    return spec.encode(attr, raw, codes=codes)


def decode_row(
    columns: list[str],
    values: tuple[Any, ...],
    target: HeadTarget,
) -> dict[str, Any]:
    by_name = {attr.name: attr for attr in target.attributes}
    out: dict[str, Any] = {}
    for col, value in zip(columns, values, strict=True):
        if col == "row_id":
            out["row_id"] = int(value) if value is not None else None
            continue
        attr = by_name[col]
        out[col] = _decode_value(attr, value, target)
    return out


def writable_dictionary_codes(
    attr: AttributeRecord, target: HeadTarget
) -> frozenset[str]:
    snapshot = target.head.dictionary_snapshots.get(attr.name)
    if not isinstance(snapshot, dict):
        return frozenset()
    snap = {str(code) for code in (snapshot.get("codes") or [])}
    found = get_dictionary_store().get(attr.dictionary_id or "")
    if found is None:
        return frozenset()
    active = {entry.code for entry in found.entries if entry.active}
    return frozenset(snap & active)


def _encode_reference(attr: AttributeRecord, raw: Any, target: HeadTarget) -> Any:
    proxy = reference_value_attr(attr, target)
    return resolve(proxy.type).encode(proxy, raw)


def _decode_value(attr: AttributeRecord, value: Any, target: HeadTarget) -> Any:
    if value is None:
        return None
    if attr.type == "reference":
        proxy = reference_value_attr(attr, target)
        return resolve(proxy.type).decode(proxy, value)
    return resolve(attr.type).decode(attr, value)


def reference_value_attr(attr: AttributeRecord, target: HeadTarget) -> AttributeRecord:
    snap = target.head.reference_snapshots[attr.name]
    if snap["type"] == "string":
        return replace(attr, type="string", max_length=snap["max_length"])
    return replace(attr, type="integer")
