"""One write-target compatibility rule for a match key, a mapping, and a head."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Mapping, Sequence

if TYPE_CHECKING:
    from backend.channel.nodes.spec import ResolvedAttribute, ResolvedEntity

ReasonCode = Literal[
    "business_key_missing",
    "attribute_missing",
    "match_key_not_unique",
]

__all__ = ["WriteReason", "write_reasons"]


@dataclass(frozen=True, slots=True)
class WriteReason:
    code: ReasonCode
    subject: str


def write_reasons(
    match_key: str | None,
    mapping: Sequence[Mapping[str, Any]],
    head: ResolvedEntity,
) -> list[WriteReason]:
    by_name = {attr.name: attr for attr in head.attributes}
    pending: list[WriteReason] = []
    if match_key is None:
        marked = next((attr for attr in head.attributes if attr.business_key), None)
        if marked is None:
            pending.append(WriteReason("business_key_missing", "match_key"))
        else:
            pending.extend(_effective_match_key(marked.name, by_name))
    elif match_key == "row_id":
        pending.append(WriteReason("attribute_missing", "match_key"))
    else:
        pending.extend(_effective_match_key(match_key, by_name))
    for item in mapping:
        if not isinstance(item, Mapping):
            continue
        name = item.get("attribute")
        if isinstance(name, str) and name not in by_name:
            pending.append(WriteReason("attribute_missing", name))
    return _dedupe(pending)


def _effective_match_key(
    name: str,
    by_name: Mapping[str, ResolvedAttribute],
) -> list[WriteReason]:
    attr = by_name.get(name)
    if attr is None:
        return [WriteReason("attribute_missing", "match_key")]
    if not attr.unique:
        return [WriteReason("match_key_not_unique", "match_key")]
    return []


def _dedupe(reasons: list[WriteReason]) -> list[WriteReason]:
    seen: set[tuple[str, str]] = set()
    ordered: list[WriteReason] = []
    for reason in reasons:
        key = (reason.code, reason.subject)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(reason)
    return ordered
