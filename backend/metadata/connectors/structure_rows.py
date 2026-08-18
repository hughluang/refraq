"""Flat structure-collect rows and a pure assembler into CollectedStructure."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from backend.metadata.connectors.base import (
    CollectedColumn,
    CollectedForeignKey,
    CollectedIndex,
    CollectedObject,
    CollectedStructure,
    CollectProgress,
)


@dataclass(frozen=True)
class ObjectRow:
    object_key: str
    schema_name: str
    name: str
    object_type: str
    comment: str | None = None


@dataclass(frozen=True)
class ColumnRow:
    object_key: str
    name: str
    ordinal: int
    data_type: str
    nullable: bool
    default_value: str | None = None
    comment: str | None = None


@dataclass(frozen=True)
class KeyColumnRow:
    object_key: str
    name: str
    ordinal: int


@dataclass(frozen=True)
class ForeignKeyColumnRow:
    object_key: str
    constraint_name: str
    column_name: str
    ref_schema: str
    ref_table: str
    ref_column: str
    ordinal: int


@dataclass(frozen=True)
class IndexColumnRow:
    object_key: str
    index_name: str
    column_name: str
    ordinal: int
    is_unique: bool


@dataclass(frozen=True)
class DefinitionRow:
    object_key: str
    ddl: str | None


@dataclass
class StructureRows:
    objects: Iterable[ObjectRow]
    columns: Iterable[ColumnRow] = field(default_factory=list)
    primary_keys: Iterable[KeyColumnRow] = field(default_factory=list)
    foreign_keys: Iterable[ForeignKeyColumnRow] = field(default_factory=list)
    indexes: Iterable[IndexColumnRow] = field(default_factory=list)
    definitions: Iterable[DefinitionRow] = field(default_factory=list)


def stream_mappings(
    conn: object,
    sql: object,
    params: dict[str, object],
    *,
    yield_per: int = 1000,
) -> Iterator[Any]:
    """Iterate a SQLAlchemy result as mapping rows without materializing it."""
    result = conn.execution_options(yield_per=yield_per).execute(sql, params)  # type: ignore[attr-defined]
    yield from result.mappings()


def assemble(
    rows: StructureRows,
    progress: CollectProgress | None = None,
) -> CollectedStructure:
    """Group six schema-scoped fetches into CollectedStructure."""
    objects: dict[str, _ObjectBuild] = {}
    for obj in rows.objects:
        if obj.object_key in objects:
            raise ValueError(
                f"duplicate object_key {obj.object_key!r} "
                f"({obj.schema_name}.{obj.name} {obj.object_type})"
            )
        objects[obj.object_key] = _ObjectBuild(
            schema_name=obj.schema_name,
            name=obj.name,
            object_type=obj.object_type,
            comment=obj.comment,
        )

    column_count = _consume_columns(objects, rows.columns)
    pk_count = _consume_primary_keys(objects, rows.primary_keys)
    fk_count = _consume_foreign_keys(objects, rows.foreign_keys)
    index_count = _consume_indexes(objects, rows.indexes)
    definition_count = _consume_definitions(objects, rows.definitions)
    if progress is not None:
        progress.fetched("columns", column_count)
        progress.fetched("primary_keys", pk_count)
        progress.fetched("foreign_keys", fk_count)
        progress.fetched("indexes", index_count)
        progress.fetched("definitions", definition_count)

    collected = [
        builder.to_collected()
        for builder in objects.values()
    ]
    if progress is not None:
        progress.assembled(len(collected))
    return CollectedStructure(objects=collected)


@dataclass
class _ObjectBuild:
    schema_name: str
    name: str
    object_type: str
    comment: str | None
    columns: list[CollectedColumn] = field(default_factory=list)
    primary_key: list[tuple[int, str]] = field(default_factory=list)
    foreign_keys: dict[str, _ForeignKeyBuild] = field(default_factory=dict)
    indexes: dict[str, _IndexBuild] = field(default_factory=dict)
    ddl: str | None = None

    def to_collected(self) -> CollectedObject:
        return CollectedObject(
            schema_name=self.schema_name,
            name=self.name,
            object_type=self.object_type,
            columns=sorted(self.columns, key=lambda col: col.ordinal),
            ddl=self.ddl,
            comment=self.comment,
            primary_key=[name for _, name in sorted(self.primary_key)],
            foreign_keys=[
                fk.to_collected()
                for fk in sorted(self.foreign_keys.values(), key=lambda item: item.name)
            ],
            indexes=[
                idx.to_collected()
                for idx in sorted(self.indexes.values(), key=lambda item: item.name)
            ],
        )


@dataclass
class _ForeignKeyBuild:
    name: str
    ref_schema: str
    ref_table: str
    columns: list[tuple[int, str]] = field(default_factory=list)
    ref_columns: list[tuple[int, str]] = field(default_factory=list)

    def to_collected(self) -> CollectedForeignKey:
        return CollectedForeignKey(
            name=self.name,
            columns=[name for _, name in sorted(self.columns)],
            ref_schema=self.ref_schema,
            ref_table=self.ref_table,
            ref_columns=[name for _, name in sorted(self.ref_columns)],
        )


@dataclass
class _IndexBuild:
    name: str
    is_unique: bool
    columns: list[tuple[int, str]] = field(default_factory=list)

    def to_collected(self) -> CollectedIndex:
        return CollectedIndex(
            name=self.name,
            columns=[name for _, name in sorted(self.columns)],
            is_unique=self.is_unique,
        )


def _consume_columns(
    objects: dict[str, _ObjectBuild], rows: Iterable[ColumnRow]
) -> int:
    count = 0
    for row in rows:
        count += 1
        builder = objects.get(row.object_key)
        if builder is None:
            continue
        builder.columns.append(
            CollectedColumn(
                name=row.name,
                ordinal=row.ordinal,
                data_type=row.data_type,
                nullable=row.nullable,
                default_value=row.default_value,
                comment=row.comment,
            )
        )
    return count


def _consume_primary_keys(
    objects: dict[str, _ObjectBuild], rows: Iterable[KeyColumnRow]
) -> int:
    count = 0
    for row in rows:
        count += 1
        builder = objects.get(row.object_key)
        if builder is None:
            continue
        builder.primary_key.append((row.ordinal, row.name))
    return count


def _consume_foreign_keys(
    objects: dict[str, _ObjectBuild], rows: Iterable[ForeignKeyColumnRow]
) -> int:
    count = 0
    for row in rows:
        count += 1
        builder = objects.get(row.object_key)
        if builder is None:
            continue
        fk = builder.foreign_keys.get(row.constraint_name)
        if fk is None:
            fk = _ForeignKeyBuild(
                name=row.constraint_name,
                ref_schema=row.ref_schema,
                ref_table=row.ref_table,
            )
            builder.foreign_keys[row.constraint_name] = fk
        fk.columns.append((row.ordinal, row.column_name))
        fk.ref_columns.append((row.ordinal, row.ref_column))
    return count


def _consume_indexes(
    objects: dict[str, _ObjectBuild], rows: Iterable[IndexColumnRow]
) -> int:
    count = 0
    for row in rows:
        count += 1
        builder = objects.get(row.object_key)
        if builder is None:
            continue
        idx = builder.indexes.get(row.index_name)
        if idx is None:
            idx = _IndexBuild(name=row.index_name, is_unique=row.is_unique)
            builder.indexes[row.index_name] = idx
        idx.columns.append((row.ordinal, row.column_name))
    return count


def _consume_definitions(
    objects: dict[str, _ObjectBuild], rows: Iterable[DefinitionRow]
) -> int:
    count = 0
    for row in rows:
        count += 1
        builder = objects.get(row.object_key)
        if builder is None:
            continue
        builder.ddl = row.ddl
    return count
