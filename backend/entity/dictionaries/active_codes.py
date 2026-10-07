"""Dictionary code adapter bound into ``backend.admin.subjects`` by composition."""

from __future__ import annotations

from backend.entity.dictionaries.store import get_dictionary_store

__all__ = ["DictionaryActiveCodes"]


class DictionaryActiveCodes:
    def active_codes(self, dictionary_id: str) -> frozenset[str] | None:
        found = get_dictionary_store().get(dictionary_id)
        if found is None:
            return None
        return frozenset(entry.code for entry in found.entries if entry.active)
