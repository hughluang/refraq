"""Physical Entity Table names and live-table occupancy."""

from __future__ import annotations

from backend.entity.records import EntityVersionRecord

__all__ = [
    "compose_physical_table_name",
    "occupies_live_table",
    "physical_table_name",
    "table_present",
]

_IDENT_MAX = 63


def table_present(version: EntityVersionRecord) -> bool:
    return bool(version.materialized_attributes)


def compose_physical_table_name(
    stem: str, version: int, version_id: str
) -> tuple[str, str | None]:
    """Physical relation name, and the full stem when that stem was shortened.

    The suffix ``__v{version}__{version_id}`` is kept whole. A stem that would
    push the identifier past 63 characters is shortened from the right.
    """
    suffix = f"__v{version}__{version_id}"
    if len(stem) + len(suffix) <= _IDENT_MAX:
        return f"{stem}{suffix}", None
    head = stem[: _IDENT_MAX - len(suffix)]
    return f"{head}{suffix}", stem


def physical_table_name(version: EntityVersionRecord, stem: str) -> str | None:
    """Physical table holding this version's rows. The entity stem is a view."""
    if not table_present(version):
        return None
    name, _comment = compose_physical_table_name(stem, version.version, version.id)
    return name


def occupies_live_table(
    version: EntityVersionRecord,
    latest_published: EntityVersionRecord | None,
) -> bool:
    return (
        table_present(version)
        and latest_published is not None
        and version.id == latest_published.id
    )
