"""Readable locator keys for Sources, Catalog Objects, and columns (ADR 0012)."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote

from backend.metadata.errors import LocatorInvalid

__all__ = [
    "ColumnLocator",
    "ObjectLocator",
    "SourceLocator",
    "format_column_locator",
    "format_object_locator",
    "format_source_locator",
    "parse_column_locator",
    "parse_object_locator",
    "parse_source_locator",
    "source_locator_segment",
]


def _enc(segment: str) -> str:
    return quote(str(segment), safe="")


def _dec(segment: str) -> str:
    return unquote(segment)


def source_locator_segment(*, engine: str | None, kind: str) -> str:
    """Engine for database Sources; kind for non-database.

    Empty engine and empty kind are rejected — callers must pass an explicit
    identity segment rather than relying on silent defaults.
    """
    if engine is not None and str(engine).strip():
        return str(engine).strip().lower()
    cleaned_kind = (kind or "").strip().lower()
    if not cleaned_kind:
        raise LocatorInvalid("Source locator requires engine or kind")
    return cleaned_kind


def format_source_locator(*, engine: str | None, kind: str, key: str) -> str:
    return f"src/{_enc(source_locator_segment(engine=engine, kind=kind))}/{_enc(key)}"


def format_object_locator(
    *,
    engine: str | None,
    kind: str,
    source_key: str,
    schema_name: str,
    object_type: str,
    name: str,
) -> str:
    seg = source_locator_segment(engine=engine, kind=kind)
    return (
        f"obj/{_enc(seg)}/{_enc(source_key)}/"
        f"{_enc(schema_name)}/{_enc(object_type)}/{_enc(name)}"
    )


def format_column_locator(
    *,
    engine: str | None,
    kind: str,
    source_key: str,
    schema_name: str,
    object_type: str,
    name: str,
    column_name: str,
    field_kind: str = "column",
) -> str:
    seg = source_locator_segment(engine=engine, kind=kind)
    return (
        f"col/{_enc(seg)}/{_enc(source_key)}/"
        f"{_enc(schema_name)}/{_enc(object_type)}/{_enc(name)}/"
        f"{_enc(field_kind)}/{_enc(column_name)}"
    )


@dataclass(frozen=True)
class SourceLocator:
    engine_or_kind: str
    source_key: str


@dataclass(frozen=True)
class ObjectLocator:
    engine_or_kind: str
    source_key: str
    schema_name: str
    object_type: str
    name: str


@dataclass(frozen=True)
class ColumnLocator:
    engine_or_kind: str
    source_key: str
    schema_name: str
    object_type: str
    name: str
    field_kind: str
    column_name: str


def parse_source_locator(locator_key: str) -> SourceLocator:
    parts = (locator_key or "").split("/")
    if len(parts) != 3 or parts[0] != "src":
        raise LocatorInvalid(f"Invalid source locator: {locator_key}")
    return SourceLocator(
        engine_or_kind=_dec(parts[1]),
        source_key=_dec(parts[2]),
    )


def parse_object_locator(locator_key: str) -> ObjectLocator:
    parts = (locator_key or "").split("/")
    if len(parts) != 6 or parts[0] != "obj":
        raise LocatorInvalid(f"Invalid object locator: {locator_key}")
    return ObjectLocator(
        engine_or_kind=_dec(parts[1]),
        source_key=_dec(parts[2]),
        schema_name=_dec(parts[3]),
        object_type=_dec(parts[4]),
        name=_dec(parts[5]),
    )


def parse_column_locator(locator_key: str) -> ColumnLocator:
    parts = (locator_key or "").split("/")
    if len(parts) != 8 or parts[0] != "col":
        raise LocatorInvalid(f"Invalid column locator: {locator_key}")
    return ColumnLocator(
        engine_or_kind=_dec(parts[1]),
        source_key=_dec(parts[2]),
        schema_name=_dec(parts[3]),
        object_type=_dec(parts[4]),
        name=_dec(parts[5]),
        field_kind=_dec(parts[6]),
        column_name=_dec(parts[7]),
    )
