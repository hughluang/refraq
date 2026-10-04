"""Canonical IANA zone ids shared by Display Timezone and Schedule Timezone.

The set is the zones named in tzdata ``zone1970.tab`` plus ``UTC``. Link names
from ``tzdata.zi`` are aliases of that set, not separate choices.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

__all__ = ["canonical_zone_id", "iana_zone_ids", "zone_aliases"]


def iana_zone_ids() -> tuple[str, ...]:
    """Sorted current zone ids. Does not include historical link names."""
    return _catalog()[0]


def zone_aliases() -> dict[str, tuple[str, ...]]:
    """Current zone id to the historical link names that resolve to it."""
    return _catalog()[2]


def canonical_zone_id(name: str) -> str | None:
    """Map a current id or historical link to the stored id. Unknown → None."""
    trimmed = name.strip()
    if not trimmed:
        return None
    return _catalog()[1].get(trimmed)


@lru_cache(maxsize=1)
def _catalog() -> tuple[
    tuple[str, ...],
    dict[str, str],
    dict[str, tuple[str, ...]],
]:
    zone_ids = set(_zone1970_ids())
    zone_ids.add("UTC")
    link_of, links_from = _links()

    def canonical(name: str) -> str | None:
        seen: set[str] = set()
        current = name
        while current not in zone_ids and current not in seen:
            seen.add(current)
            nxt = link_of.get(current)
            if nxt is None:
                for alias in links_from.get(current, ()):
                    if alias in zone_ids:
                        return alias
                return None
            current = nxt
        if current in zone_ids:
            return current
        return None

    alias_lists: dict[str, list[str]] = {zone_id: [] for zone_id in zone_ids}
    for name in set(link_of) | set(links_from):
        if name in zone_ids:
            continue
        canon = canonical(name)
        if canon is None:
            continue
        alias_lists[canon].append(name)

    lookup = {zone_id: zone_id for zone_id in zone_ids}
    aliases: dict[str, tuple[str, ...]] = {}
    for zone_id, names in alias_lists.items():
        unique = tuple(sorted(set(names)))
        aliases[zone_id] = unique
        for alias in unique:
            lookup[alias] = zone_id
    return tuple(sorted(zone_ids)), lookup, aliases


def _zone1970_ids() -> tuple[str, ...]:
    text = files("tzdata.zoneinfo").joinpath("zone1970.tab").read_text(encoding="utf-8")
    ids: list[str] = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2]:
            ids.append(parts[2])
    return tuple(ids)


def _links() -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    text = files("tzdata.zoneinfo").joinpath("tzdata.zi").read_text(encoding="utf-8")
    link_of: dict[str, str] = {}
    links_from: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.startswith("L "):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        target, linkname = parts[1], parts[2]
        link_of[linkname] = target
        links_from.setdefault(target, []).append(linkname)
    return link_of, {key: tuple(names) for key, names in links_from.items()}
